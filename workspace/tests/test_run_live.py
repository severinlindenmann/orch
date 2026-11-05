"""Live runs in tmux: start, input only when idle, hooks, attach, stop, idle close, crash, limit, fallback."""

import json
import os
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import jsonschema
import pytest
from conftest import CONTRACTS

from orch import config, runs, runs_live, tickets

AGENT = Path(__file__).resolve().parents[2] / "e2e" / "fixtures" / "generic-agent" / "agent.py"
SID = "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"
_no_tmux = pytest.mark.skipif(
    os.name == "nt" or not shutil.which("tmux"), reason="live runs need tmux (not on Windows)"
)


def needs_tmux(fn):
    return pytest.mark.slow(_no_tmux(fn))


@pytest.fixture
def lab(proj, monkeypatch):
    """Own env: the fake agents log what reaches them; the workspace's tmux server is removed at the end."""
    log = proj.parent / f"{proj.name}-agent.log"
    monkeypatch.setenv("ORCH_CMD", f"{shlex.quote(sys.executable)} -m orch")
    monkeypatch.setenv("ORCH_TEST_AGENT_LOG", str(log))
    yield log
    if shutil.which("tmux"):
        runs_live.tmux(proj, "kill-server")


def _until(fn, timeout=20.0, what=""):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError(f"timed out: {what}")


def _lines(log, kind):
    if not log.exists():
        return []
    return [
        ln.split(": ", 1)[1]
        for ln in log.read_text(encoding="utf-8").splitlines()
        if ln.startswith(kind + ":")
    ]


def _generic_live(proj):
    py = shlex.quote(sys.executable)
    config.add_agent(
        proj,
        "fake",
        f"{py} {shlex.quote(str(AGENT))} {{prompt}}",
        f"{py} {shlex.quote(str(AGENT))} --interactive",
    )
    config.set_key(proj, "workspace", "agent", "fake")


def _fake_claude(tmp_path, monkeypatch):
    """A `claude` that logs its argv, and everything typed into it."""
    d = tmp_path / "clbin"
    d.mkdir(exist_ok=True)
    calls, typed = tmp_path / "claude-calls.txt", tmp_path / "claude-typed.txt"
    f = d / "claude"
    f.write_text(
        f'#!/bin/sh\necho "$@" >> {shlex.quote(str(calls))}\nexec cat >> {shlex.quote(str(typed))}\n'
    )
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    return calls, typed


def _ticket(run, title="Do the thing"):
    tid = json.loads(run("ticket", "new", title, "--json", "--by", "human:t")[1])["id"]
    run("check", "add", tid, "Step one", "--by", "human:t")
    return tid


def _claude_live(proj):
    config.set_key(proj, "workspace", "agent", "claude")


def _hook(run, *args, stdin=None, monkeypatch=None):
    return run("run", "event", *args)


# ---------------------------------------------------------------- start, input, idle


