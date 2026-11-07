"""A Start must show progress: the tool may run orch, one-shot output streams, a live tool stuck on a
first screen (trust this folder) is explained instead of "working", a never-pasted prompt is never nested,
attach explains a one-shot run."""

import json
import os
import shutil
import subprocess
import time

import jsonschema
import pytest
from conftest import CONTRACTS

from orch import adapters, config, runs, runs_live, tickets

TRUST_SCREEN = """ Accessing workspace:
 Quick safety check: Is this a project you created or one you trust?
 ❯ No, exit
   Yes, I trust this folder
 Enter to confirm · Esc to cancel"""

# recorded from a real first start (fresh HOME, Claude Code 2.1.319, tmux pane 200x50), trimmed
THEME_SCREEN = """ Let's get started.
 Choose the text style that looks best with your terminal
 To change this later, run /theme
     Auto (match terminal)
 ❯ ✔ Dark mode
     Light mode
     Dark mode (colorblind-friendly)
  Syntax theme: Monokai Extended (ctrl+t to disable)"""
NOTES_SCREEN = """ Security notes:
 1. Claude can make mistakes.
    You're responsible for Claude's actions and should always
    review them, especially when running code.
 2. Due to prompt injection risks, only use it with code you trust
    Learn more: https://code.claude.com/docs/en/security
 Press Enter to continue…"""
FOLDER_TRUST_SCREEN = """ Accessing workspace:
 {folder}
 Quick safety check: Is this a project you created or one you trust? (Like your own code, a well-known open \
source project, or work from your team). If not, take a moment to review what's in this
 folder first.
 Claude Code'll be able to read, edit, and execute files here.
 Security guide
 ❯ No, exit
   Yes, I trust this folder
 Enter to confirm · Esc to cancel"""
LOGIN_SCREEN = """ Claude Code can be used with your Claude subscription or billed based on API usage.
 Select login method:
 ❯ 1. Claude account with subscription · Pro, Max, Team, or Enterprise
   2. Anthropic Console account · API usage billing"""
PERMISSION_SCREEN = """ Bash command
   rm -rf build
 Do you want to proceed?
 ❯ 1. Yes
   2. Yes, and don't ask again for rm commands in this folder
   3. No, and tell Claude what to do differently (esc)"""


def _ticket(run, title="A presentation about giraffes"):
    return json.loads(run("ticket", "new", title, "--json", "--by", "human:t")[1])["id"]


def _no_tmux(monkeypatch):
    real = shutil.which
    monkeypatch.setattr(
        runs_live.shutil, "which", lambda n, *a, **k: None if n == "tmux" else real(n, *a, **k)
    )


