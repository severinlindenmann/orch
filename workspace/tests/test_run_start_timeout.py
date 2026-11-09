"""A run that never gets an agent: after ~60 s a person is told why (run line, Chat, history, log)."""

import json
import os
import shutil
from datetime import UTC, datetime, timedelta

import pytest

from orch import adapters, chat, runs, tickets


def _ago(seconds):
    return (datetime.now(UTC) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _edit(proj, tid, **fields):
    p = runs.record_path(proj, tid)
    rec = json.loads(p.read_text(encoding="utf-8"))
    rec.update(fields)
    p.write_text(json.dumps(rec), encoding="utf-8")


def _start(proj, tid, **fields):
    """A start whose agent never comes: the claim exists, its wrapper is this (live) test process."""
    rec = runs.claim(proj, tid, "human:tester", "claude", pid=os.getpid())
    _edit(proj, tid, started_at=_ago(fields.pop("age", 90)), **fields)
    return rec


@pytest.fixture(autouse=True)
def _no_kill(monkeypatch):
    monkeypatch.setattr(runs, "kill_tree", lambda *a, **k: None)  # the wrapper is the test process itself
    monkeypatch.setattr(runs.shutil, "which", lambda b: "/usr/bin/" + b)  # the agent command exists


def test_no_agent_after_60s_ends_the_run_and_the_ticket_says_why(proj, new_ticket):
    tid = new_ticket()
    rec = _start(proj, tid)
    text = runs.check_start_timeout(proj, tid)
    assert text == "Couldn't start the agent: no agent session appeared"
    assert runs.read(proj, tid) is None  # released: the ticket is free
    t = tickets.load(proj, tid)
    assert t["status"] == "waiting" and t["waiting_on"]["ref"] == text  # the run line shows the reason
    assert any(text in h.get("text", "") for h in t["history"])  # logged in the history
    assert rec["run"]  # and nobody is "working" any more


def test_a_young_run_or_one_with_an_agent_is_left_alone(proj, new_ticket):
    tid = new_ticket()
    _start(proj, tid, age=10)
    assert runs.check_start_timeout(proj, tid) is None and runs.read(proj, tid)
    _edit(proj, tid, started_at=_ago(300), agent_pid=os.getpid())  # the agent process exists
    assert runs.check_start_timeout(proj, tid) is None and runs.read(proj, tid)


def test_live_run_still_starting_counts_as_no_agent(proj, new_ticket, monkeypatch):
    from orch import runs_live

    tid = new_ticket()
    _start(proj, tid, mode="live", age=200, live={"state": "starting", "since": _ago(100)})
    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: True)
    monkeypatch.setattr(runs_live, "tmux", lambda *a, **k: None)
    assert runs.check_start_timeout(proj, tid) == "Couldn't start the agent: no agent session appeared"
    tid2 = new_ticket("Two")
    _start(
        proj, tid2, mode="live", age=200, live={"state": "idle", "since": _ago(100)}
    )  # the tool reported in
    assert runs.check_start_timeout(proj, tid2) is None


def test_reason_is_the_real_cause_when_known(proj, new_ticket, monkeypatch):
    tid = new_ticket()
    rec = _start(proj, tid, log=".orch/run/logs/x.log")
    log = proj / ".orch/run/logs/x.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("starting\nError: Not logged in. Run claude login\n")
    assert runs.start_failure_reason(proj, runs.read(proj, tid)) == "no login"
    monkeypatch.setattr(runs.shutil, "which", lambda b: None)  # the command is gone
    assert runs.start_failure_reason(proj, runs.read(proj, tid)) == "agent command not found"
    monkeypatch.setattr(runs.shutil, "which", lambda b: "/x/" + b)
    log.write_text("segfault in launcher\n")
    assert runs.start_failure_reason(proj, runs.read(proj, tid)) == "no agent session appeared"
    assert rec["run"]


def test_tmux_failure_is_named_for_a_live_run(proj, new_ticket, monkeypatch):
    from orch import runs_live

    tid = new_ticket()
    _start(proj, tid, mode="live", live={"state": "starting", "since": _ago(100)})
    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: False)
    assert runs.start_failure_reason(proj, runs.read(proj, tid)) == "couldn't open the terminal session"


def test_chat_gets_a_message_instead_of_thinking_forever(proj, monkeypatch):
    gid = tickets.ensure_general(proj, "human:tester")
    _start(proj, gid)
    st = chat.status(proj)  # the dashboard polls this
    assert st["running"] is False
    texts = [m["text"] for m in st["messages"]]
    assert "Couldn't start the agent: no agent session appeared" in texts
    last = st["messages"][-1]
    assert last["by"] != "you"  # from the workspace: the dashboard shows it instead of "is thinking"
    assert tickets.load(proj, gid)["status"] != "waiting"  # Chat is not parked as Waiting


