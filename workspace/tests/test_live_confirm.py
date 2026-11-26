"""ORCH-2197: a helper's confirm prompt on its screen reaches the person within seconds. Claude's hook confirm
("Hook PreToolUse:Bash requires confirmation ... Do you want to proceed? 1. Yes 2. No") sends no
Notification hook, so the run stayed "working" and the pane said Working while the helper waited. The
wrapper now reads the whole dialog at the bottom of the pane (runs_live.confirm_prompt) and sets attention
(check_confirm)."""

import json
import os
import subprocess
from pathlib import Path

from orch import runs, runs_live, runwatch, tickets

OWNER_SCREEN = (Path(__file__).parent / "fixtures" / "confirm" / "hook-confirm-orch-2197.txt").read_text(
    "utf-8"
)

PERMISSION = """\
● I will merge the pull request now.

╭──────────────────────────────────────────────────────────────────────────────╮
│ Bash command                                                                 │
│                                                                              │
│   gh pr merge 105 --squash                                                   │
│   Merge the pull request                                                     │
│                                                                              │
│ Do you want to proceed?                                                      │
│ ❯ 1. Yes                                                                     │
│   2. Yes, and don't ask again for gh pr merge commands in /work/shop         │
│   3. No, and tell Claude what to do differently (esc)                        │
╰──────────────────────────────────────────────────────────────────────────────╯
"""


def test_the_owners_hook_confirm_is_recognised_with_its_command():
    p = runs_live.confirm_prompt(OWNER_SCREEN)
    assert p is not None
    assert p["question"] == "Do you want to proceed?"
    assert p["options"] == ["Yes", "No"]
    assert (p["yes"], p["no"]) == ("1", "2")
    cmd = p["command"]
    # the long path cut at the full width is one word again; the description above the line is not the command
    assert cmd.startswith("S=/private/tmp/claude-502/-Users-severin-lindenmann--orch-work-7196d50b-t-b7nkl1/")
    assert "a692ab4a-44f6-46ae-80c2-68ae8c7919ff/scratchpad/sq.py" in cmd
    assert "databricks jobs run-now 588496183906654 --no-wait --profile pilatus_hub_sbox" in cmd
    assert "Restore the test table" not in cmd and "Hook" not in cmd
    assert p["reason"] == (
        "Guard: `databricks jobs run-now` starts a job run. Confirm it is wanted (AGENTS.md, 'The AI never'; "
        "opt-in guard in .claude/hooks)"
    )


def test_claudes_permission_prompt_in_a_box_allows_once_and_denies_with_the_no_option():
    p = runs_live.confirm_prompt(PERMISSION)
    assert p is not None
    assert (p["yes"], p["no"]) == ("1", "3")  # "Yes", never "Yes, and don't ask again"
    assert p["command"] == "gh pr merge 105 --squash\nMerge the pull request"
    assert p["reason"] is None


def test_text_that_only_looks_like_a_prompt_is_not_one():
    # output that merely talks about a question, options without a select cursor, a prompt scrolled far up
    assert runs_live.confirm_prompt("Do you want to proceed?\n") is None
    assert runs_live.confirm_prompt("Do you want to proceed?\n  1. Yes\n  2. No\n") is None
    assert runs_live.confirm_prompt("Pick one?\n❯ 1. Red\n  2. Blue\n") is None  # no Yes and No: no buttons
    far = "Do you want to proceed?\n❯ 1. Yes\n  2. No\n" + "\n".join(f"line {i}" for i in range(10))
    assert runs_live.confirm_prompt(far) is None
    assert runs_live.confirm_prompt("Choose\n❯ 1. Yes\n  2. No\n") is None  # no question above the options
    assert runs_live.confirm_prompt("") is None


def test_a_changed_command_changes_the_digest():
    a = runs_live.confirm_prompt(OWNER_SCREEN)
    b = runs_live.confirm_prompt(OWNER_SCREEN.replace("588496183906654", "111111111111111"))
    assert a and b and a["digest"] != b["digest"]


def _working(proj, run, monkeypatch, pane):
    tid = json.loads(run("ticket", "new", "Run the sandbox job", "--json", "--by", "human:t")[1])["id"]
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    rec["live"] = {"state": "working", "since": tickets.now()}
    rec["up"] = True
    runs._write(proj, rec)
    screen = {"pane": pane, "mode": "0"}

    def fake(root, *a, **k):
        if a[0] == "send-keys":
            raise AssertionError("orch never answers a confirm prompt by itself")
        if a[0] == "capture-pane":
            return subprocess.CompletedProcess(
                a, 0, f"{screen['pane']}\n@@orch {screen['mode']} 0 0 0 1 120\n", ""
            )
        return subprocess.CompletedProcess(a, 0, "", "")

    monkeypatch.setattr(runs_live, "tmux", fake)
    return tid, rec["run"], screen