def _valid_run(rec):
    schema = json.loads((CONTRACTS / "run.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(rec)


# ---------------------------------------------------------------- what the agent is told and allowed


def test_the_start_prompt_asks_for_tasks_and_a_summary(proj, run):
    tid = _ticket(run)
    config.set_key(proj, "workspace", "agent", "claude")
    p = runs.plan(proj, tid)
    assert f"orch check add {tid}" in p["prompt"] and f"orch ticket summary {tid}" in p["prompt"]
    assert f"orch check done {tid}" in p["prompt"]


def test_a_one_shot_claude_streams_and_may_run_orch(proj, run):
    tid = _ticket(run)
    config.set_key(proj, "workspace", "agent", "claude")
    argv = runs.plan(proj, tid, mode="oneshot")["argv"]
    head = argv[: argv.index("--")]
    assert head[head.index("--output-format") + 1] == "stream-json"
    rules = head[head.index("--allowedTools") + 1].split(",")
    assert "Bash(orch check:*)" in rules and "Bash(orch ticket summary:*)" in rules
    assert not [
        r for r in rules if r.startswith(("Bash(orch config", "Bash(orch addon", "Bash(orch run start"))
    ]


def test_a_tool_without_a_stream_gets_no_stream_args(proj, run):
    tid = _ticket(run)
    config.set_key(proj, "workspace", "agent", "codex")
    assert "--output-format" not in runs.plan(proj, tid, mode="oneshot")["argv"]


# ---------------------------------------------------------------- folder trust (adapter data only)


def _cfg(proj):
    return proj.parent / f"{proj.name}_home" / ".claude.json"


def test_trust_only_for_a_folder_set_up_with_orch_init(proj, tmp_path):
    f = _cfg(proj)
    f.write_text(json.dumps({"theme": "dark"}))
    other = tmp_path / "not-a-workspace"
    other.mkdir()
    assert adapters.trust_folder("claude", other) == "skipped"
    assert json.loads(f.read_text()) == {"theme": "dark"}


def test_trust_sets_only_the_one_key_and_keeps_the_rest(proj, run):
    run("init", "--yes")
    f = _cfg(proj)
    f.write_text(json.dumps({"theme": "dark", "projects": {"/other": {"x": 1}}}))
    f.chmod(0o600)
    assert adapters.trust_folder("claude", proj) == "set"
    doc = json.loads(f.read_text())
    assert doc["theme"] == "dark" and doc["projects"]["/other"] == {"x": 1}
    assert doc["projects"][str(proj.resolve())] == {"hasTrustDialogAccepted": True}
    if os.name != "nt":
        assert oct(f.stat().st_mode & 0o777) == "0o600"  # the file keeps its own mode
    assert adapters.trust_folder("claude", proj) == "already"
    assert not [p for p in f.parent.iterdir() if p.name.endswith(".tmp")]


def test_trust_never_touches_a_missing_or_unreadable_file(proj, run):
    run("init", "--yes")
    f = _cfg(proj)
    assert adapters.trust_folder("claude", proj) == "skipped" and not f.exists()
    f.write_text("{not json")
    assert adapters.trust_folder("claude", proj) == "skipped" and f.read_text() == "{not json"


def test_trust_never_clobbers_a_write_by_the_tool(proj, run, monkeypatch):
    run("init", "--yes")
    f = _cfg(proj)
    f.write_text(json.dumps({"n": 0}))
    real_dump = json.dump
    n = {"i": 0}

    def tool_writes_meanwhile(doc, out, **kw):
        n["i"] += 1
        f.write_text(json.dumps({"n": n["i"]}))  # the tool saves its file while orch prepares its copy
        return real_dump(doc, out, **kw)

    monkeypatch.setattr(adapters.json, "dump", tool_writes_meanwhile)
    assert adapters.trust_folder("claude", proj) == "skipped"
    assert json.loads(f.read_text()) == {"n": 3}  # the tool's last write stands


def test_a_tool_without_trust_data_is_left_alone(proj):
    assert adapters.trust_folder("codex", proj) == "none"


# ---------------------------------------------------------------- a live tool that is not up yet


def _starting(proj, run, monkeypatch, pane_text, age):
    tid = _ticket(run)
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    rec["live"] = {"state": "starting", "since": runs._iso(time.time() - age)}
    runs._write(proj, rec)
    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: True)
    monkeypatch.setattr(
        runs_live, "tmux", lambda root, *a, **k: subprocess.CompletedProcess(a, 0, pane_text, "")
    )
    return tid


def test_a_trust_question_is_shown_instead_of_working(proj, run, monkeypatch):
    tid = _starting(proj, run, monkeypatch, TRUST_SCREEN, age=5)  # the screen names no folder: never answered
    runs_live.check_starting(proj, runs.read(proj, tid), answered=[])
    rec = runs.read(proj, tid)
    _valid_run(rec)
    assert rec["live"]["state"] == "attention"
    assert rec["live"]["why"].startswith("Claude asks whether to trust this folder")
    key = tickets.load(proj, tid)["key"]
    assert f"orch run attach {key}" in rec["live"]["why"]  # the key a person knows, not the internal id
    out = run("run", "status", tid)[1]
    assert f"orch run attach {key}" in out
    assert "trust this folder" in out and "working" not in out
    # the tool's own hook, once it is up, takes over again
    run("run", "event", "--run", rec["run"], "--kind", "idle")
    assert "why" not in runs.read(proj, tid)["live"]


def test_a_live_tool_not_up_after_a_minute_asks_for_a_look(proj, run, monkeypatch):
    tid = _starting(proj, run, monkeypatch, "some screen orch does not know", age=61)
    runs_live.cleanup(proj)
    live = runs.read(proj, tid)["live"]
    assert live["state"] == "attention" and "has not started up after a minute" in live["why"]


def test_a_quiet_start_is_left_alone_for_a_minute(proj, run, monkeypatch):
    tid = _starting(proj, run, monkeypatch, "loading", age=10)
    runs_live.cleanup(proj)
    assert runs.read(proj, tid)["live"]["state"] == "starting"


# ---------------------------------------------------------------- first-run screens: passed, never a login


def _screens(proj, run, monkeypatch, panes, age=5):
    """A starting run whose pane shows the given screens in turn; returns (ticket, keys sent)."""
    tid = _ticket(run)
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    rec["live"] = {"state": "starting", "since": runs._iso(time.time() - age)}
    runs._write(proj, rec)
    panes, sent = list(panes), []

    def fake(root, *a, **k):
        if a[0] == "capture-pane":
            return subprocess.CompletedProcess(a, 0, panes.pop(0) if len(panes) > 1 else panes[0], "")
        if a[0] == "send-keys":
            sent.append((a[2], a[3]))
        return subprocess.CompletedProcess(a, 0, "", "")

    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: True)
    monkeypatch.setattr(runs_live, "tmux", fake)
    monkeypatch.setattr(runs_live, "PASTE_DELAY", 0)
    return tid, sent


