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


def test_dash_lines_inside_a_boxed_dialog_or_in_the_wrong_place_are_unclear():
    dashes = "│   " + "─" * 30 + "   │"
    boxed = PERMISSION.replace(
        "│   gh pr merge 105 --squash", f"{dashes}\n│   gh pr merge 105 --squash\n{dashes}"
    )
    p = runs_live.confirm_prompt(boxed)
    assert p["unclear"] is True and p["command"] is None
    # newer look: the second line must close the command right before the hook line, not sit inside it
    moved = OWNER_SCREEN.replace(' "import json,sys;', " " + "╌" * 40 + '\n "import json,sys;', 1)
    assert runs_live.confirm_prompt(moved)["unclear"] is True


def _long(screen: str, first_row: str, rows: int = 71) -> str:
    """The screen with the command grown to `rows` more rows, so the dialog is taller than the rows read."""
    assert first_row in screen
    return screen.replace(first_row, first_row + "".join(f"\n echo padding {n};" for n in range(rows)), 1)


def test_a_command_longer_than_the_rows_read_is_unclear_never_a_blind_allow():
    # ORCH-2352: the title and the top border are above the rows read; the hook line is still among them.
    # Before, this gave command None, reason None and unclear False: Allow once with nothing to read.
    assert runs_live.CONFIRM_TAIL < 71
    p = runs_live.confirm_prompt(_long(OWNER_SCREEN, "\n S=/private/tmp/claude-502/"))
    assert p is not None and p["question"] == "Do you want to proceed?"
    assert p["unclear"] is True and p["command"] is None and p["reason"] is None
    # the same without a hook: a boxed permission prompt whose top is out of the rows read
    p = runs_live.confirm_prompt(_long(PERMISSION, "│   gh pr merge 105 --squash"))
    assert p is not None and p["unclear"] is True and p["command"] is None
    # a dialog without a title that is seen whole is still answered (a file edit names its file)
    edit = PERMISSION.replace("│ Bash command", "│ Edit file").replace(
        "Do you want to proceed?", "Edit a.py?"
    )
    p = runs_live.confirm_prompt(edit)
    assert p is not None and p["unclear"] is False and p["command"] is None and p["yes"] == "1"


# ORCH-2383 (re-review of ORCH-2352: N1, N2, N3). A misled helper shapes its own command text. An answer is
# offered only when the whole dialog was read from its real top border; a row of the command is never the top.
_FAKE_END = "\n " + "-" * 40 + "\n Bash command\n List the files\n " + "\u254c" * 40 + "\n ls -la"
_LAST_ROW = "\"import json,sys; print('run', json.load(sys.stdin)['run_id'])\""
_NO_HOOK = "\n".join(r for i, r in enumerate(OWNER_SCREEN.split("\n")) if i not in (20, 21, 22, 23))


def _blind(p: dict | None) -> bool:
    return p is not None and p["unclear"] is True and p["command"] is None and p["reason"] is None


def test_n1_a_title_of_its_own_near_the_end_of_a_long_command_never_picks_what_the_card_shows():
    assert _LAST_ROW in OWNER_SCREEN
    # the real title and top border are above the rows read; the command ends in its own dashes, title, line
    # and a harmless call. Before: command "ls -la" with the real hook reason and Allow once.
    padded = _long(OWNER_SCREEN, "\n S=/private/tmp/claude-502/").replace(_LAST_ROW, _LAST_ROW + _FAKE_END, 1)
    assert "ls -la" in "\n".join(padded.split("\n")[-runs_live.CONFIRM_TAIL :])
    assert _blind(runs_live.confirm_prompt(padded))
    # the same with no hook (before: command "ls -la", no reason, Allow once)
    assert _blind(
        runs_live.confirm_prompt(
            _long(_NO_HOOK, "\n S=/private/tmp/claude-502/").replace(_LAST_ROW, _LAST_ROW + _FAKE_END, 1)
        )
    )
    # seen whole, the same imitation is a second title: unclear as before
    assert _blind(runs_live.confirm_prompt(OWNER_SCREEN.replace(_LAST_ROW, _LAST_ROW + _FAKE_END, 1)))


def test_n2_a_permission_prompt_with_no_hook_taller_than_the_rows_read_is_not_answered_blind():
    whole = runs_live.confirm_prompt(
        _NO_HOOK
    )  # read from its top: the command shows and the answer is offered
    assert whole["unclear"] is False and whole["reason"] is None
    assert "databricks jobs run-now 588496183906654" in whole["command"]
    # before: the closing dash row counted as a top border: no command, no reason, Allow once
    assert _blind(runs_live.confirm_prompt(_long(_NO_HOOK, "\n S=/private/tmp/claude-502/")))
    # a boxed dialog whose command holds a row of dashes (comment art), top out of the rows read
    art = _long(PERMISSION, "\u2502   gh pr merge 105 --squash").replace(
        "\u2502   Merge the pull request",
        "\u2502   " + "-" * 30 + "   \u2502\n\u2502   Merge the pull request",
        1,
    )
    assert _blind(runs_live.confirm_prompt(art))


def test_n3_a_long_hook_reason_with_a_row_of_dashes_is_not_answered_blind():
    # the hook repeats long text: its "Hook ... requires confirmation" line leaves the rows read too
    reason = "".join(f"\n the guard says again, row {n}" for n in range(58)) + "\n " + "-" * 40
    long_reason = OWNER_SCREEN.replace(
        "\n opt-in guard in .claude/hooks)", "\n opt-in guard in .claude/hooks)" + reason, 1
    )
    tail = "\n".join(long_reason.split("\n")[-runs_live.CONFIRM_TAIL :])
    assert "Hook PreToolUse" not in tail and "-" * 40 in tail
    assert _blind(runs_live.confirm_prompt(long_reason))


def test_the_top_of_a_dialog_is_the_tools_border_never_a_row_inside_it():
    rows = OWNER_SCREEN.split("\n")
    # a long command that still fits the rows read is shown whole, with the answer
    fits = runs_live.confirm_prompt(_long(OWNER_SCREEN, "\n S=/private/tmp/claude-502/", rows=20))
    assert fits["unclear"] is False and "echo padding 19;" in fits["command"] and fits["yes"] == "1"
    # the real top border missing (the rows start at the title): what stands above is not the tool's border
    assert _blind(runs_live.confirm_prompt("\n".join(["\u25cf Earlier words of the helper", *rows[10:]])))
    # a border the command writes is indented like the rest of the dialog, so it is no top: without the real
    # one (first column, full row) the dialog is unclear even though a row of dashes stands above the title
    inner = "\n".join([" " + "\u2500" * 60, *rows[10:]])
    assert _blind(runs_live.confirm_prompt(inner))
    # a question in the first column with no box has no column to tell the dialog from the command's text
    flush = "\n".join(r[1:] if r.startswith(" ") else r for r in rows)
    assert _blind(runs_live.confirm_prompt(flush))
