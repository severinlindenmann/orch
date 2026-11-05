"""orch run start: a detached wrapper runs the agent, records its session, delivers pending input once."""

import json
import os
import shlex
import signal
import stat
import sys
import time
from pathlib import Path

import pytest

from orch import config, runs, tickets

AGENT = Path(__file__).resolve().parents[2] / "e2e" / "fixtures" / "generic-agent" / "agent.py"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="detached wrapper tests use shell stubs")


@pytest.fixture
def gen(proj, monkeypatch):
    """The generic fake agent as the folder's agent; its log says what it was told."""
    log = proj.parent / f"{proj.name}-agent.log"
    monkeypatch.setenv("ORCH_CMD", f"{shlex.quote(sys.executable)} -m orch")
    monkeypatch.setenv("GENERIC_AGENT_LOG", str(log))

    def _set(extra=""):
        cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(AGENT))} {extra} {{prompt}}"
        config.add_agent(proj, "fake", cmd)
        config.set_key(proj, "workspace", "agent", "fake")
        return log

    return _set


def _wait(proj, tid, gone=True, timeout=25):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if (runs.read(proj, tid) is None) == gone:
            return
        time.sleep(0.05)
    raise AssertionError(f"claim on {tid} did not {'end' if gone else 'appear'}: {runs.read(proj, tid)}")


def _lines(log, kind):
    if not log.exists():
        return []
    return [
        ln.split(": ", 1)[1]
        for ln in log.read_text(encoding="utf-8").splitlines()
        if ln.startswith(kind + ":")
    ]


def _ticket_with_check(proj, run, title="Do the thing"):
    tid = json.loads(run("ticket", "new", title, "--json", "--by", "human:t")[1])["id"]
    run("check", "add", tid, "Step one", "--by", "human:t")
    return tid


def test_start_runs_the_agent_and_it_works_the_ticket(proj, run, gen):
    log = gen()
    tid = _ticket_with_check(proj, run)
    code, out, err = run("start" if False else "run", "start", tid, "--by", "agent:focus", "--json")
    assert code == 0
    r = json.loads(out)
    assert r["resumed"] is False and r["agent"] == "fake" and r["log"].startswith(".orch/run/logs/")
    assert "Using agent command from this folder's settings:" in err and "agent.py" in err
    _wait(proj, tid)
    t = tickets.load(proj, tid)
    assert t["checklist"][0]["done"] is True  # the agent ran `orch check done` inside the run
    assert "Do the thing" in _lines(log, "prompt")[0]
    env = _lines(log, "env")[0].split()
    assert env[0] == r["run"] and env[1:] == [tid, "fake"]  # ORCH_RUN, ORCH_TICKET, ORCH_AGENT
    assert (proj / r["log"]).exists() and not t.get("sessions")  # a generic agent has no session


def test_second_start_gets_exit_2_and_the_event_goes_in_after_exactly_once(proj, run, gen):
    log = gen("--silent 1.5")
    tid = _ticket_with_check(proj, run)
    assert run("run", "start", tid)[0] == 0
    _wait(proj, tid, gone=False)
    code, out, _ = run("run", "start", tid, "--by", "agent:phone", "--text", "Also add October", "--json")
    j = json.loads(out)
    assert code == 2 and j["pending"] is True
    _wait(proj, tid)
    prompts = _lines(log, "prompt")
    assert len(prompts) == 2 and "Also add October" in prompts[1] and "Also add October" not in prompts[0]
    assert runs.undelivered(proj, tid) == []
    items = runs._pending_read(proj, tid)
    assert len(items) == 1 and items[0]["delivered_at"]


def test_killed_wrapper_loses_no_input_and_it_is_delivered_once_after_restart(proj, run, gen):
    log = gen("--silent 1.5")
    tid = _ticket_with_check(proj, run)
    run("run", "start", tid)
    _wait(proj, tid, gone=False)
    pid = runs.read(proj, tid)["pid"]
    runs.pending_add(proj, tid, "phone", "message", "Use CHF")
    os.kill(pid, signal.SIGKILL)  # the wrapper we started
    os.waitpid(pid, 0)  # this test is its parent (a real `orch run start` exits and init reaps it)
    assert runs.state(runs.read(proj, tid)) == "dead"
    assert [i["text"] for i in runs.undelivered(proj, tid)] == ["Use CHF"]
    code, out, _ = run("run", "start", tid, "--json")  # a dead claim is taken over without asking
    assert code == 0
    _wait(proj, tid)
    told = [p for p in _lines(log, "prompt") if "Use CHF" in p]
    assert len(told) == 1 and runs.undelivered(proj, tid) == []