def _trust(folder):
    return FOLDER_TRUST_SCREEN.replace("{folder}", str(folder))


@pytest.mark.parametrize(
    ("screen", "keys", "what"),
    [(THEME_SCREEN, ["Enter"], "theme"), (NOTES_SCREEN, ["Enter"], "notes")],
)
def test_a_harmless_first_run_screen_is_passed_once(proj, run, monkeypatch, screen, keys, what):
    tid, sent = _screens(proj, run, monkeypatch, [screen])
    answered: list[str] = []
    assert runs_live.check_starting(proj, runs.read(proj, tid), answered=answered) is None
    assert sent == [(runs_live.target(tid), k) for k in keys] and answered == [what]
    # the tool is still redrawing the same screen: nothing is sent twice
    assert runs_live.check_starting(proj, runs.read(proj, tid), answered=answered) is None
    assert len(sent) == len(keys)
    assert runs.read(proj, tid)["live"]["state"] == "starting"


def test_the_trust_screen_is_answered_yes_only_for_the_orch_init_folder(proj, run, monkeypatch):
    run("init", "--yes")
    tid, sent = _screens(proj, run, monkeypatch, [_trust(proj.resolve())])
    answered: list[str] = []
    assert runs_live.check_starting(proj, runs.read(proj, tid), answered=answered) is None
    assert [k for _, k in sent] == ["Down", "Enter"] and answered == ["folder trust"]


def test_the_trust_screen_for_another_folder_is_not_answered(proj, run, monkeypatch, tmp_path):
    run("init", "--yes")
    tid, sent = _screens(proj, run, monkeypatch, [_trust(tmp_path / "elsewhere")])
    note = runs_live.check_starting(proj, runs.read(proj, tid), answered=[])
    assert sent == [] and note.startswith("Claude asks whether to trust this folder")
    assert runs.read(proj, tid)["live"]["state"] == "attention"


def test_the_trust_screen_without_orch_init_is_not_answered(proj, run, monkeypatch):
    tid, sent = _screens(proj, run, monkeypatch, [_trust(proj.resolve())])
    monkeypatch.setattr(runs_live.adapters, "orch_folder", lambda root: False)
    assert runs_live.check_starting(proj, runs.read(proj, tid), answered=[]) is not None
    assert sent == []


@pytest.mark.parametrize("screen", [LOGIN_SCREEN, THEME_SCREEN + "\n" + LOGIN_SCREEN, PERMISSION_SCREEN])
def test_a_login_or_permission_screen_is_never_answered(proj, run, monkeypatch, screen):
    tid, sent = _screens(proj, run, monkeypatch, [screen], age=61)
    note = runs_live.check_starting(proj, runs.read(proj, tid), answered=[])
    assert sent == [] and note
    if "login" in screen:
        assert note.startswith("Claude wants a login") and "orch run attach" in note


def test_only_the_runs_own_wrapper_answers(proj, run, monkeypatch):
    tid, sent = _screens(proj, run, monkeypatch, [THEME_SCREEN])
    runs_live.cleanup(proj)  # any other orch command: leaves the screen to the wrapper
    assert sent == [] and runs.read(proj, tid)["live"]["state"] == "starting"


class _Proc:
    def __init__(self):
        self.n = 0

    def poll(self):
        return None