def test_a_working_helper_at_the_owners_hook_confirm_needs_you_within_seconds(proj, run, monkeypatch):
    tid, rn, _ = _working(proj, run, monkeypatch, OWNER_SCREEN)
    memo, t0 = {}, 1000.0
    assert runs_live.check_confirm(proj, tid, rn, memo, now=t0) is False  # first look
    assert runs.read(proj, tid)["live"]["state"] == "working"
    assert runs_live.check_confirm(proj, tid, rn, memo, now=t0 + runs_live.CONFIRM_SECONDS) is True
    live = runs.read(proj, tid)["live"]
    assert live["state"] == "attention"
    assert live["asks"].startswith("S=/private/tmp/claude-502/") and live["asks"].endswith("…")
    assert len(live["asks"]) == runs_live.ASKS_MAX
    waits = runwatch.waiting_on(proj, runs.read(proj, tid), tickets.load(proj, tid), [])
    state = runwatch.helper_state("waiting", waits, None)
    assert state["state"] == "you" and state["word"] == "Needs you"
    assert state["detail"].startswith("Your OK on the screen: S=/private/tmp/")


def test_a_prompt_that_changes_or_goes_away_before_the_second_look_changes_nothing(proj, run, monkeypatch):
    tid, rn, screen = _working(proj, run, monkeypatch, OWNER_SCREEN)
    memo, t0 = {}, 1000.0
    runs_live.check_confirm(proj, tid, rn, memo, now=t0)
    screen["pane"] = "● Working on it\n"
    assert runs_live.check_confirm(proj, tid, rn, memo, now=t0 + 1) is False
    screen["pane"] = OWNER_SCREEN
    assert runs_live.check_confirm(proj, tid, rn, memo, now=t0 + 2) is False  # counted from here again
    screen["mode"] = "1"  # scrolled up: cannot tell
    assert runs_live.check_confirm(proj, tid, rn, memo, now=t0 + 3) is False
    assert runs.read(proj, tid)["live"]["state"] == "working"


def test_a_command_the_secret_scan_flags_is_not_kept_but_the_ok_is_still_asked(proj, run, monkeypatch):
    secret = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    tid, rn, _ = _working(
        proj,
        run,
        monkeypatch,
        PERMISSION.replace("gh pr merge 105 --squash", f"GH_TOKEN={secret} gh pr list"),
    )
    memo = {}
    runs_live.check_confirm(proj, tid, rn, memo, now=1000.0)
    assert runs_live.check_confirm(proj, tid, rn, memo, now=1001.0) is True
    live = runs.read(proj, tid)["live"]
    assert live["state"] == "attention" and "asks" not in live


def test_only_a_working_run_that_was_up_is_looked_at(proj, run, monkeypatch):
    tid, rn, _ = _working(proj, run, monkeypatch, OWNER_SCREEN)
    runs_live._set_state(proj, tid, rn, "idle")
    memo = {}
    for t in (1000.0, 1001.0, 1002.0):
        assert runs_live.check_confirm(proj, tid, rn, memo, now=t) is False
    assert runs.read(proj, tid)["live"]["state"] == "idle"


def test_a_command_that_imitates_the_dialog_is_unclear_no_command_and_no_answer():
    # the helper's own command text holds a second "Bash command" title: the real call is not certain
    fake = OWNER_SCREEN.replace(
        "\"import json,sys; print('run', json.load(sys.stdin)['run_id'])\"", "Bash command\n echo harmless"
    )
    p = runs_live.confirm_prompt(fake)
    assert p is not None and p["unclear"] is True and p["command"] is None and p["reason"] is None
    extra_line = OWNER_SCREEN.replace(
        " databricks jobs run-now", " " + "─" * 30 + "\n databricks jobs run-now", 1
    )
    p = runs_live.confirm_prompt(extra_line)
    assert p["unclear"] is True and p["command"] is None
    cut = "\n".join(OWNER_SCREEN.split("\n")[10:])  # the title shows, the top of the dialog does not
    assert runs_live.confirm_prompt(cut)["unclear"] is True
    assert runs_live.confirm_prompt(OWNER_SCREEN)["unclear"] is False