def test_run_status_polling_triggers_it(proj, new_ticket, run):
    tid = new_ticket()
    _start(proj, tid)
    code, out, err = run("run", "status", tid, "--json")
    assert code == 0, err
    assert runs.read(proj, tid) is None
    assert tickets.load(proj, tid)["waiting_on"]["ref"].startswith("Couldn't start the agent")


def test_a_fake_agent_that_never_starts_end_to_end(proj, new_ticket, monkeypatch):
    """runs.start with an agent command that does not exist: the wrapper cannot launch it."""
    tid = new_ticket()
    monkeypatch.setenv("ORCH_RUN_START_TIMEOUT_SECONDS", "0")
    monkeypatch.setattr(
        adapters, "load", lambda name, root=None: {"label": "Fake", "detect": {"binary": "nope"}}
    )
    monkeypatch.setattr(runs.shutil, "which", lambda b: None)
    rec = runs.claim(proj, tid, "human:tester", "fake", pid=os.getpid())
    assert rec["run"]
    text = runs.check_start_timeout(proj, tid, at=datetime.now(UTC).timestamp() + 5)
    assert text == "Couldn't start the agent: agent command not found"


def test_no_raw_log_text_ever_reaches_the_reason_or_the_ticket(proj, new_ticket):
    """A log tail with a key: the reason is a fixed message; no key in history, status or what orch adds."""
    tid = new_ticket()
    key = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef"
    _start(proj, tid, log=".orch/run/logs/k.log")
    log = proj / ".orch/run/logs/k.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    original = f"Not logged in. ANTHROPIC_API_KEY={key} https://user:{key}@evil.example/x\n"
    log.write_text(original)  # the agent's own output stays as it is
    text = runs.check_start_timeout(proj, tid)
    assert text == "Couldn't start the agent: no login"
    t = tickets.load(proj, tid)
    assert key not in json.dumps(t) and key not in text
    added = log.read_text()[len(original) :]  # what orch appended: the reason and a redacted detail
    assert key not in added and "the agent's last line was" in added and "[hidden]" in added


def test_orch_is_syncing_is_a_known_cause(proj, new_ticket, monkeypatch):
    from orch import syncgate

    tid = new_ticket()
    _start(proj, tid)
    monkeypatch.setattr(syncgate, "live_holder", lambda root: {"pid": 1})
    assert runs.start_failure_reason(proj, runs.read(proj, tid)) == "orch is syncing"


def test_live_runs_get_three_times_the_time_and_a_session_with_output_counts_as_alive(
    proj, new_ticket, monkeypatch
):
    from orch import runs_live

    tid = new_ticket()
    _start(proj, tid, mode="live", age=100, live={"state": "starting", "since": _ago(100)})
    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: True)
    monkeypatch.setattr(runs_live, "tmux", lambda *a, **k: None)
    assert runs.check_start_timeout(proj, tid) is None  # 100 s < 180 s
    _edit(proj, tid, started_at=_ago(200))
    pane = type("P", (), {"returncode": 0, "stdout": "Welcome to the tool\n"})()
    monkeypatch.setattr(runs_live, "tmux", lambda *a, **k: pane)
    assert runs.check_start_timeout(proj, tid) is None  # the session shows output: it is starting up
    assert runs.read(proj, tid)
    pane.stdout = "   \n"
    assert runs.check_start_timeout(proj, tid) is not None  # an empty pane after 200 s: no agent


def test_another_machines_claim_is_not_ours_to_judge(proj, new_ticket):
    tid = new_ticket()
    _start(proj, tid, host="some-other-machine")
    assert runs.check_start_timeout(proj, tid) is None and runs.read(proj, tid)
    _edit(proj, tid, host=None)  # no host recorded either: skipped
    assert runs.check_start_timeout(proj, tid) is None


def test_a_run_that_gets_its_agent_while_we_decide_is_left_alone(proj, new_ticket, monkeypatch):
    tid = new_ticket()
    _start(proj, tid)
    real = runs.start_failure_reason

    def late(root, rec):  # the agent comes up between the first look and the locked decision
        _edit(proj, tid, agent_pid=os.getpid())
        return real(root, rec)

    monkeypatch.setattr(runs, "start_failure_reason", late)
    assert runs.check_start_timeout(proj, tid) is None
    assert runs.read(proj, tid) and tickets.load(proj, tid)["status"] == "active"