@needs_tmux
def test_live_start_pastes_the_prompt_and_input_only_when_idle(proj, run, lab):
    _generic_live(proj)
    tid = _ticket(run)
    code, out, _ = run("run", "start", tid, "--json")
    r = json.loads(out)
    assert (
        code == 0
        and r["mode"] == "live"
        and r["tmux"] == {"socket": runs_live.socket_name(proj), "session": tid}
    )
    rec = runs.read(proj, tid)
    schema = json.loads((CONTRACTS / "run.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(rec)
    pane = runs_live.tmux(proj, "display-message", "-p", "-t", runs_live.target(tid), "#{pane_pid}")
    assert rec["mode"] == "live" and rec["pid"] == int(pane.stdout.strip())  # the claim's pid is the pane pid
    # the agent says it is ready by itself (`orch run done`): the prompt goes in once
    _until(lambda: _lines(lab, "input"), what="first prompt")
    assert "Do the thing" in _lines(lab, "input")[0]
    _until(lambda: runs.read(proj, tid)["live"]["state"] == "idle", what="idle again")
    # input while busy waits; on idle it goes in exactly once
    rec = runs.read(proj, tid)
    rec["live"]["state"] = "working"
    runs._write(proj, rec)
    code, out, _ = run("run", "send", tid, "Use CHF", "--by", "human:anna", "--json")
    assert code == 0 and json.loads(out)["delivered"] == 0
    assert [i["text"] for i in runs.undelivered(proj, tid)] == ["Use CHF"]
    code, out, _ = run("run", "done", tid)
    assert "1 message from you waiting: sent." in out
    _until(lambda: len(_lines(lab, "input")) == 2, what="the sent text")
    assert _lines(lab, "input")[1] == "From human:anna: Use CHF"
    assert runs.undelivered(proj, tid) == []
    run("run", "done", tid)
    time.sleep(0.5)
    assert len(_lines(lab, "input")) == 2  # not again


@needs_tmux
def test_send_to_an_idle_agent_goes_in_at_once(proj, run, lab):
    _generic_live(proj)
    tid = _ticket(run)
    run("run", "start", tid)
    _until(lambda: runs.read(proj, tid)["live"]["state"] == "idle" and len(_lines(lab, "input")) == 1)
    code, out, _ = run("run", "send", tid, "Also October")
    assert out.strip() == "Sent."
    _until(lambda: len(_lines(lab, "input")) == 2)


def test_send_without_a_run_is_saved_for_the_next_start(proj, run):
    tid = _ticket(run)
    code, out, _ = run("run", "send", tid, "Remember CHF", "--by", "human:anna")
    assert code == 0 and f"orch run start {tid}" in out
    assert [i["text"] for i in runs.undelivered(proj, tid)] == ["Remember CHF"]
    (proj / "note.txt").write_text("from a file")
    run("run", "send", tid, "--file", "note.txt")
    assert len(runs.undelivered(proj, tid)) == 2


def test_event_for_an_unknown_run_is_quiet(proj, run):
    code, out, err = run("run", "event", "--run", "r_nosuchrun", "--kind", "idle")
    assert code == 0 and out == "" and err == ""


# ---------------------------------------------------------------- Claude: hooks file, session id, idle close


@needs_tmux
def test_claude_live_hooks_session_idle_close_and_resume(proj, run, lab, tmp_path, monkeypatch):
    calls, typed = _fake_claude(tmp_path, monkeypatch)
    _claude_live(proj)
    tid = _ticket(run)
    code, out, _ = run("run", "start", tid, "--json")
    r = json.loads(out)
    assert code == 0 and r["mode"] == "live" and r["resumed"] is False
    hooks = proj / ".orch" / "run" / f"hooks-{r['run']}.json"
    assert oct(hooks.stat().st_mode & 0o777) == "0o600"
    cmds = {k: v[0]["hooks"][0]["command"] for k, v in json.loads(hooks.read_text())["hooks"].items()}
    assert cmds["Stop"] == f"orch run event --run {r['run']} --kind idle"
    _until(lambda: calls.exists() and calls.read_text().strip(), what="claude argv")
    argv = calls.read_text().split()
    assert argv[0] == "--session-id" and argv[2:4] == ["--permission-mode", "acceptEdits"]
    assert argv[4:] == ["--settings", str(hooks)]
    # the tool's SessionStart hook: records the id on the ticket and the prompt goes in
    proc = subprocess.run(
        [sys.executable, "-m", "orch", "run", "event", "--run", r["run"], "--kind", "session"],
        input=json.dumps({"session_id": SID}), text=True, cwd=proj, capture_output=True,
    )  # fmt: skip
    assert proc.returncode == 0 and proc.stderr == ""
    assert tickets.sessions_for(tickets.load(proj, tid), "claude", runs.host()) == SID
    _until(lambda: typed.exists() and "Do the thing" in typed.read_text(), what="prompt typed")
    # an attention hook shows in status
    run("run", "event", "--run", r["run"], "--kind", "attention")
    assert "waiting for your OK" in run("run", "status", tid)[1]
    # idle for more than the limit: closed on the next `orch run` call; the session id stays
    run("run", "event", "--run", r["run"], "--kind", "idle")
    monkeypatch.setenv("ORCH_RUN_IDLE_SECONDS", "0.01")
    time.sleep(0.1)
    run("run", "status", tid)
    assert runs.read(proj, tid) is None and not runs_live.session_exists(proj, tid)
    assert not hooks.exists()
    assert tickets.sessions_for(tickets.load(proj, tid), "claude", runs.host()) == SID
    # the next start continues that conversation
    monkeypatch.delenv("ORCH_RUN_IDLE_SECONDS")
    calls.write_text("")
    code, out, _ = run("run", "start", tid, "--json")
    assert code == 0 and json.loads(out)["resumed"] is True and json.loads(out)["session"] == SID
    _until(lambda: calls.read_text().strip(), what="resume argv")
    assert calls.read_text().split()[:2] == ["--resume", SID]


@needs_tmux
def test_a_crashed_session_is_continued_by_id(proj, run, lab, tmp_path, monkeypatch):
    calls, typed = _fake_claude(tmp_path, monkeypatch)
    _claude_live(proj)
    tid = _ticket(run)
    tickets.record_session(proj, tid, "claude", SID, runs.host())
    run("run", "start", tid)
    _until(lambda: calls.exists() and calls.read_text().strip())
    pid = runs.read(proj, tid)["pid"]
    runs_live.tmux(proj, "kill-session", "-t", runs_live.target(tid))  # the pane is gone, the record is left
    _until(
        lambda: runs.read(proj, tid) is None or runs.state(runs.read(proj, tid)) == "dead", what="dead claim"
    )
    assert not runs._running(pid, None)
    calls.write_text("")
    code, out, _ = run("run", "start", tid, "--json")
    assert code == 0 and json.loads(out)["resumed"] is True
    _until(lambda: calls.read_text().strip())
    assert calls.read_text().split()[:2] == ["--resume", SID]


# ---------------------------------------------------------------- stop, limit, attach, fallback


@needs_tmux
def test_stop_ends_the_session_and_the_agent_but_keeps_the_work(proj, run, lab):
    _generic_live(proj)
    tid = _ticket(run)
    run("run", "start", tid)
    rec = _until(lambda: (r := runs.read(proj, tid)) and r.get("agent_pid") and r, what="agent pid")
    code, out, err = run("run", "stop", tid)
    assert code == 0 and "work done so far is kept" in out, err
    assert runs.read(proj, tid) is None and not runs_live.session_exists(proj, tid)
    _until(lambda: not runs._running(rec["agent_pid"], rec["agent_pid_started"]), what="agent ended")
    assert not runs._running(rec["pid"], rec["pid_started"])
    assert run("run", "stop", tid)[1].strip() == f"Nothing is running on {tid}."


@needs_tmux
def test_at_most_four_live_sessions_and_the_fifth_starts_when_one_closes(
    proj, run, lab, tmp_path, monkeypatch
):
    _fake_claude(tmp_path, monkeypatch)
    _claude_live(proj)
    ids = [_ticket(run, f"T{i}") for i in range(5)]
    for tid in ids[:4]:
        assert run("run", "start", tid)[0] == 0
    code, out, err = run("run", "start", ids[4], "--json")
    assert code == 2 and json.loads(out)["pending"] is True and "4 live sessions" in err
    assert runs.read(proj, ids[4]) is None
    assert [i["via"] for i in runs.undelivered(proj, ids[4])] == ["slots"]
    assert run("run", "stop", ids[0])[0] == 0  # a slot opens: the waiting ticket starts
    rec = _until(lambda: runs.read(proj, ids[4]), what="fifth started")
    assert rec["mode"] == "live" and len(runs_live.live_alive(proj)) == 4


@needs_tmux
def test_attach_runs_tmux_on_the_workspace_socket(proj, run, lab, monkeypatch):
    _generic_live(proj)
    tid = _ticket(run)
    run("run", "start", tid)
    _until(lambda: runs_live.session_exists(proj, tid))
    seen = []
    monkeypatch.setattr(os, "execvpe", lambda f, argv, env: seen.append((f, argv, env)))
    run("run", "attach", tid)
    run("run", "attach", tid, "--watch")
    sock = runs_live.socket_name(proj)
    assert seen[0][1] == ["tmux", "-L", sock, "attach", "-t", f"={tid}:"]
    assert seen[1][1][-1] == "-r" and "TMUX" not in seen[0][2]
    runs_live.tmux(proj, "kill-session", "-t", runs_live.target(tid))
    code, _, err = run("run", "attach", tid)
    assert code == 2 and "No live session" in err


def test_without_tmux_the_run_is_one_turn_at_a_time(proj, run, lab, monkeypatch):
    _generic_live(proj)
    real = shutil.which
    monkeypatch.setattr(
        runs_live.shutil, "which", lambda n, *a, **k: None if n == "tmux" else real(n, *a, **k)
    )
    tid = _ticket(run)
    code, out, err = run("run", "start", tid, "--json")
    assert code == 0 and json.loads(out)["mode"] == "oneshot"
    _until(lambda: runs.read(proj, tid) is None)
    code, out, err = run(
        "run", "start", tid, "--mode", "live", "--json"
    )  # asked for live: same record, plain note
    assert code == 0 and json.loads(out)["mode"] == "oneshot" and "needs tmux" in err
    _until(lambda: runs.read(proj, tid) is None)


# ---------------------------------------------------------------- process control (no tmux needed)


@pytest.mark.skipif(os.name == "nt", reason="signals")
def test_sigterm_to_the_wrapper_ends_the_agent_through_kill_tree(proj, run, lab):
    py = shlex.quote(sys.executable)
    config.add_agent(proj, "quiet", f"{py} {shlex.quote(str(AGENT))} --silent 30 {{prompt}}")
    config.set_key(proj, "workspace", "agent", "quiet")
    tid = _ticket(run)
    run("run", "start", tid, "--mode", "oneshot")
    rec = _until(lambda: (r := runs.read(proj, tid)) and r.get("agent_pid") and r, what="agent pid")
    os.kill(rec["pid"], signal.SIGTERM)
    _until(lambda: not runs._running(rec["agent_pid"], rec["agent_pid_started"]), what="agent ended")
    _until(lambda: runs.read(proj, tid) is None, what="claim released")


@pytest.mark.skipif(os.name == "nt", reason="signals")
def test_stop_kills_an_agent_left_behind_by_a_killed_wrapper(proj, run, lab):
    py = shlex.quote(sys.executable)
    config.add_agent(proj, "quiet", f"{py} {shlex.quote(str(AGENT))} --silent 30 {{prompt}}")
    config.set_key(proj, "workspace", "agent", "quiet")
    tid = _ticket(run)
    run("run", "start", tid, "--mode", "oneshot")
    rec = _until(lambda: (r := runs.read(proj, tid)) and r.get("agent_pid") and r, what="agent pid")
    os.kill(rec["pid"], signal.SIGKILL)
    os.waitpid(rec["pid"], 0)
    assert runs._running(rec["agent_pid"], rec["agent_pid_started"])  # orphaned, still working
    assert run("run", "stop", tid)[0] == 0
    _until(lambda: not runs._running(rec["agent_pid"], rec["agent_pid_started"]), what="orphan ended")
    assert runs.read(proj, tid) is None