def _fake_claude(tmp_path, monkeypatch, resume_works):
    d = tmp_path / "clbin"
    d.mkdir()
    out = tmp_path / "claude-calls.txt"
    f = d / "claude"
    f.write_text(
        "#!/bin/sh\n"
        f'echo "$*" | tr "\\n" " " >> {shlex.quote(str(out))}; echo >> {shlex.quote(str(out))}\n'
        + ("" if resume_works else 'for a in "$@"; do [ "$a" = "--resume" ] && exit 1; done\n')
        + "exit 0\n"
    )
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    return out


def test_resume_is_used_when_there_is_a_session_and_allow_goes_to_argv_only(proj, run, tmp_path, monkeypatch):
    calls = _fake_claude(tmp_path, monkeypatch, resume_works=True)
    config.set_key(proj, "workspace", "agent", "claude")
    tid = _ticket_with_check(proj, run)
    old = "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"
    tickets.record_session(proj, tid, "claude", old, runs.host())
    code, out, err = run("run", "start", tid, "--allow", "Bash(git push:*)", "--json")
    assert code == 0 and json.loads(out)["resumed"] is True and err == ""
    _wait(proj, tid)
    line = calls.read_text(encoding="utf-8").splitlines()[0]
    assert f"--resume {old}" in line and "--allowedTools Bash(git push:*)" in line
    assert tickets.sessions_for(tickets.load(proj, tid), "claude", runs.host()) == old
    # nothing was written for the allowance
    assert not (proj / ".claude").exists() and not list(proj.glob("**/settings*.json"))
    # --fresh starts a new conversation and records its id
    assert run("run", "start", tid, "--fresh")[0] == 0
    _wait(proj, tid)
    second = calls.read_text(encoding="utf-8").splitlines()[1]
    assert "--session-id" in second and "--resume" not in second
    assert tickets.sessions_for(tickets.load(proj, tid), "claude", runs.host()) != old


def test_failed_resume_falls_back_to_fresh_once_and_records_the_new_id(proj, run, tmp_path, monkeypatch):
    calls = _fake_claude(tmp_path, monkeypatch, resume_works=False)
    config.set_key(proj, "workspace", "agent", "claude")
    tid = _ticket_with_check(proj, run)
    old = "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"
    tickets.record_session(proj, tid, "claude", old, runs.host())
    assert run("run", "start", tid)[0] == 0
    _wait(proj, tid)
    lines = calls.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and "--resume" in lines[0] and "--session-id" in lines[1]
    new = tickets.sessions_for(tickets.load(proj, tid), "claude", runs.host())
    assert new and new != old and new in lines[1]


def test_allow_is_ignored_with_one_notice_by_an_adapter_that_cannot_use_it(proj, run, gen):
    log = gen()
    tid = _ticket_with_check(proj, run)
    code, out, err = run("run", "start", tid, "--allow", "Bash(rm:*)", "--json")
    assert code == 0 and "--allow was ignored" in err
    _wait(proj, tid)
    assert "Bash(rm:*)" not in " ".join(_lines(log, "prompt"))


def test_codex_session_comes_from_the_output(proj, run, tmp_path, monkeypatch):
    d = tmp_path / "cxbin"
    d.mkdir()
    fx = Path(__file__).resolve().parents[2] / "e2e" / "fixtures" / "agent-output" / "codex-exec-json.jsonl"
    f = d / "codex"
    f.write_text(f"#!/bin/sh\ncat {shlex.quote(str(fx))}\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    config.set_key(proj, "workspace", "agent", "codex")
    tid = _ticket_with_check(proj, run)
    assert run("run", "start", tid)[0] == 0
    _wait(proj, tid)
    assert (
        tickets.sessions_for(tickets.load(proj, tid), "codex", runs.host())
        == "01a1ad41-d898-7323-a687-0b497c12a830"
    )


def test_wrap_refuses_a_stdin_file_outside_the_run_folder(proj, run, gen):
    gen()
    tid = _ticket_with_check(proj, run)
    rec = runs.claim(proj, tid, "x", "fake")
    victim = proj / "keep.txt"
    victim.write_text("data")
    code, _, err = run("run", "_wrap", rec["run"], "--ticket", tid, "--agent", "fake",
                       "--stdin-file", str(victim), "--", "true")  # fmt: skip
    assert code == 2 and victim.exists()