def test_the_wrapper_is_only_killed_after_the_release_and_only_with_a_recorded_start(
    proj, new_ticket, monkeypatch
):
    tid = new_ticket()
    seen = []
    monkeypatch.setattr(runs, "kill_tree", lambda pid, *a, **k: seen.append((pid, runs.read(proj, tid))))
    _start(proj, tid)
    assert runs.check_start_timeout(proj, tid)
    assert len(seen) == 1 and seen[0][1] is None  # the claim was already gone when it was killed
    tid2 = new_ticket("Two")
    _start(proj, tid2, pid_started=None)  # no start time recorded: never killed (the pid may be reused)
    assert runs.check_start_timeout(proj, tid2)
    assert len(seen) == 1


def test_live_leftover_session_is_killed_by_exact_name(proj, new_ticket, monkeypatch):
    from orch import runs_live

    tid = new_ticket()
    _start(proj, tid, mode="live", age=200, live={"state": "starting", "since": _ago(100)})
    calls = []
    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: True)
    monkeypatch.setattr(
        runs_live,
        "tmux",
        lambda root, *a, **k: calls.append(a) or type("P", (), {"returncode": 0, "stdout": ""})(),
    )
    assert runs.check_start_timeout(proj, tid)
    kill = next(c for c in calls if c[0] == "kill-session")
    assert kill == ("kill-session", "-t", f"={tid}:")  # exact match, not a prefix


def test_a_static_screen_stops_counting_as_alive_after_60s(proj, new_ticket, monkeypatch):
    """An error with an open shell must still time out: only a screen that CHANGED within 60 s is alive."""
    from orch import runs_live

    tid = new_ticket()
    _start(proj, tid, mode="live", age=200, live={"state": "starting", "since": _ago(100)})
    pane = type("P", (), {"returncode": 0, "stdout": "error: could not start\n$ "})()
    monkeypatch.setattr(runs_live, "session_exists", lambda root, t: True)
    monkeypatch.setattr(runs_live, "tmux", lambda *a, **k: pane)
    now = datetime.now(UTC).timestamp()
    assert runs.check_start_timeout(proj, tid, at=now) is None  # first sight of this screen: a change
    assert runs.check_start_timeout(proj, tid, at=now + 30) is None  # unchanged, but only 30 s
    pane.stdout = "error: could not start\n$ ls\n"  # something moved: the clock starts again
    assert runs.check_start_timeout(proj, tid, at=now + 70) is None
    text = runs.check_start_timeout(proj, tid, at=now + 140)  # 70 s of the same screen
    assert text == "Couldn't start the agent: no agent session appeared"
    assert runs.read(proj, tid) is None


def test_the_log_detail_is_the_agents_last_line_not_orchs_own(proj, new_ticket):
    tid = new_ticket()
    _start(proj, tid, log=".orch/run/logs/d.log")
    log = proj / ".orch/run/logs/d.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("starting\nthe agent said this last\n")
    assert runs.check_start_timeout(proj, tid)
    lines = log.read_text().splitlines()
    assert lines[-2:] == [
        "Couldn't start the agent: no agent session appeared",
        "orch: the agent's last line was: the agent said this last",
    ]


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux is not installed")
def test_target_is_an_exact_name_for_capture_pane_and_kill_session(proj):
    """runs_live.target() is `=name:`: it finds that session and no other with the same prefix."""
    from orch import runs_live

    tid = "t_exact1"
    try:
        r = runs_live.tmux(proj, "new-session", "-d", "-s", tid, "-c", str(proj), "echo hello-pane; sleep 60")
        assert r.returncode == 0, r.stderr
        assert runs_live.target(tid) == "=t_exact1:"
        import time

        for _ in range(20):
            pane = runs_live.tmux(proj, "capture-pane", "-p", "-t", runs_live.target(tid))
            if "hello-pane" in pane.stdout:
                break
            time.sleep(0.2)
        assert pane.returncode == 0 and "hello-pane" in pane.stdout
        short = runs_live.tmux(proj, "capture-pane", "-p", "-t", runs_live.target("t_exact"))  # a prefix
        assert short.returncode != 0  # does not match t_exact1
        assert runs_live.tmux(proj, "kill-session", "-t", runs_live.target("t_exact")).returncode != 0
        assert runs_live.tmux(proj, "kill-session", "-t", runs_live.target(tid)).returncode == 0
    finally:
        runs_live.tmux(proj, "kill-server")