def test_the_wrapper_passes_the_first_run_screens_and_says_so_once(proj, run, monkeypatch):
    run("init", "--yes")
    screens = [THEME_SCREEN, THEME_SCREEN, NOTES_SCREEN, _trust(proj.resolve()), "loading"]
    tid, sent = _screens(proj, run, monkeypatch, screens)
    rec = runs.read(proj, tid)
    ticks = {"n": 0}

    def tick(_s):  # one second passes; after the trust answer the tool is up and its hook fires
        ticks["n"] += 1
        if ticks["n"] == len(screens):
            run("run", "event", "--run", rec["run"], "--kind", "session")

    monkeypatch.setattr(runs_live.time, "sleep", tick)
    answered = runs_live.watch_start(proj, tid, rec["run"], "claude", _Proc())
    assert answered == ["theme", "notes", "folder trust"]
    assert [k for _, k in sent] == ["Enter", "Enter", "Down", "Enter"]
    assert {t for t, _ in sent} == {runs_live.target(tid)}  # only this run's own pane
    texts = [h.get("text", "") for h in tickets.load(proj, tid)["history"]]
    said = [t for t in texts if "first-run screens" in t]
    assert said == ["Answered Claude's first-run screens (theme, notes, folder trust)."]


def test_the_wrapper_stops_at_a_login(proj, run, monkeypatch):
    tid, sent = _screens(proj, run, monkeypatch, [THEME_SCREEN, LOGIN_SCREEN])
    monkeypatch.setattr(runs_live.time, "sleep", lambda s: None)
    rec = runs.read(proj, tid)
    assert runs_live.watch_start(proj, tid, rec["run"], "claude", _Proc()) == ["theme"]
    live = runs.read(proj, tid)["live"]
    assert live["state"] == "attention" and live["why"].startswith("Claude wants a login")
    assert [k for _, k in sent] == ["Enter"]


# ---------------------------------------------------------------- a never-pasted prompt


def _start_prompt(proj, tid):
    with runs.locked(proj, tid):
        text = f"Work on orch ticket {tid}: old"
        runs._pending_add_locked(proj, tid, "human:t", "text", text, "start", None)


def test_a_prompt_never_pasted_is_dropped_when_its_run_ends(proj, run):
    tid = _ticket(run)
    rec = runs.claim(proj, tid, "human:t", "claude", "live")
    _start_prompt(proj, tid)
    runs.pending_add(proj, tid, "human:anna", "message", "Use CHF")
    runs.release(proj, tid, rec["run"])
    assert [i["text"] for i in runs.undelivered(proj, tid)] == ["Use CHF"]  # real input stays


def test_a_prompt_of_a_dead_run_is_not_nested_into_the_next(proj, run):
    tid = _ticket(run)
    config.set_key(proj, "workspace", "agent", "claude")
    rec = runs.claim(proj, tid, "human:t", "claude", "live")
    rec["pid"], rec["pid_started"] = 999_999, None  # its process is gone
    runs._write(proj, rec)
    _start_prompt(proj, tid)
    runs.claim(proj, tid, "human:t", "claude", "oneshot")
    p = runs.plan(proj, tid, mode="oneshot")
    assert p["prompt"].count("Work on orch ticket") == 1 and p["item_ids"] == []
    out = run("run", "status", tid)[1]
    assert "Queued" not in out


# ---------------------------------------------------------------- attach and the start note


def test_attach_on_a_one_shot_run_points_to_focus_and_the_log(proj, run):
    tid = _ticket(run)
    runs.claim(proj, tid, "human:t", "claude", "oneshot", pid=os.getpid())
    rec = runs.read(proj, tid)
    rec["log"] = f".orch/run/logs/{tid}-{rec['run']}.log"
    runs._write(proj, rec)
    code, _, err = run("run", "attach", tid, "--watch")
    assert code == 2 and "one step at a time" in err and f"orch focus open {tid}" in err
    assert f"tail -f {rec['log']}" in err and "Start one" not in err


def test_attach_without_tmux_says_so(proj, run, monkeypatch):
    tid = _ticket(run)
    _no_tmux(monkeypatch)
    code, _, err = run("run", "attach", tid)
    assert code == 2 and "need tmux, which is not installed" in err


@pytest.mark.skipif(os.name == "nt", reason="tmux note is for Mac and Linux")
def test_start_without_tmux_says_how_to_get_a_live_session(proj, run, monkeypatch, tmp_path):
    d = tmp_path / "clbin"
    d.mkdir()
    (d / "claude").write_text("#!/bin/sh\nexit 0\n")
    (d / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    _no_tmux(monkeypatch)
    config.set_key(proj, "workspace", "agent", "claude")
    tid = _ticket(run)
    code, out, err = run("run", "start", tid, "--json")
    assert code == 0 and json.loads(out)["mode"] == "oneshot"
    assert "brew install tmux" in err and "Focus" in err
    deadline = time.monotonic() + 15
    while runs.read(proj, tid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert tickets.load(proj, tid)["id"] == tid


def test_trust_never_replaces_a_linked_settings_file(proj, run, tmp_path):
    run("init", "--yes")
    real = tmp_path / "elsewhere.json"
    real.write_text(json.dumps({"theme": "dark"}))
    _cfg(proj).symlink_to(real)
    assert adapters.trust_folder("claude", proj) == "skipped"
    assert _cfg(proj).is_symlink() and json.loads(real.read_text()) == {"theme": "dark"}


@pytest.mark.skipif(os.name == "nt", reason="file modes")
def test_a_run_log_is_private_and_an_old_one_is_made_private(proj):
    log = proj / ".orch" / "run" / "logs" / "t_abcdef-r_abcdefgh.log"
    with runs.open_log(log) as f:
        f.write(b"one\n")
    assert oct(log.stat().st_mode & 0o777) == "0o600"
    log.chmod(0o644)
    with runs.open_log(log) as f:
        f.write(b"two\n")
    assert oct(log.stat().st_mode & 0o777) == "0o600" and log.read_bytes() == b"one\ntwo\n"


# ------------------------------------------------ one state: a start that cannot go on is Waiting


def test_a_login_at_start_leaves_the_ticket_waiting_then_working_once_up(proj, run, monkeypatch):
    tid, _ = _screens(proj, run, monkeypatch, [LOGIN_SCREEN], age=5)
    assert tickets.load(proj, tid)["status"] == "active"  # a normal start is Working
    note = runs_live.check_starting(proj, runs.read(proj, tid), answered=[])
    t = tickets.load(proj, tid)
    assert t["status"] == "waiting" and t["waiting_on"]["ref"] == note[:200]
    assert note.startswith("Claude wants a login")
    # the person signs in; the tool's own hook says it is up
    run("run", "event", "--run", runs.read(proj, tid)["run"], "--kind", "idle")
    t = tickets.load(proj, tid)
    assert t["status"] == "active" and t["waiting_on"] is None


def test_a_second_start_after_signing_in_is_working_again(proj, run, monkeypatch):
    tid, _ = _screens(proj, run, monkeypatch, [LOGIN_SCREEN], age=5)
    runs_live.check_starting(proj, runs.read(proj, tid), answered=[])
    runs.release(proj, tid)
    assert tickets.load(proj, tid)["status"] == "waiting"
    runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    assert tickets.load(proj, tid)["status"] == "active"


def test_an_agent_that_cannot_be_launched_does_not_leave_the_ticket_working(proj, run):
    tid = _ticket(run)
    rec = runs.claim(proj, tid, "human:t", "claude", "oneshot", pid=os.getpid())
    assert tickets.load(proj, tid)["status"] == "active"
    rc = runs.wrap(proj, rec["run"], tid, "claude", ["/nonexistent/agent-binary"])
    assert rc != 0
    t = tickets.load(proj, tid)
    assert t["status"] == "waiting" and "before it got going" in t["waiting_on"]["ref"]


def test_wait_for_start_moves_only_a_working_ticket(proj, run):
    tid = _ticket(run)
    for status in ("done", "review"):
        run("ticket", "status", tid, status, "--by", "human:t")
        tickets.wait_for_start(proj, tid, "x", "agent:claude")
        assert tickets.load(proj, tid)["status"] == status


def test_a_hook_of_an_old_run_does_not_resume_and_a_person_choice_stays(proj, run, monkeypatch):
    tid, _ = _screens(proj, run, monkeypatch, [LOGIN_SCREEN], age=5)
    runs_live.check_starting(proj, runs.read(proj, tid), answered=[])
    runs_live.event(proj, "idle", "r_oldrun", tid, None)
    assert tickets.load(proj, tid)["status"] == "waiting"  # the hook named another run
    tickets.set_status(proj, tid, "waiting", "human:t")  # the person keeps it waiting
    assert "start" not in tickets.load(proj, tid)["waiting_on"]
    run("run", "event", "--run", runs.read(proj, tid)["run"], "--kind", "idle")
    assert tickets.load(proj, tid)["status"] == "waiting"


def test_a_hook_resumes_only_after_the_state_is_written(proj, run, monkeypatch):
    tid, _ = _screens(proj, run, monkeypatch, [LOGIN_SCREEN], age=5)
    runs_live.check_starting(proj, runs.read(proj, tid), answered=[])
    monkeypatch.setattr(runs_live, "_set_state", lambda *a, **k: False)  # another run holds the claim
    runs_live.event(proj, "idle", None, tid, None)
    assert tickets.load(proj, tid)["status"] == "waiting"
