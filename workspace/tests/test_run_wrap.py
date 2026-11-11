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
def gen(proj, monkeypatch, subprocess_home):
    """The generic fake agent as the folder's agent; its log says what it was told."""
    log = proj.parent / f"{proj.name}-agent.log"
    monkeypatch.setenv("ORCH_CMD", f"{shlex.quote(sys.executable)} -m orch")
    monkeypatch.setenv("GENERIC_AGENT_LOG", str(log))

    def _set(extra=""):
        cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(AGENT))} {extra} {{prompt}}"
        config.add_agent(proj, "fake", cmd, approve=True)
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
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    _wait(proj, tid, gone=False)
    code, out, _ = run(
        "run",
        "start",
        tid,
        "--mode",
        "oneshot",
        "--by",
        "agent:phone",
        "--text",
        "Also add October",
        "--json",
    )
    j = json.loads(out)
    assert code == 2 and j["pending"] is True
    _wait(proj, tid)
    prompts = _lines(log, "prompt")
    assert len(prompts) == 2 and "Also add October" in prompts[1] and "Also add October" not in prompts[0]
    assert runs.undelivered(proj, tid) == []
    items = runs._pending_read(proj, tid)
    assert len(items) == 1 and items[0]["delivered_at"]


def test_killed_wrapper_with_a_live_agent_still_holds_the_ticket(proj, run, gen):
    log = gen("--silent 1.5")
    tid = _ticket_with_check(proj, run)
    run("run", "start", tid, "--mode", "oneshot")
    _wait(proj, tid, gone=False)
    rec = runs.read(proj, tid)
    end = time.monotonic() + 10
    while not runs.read(proj, tid).get("agent_pid") and time.monotonic() < end:
        time.sleep(0.05)
    rec = runs.read(proj, tid)
    assert rec["agent_pid"] and rec["agent_pid_started"]
    runs.pending_add(proj, tid, "phone", "message", "Use CHF")
    os.kill(rec["pid"], signal.SIGKILL)  # the wrapper we started
    os.waitpid(rec["pid"], 0)  # this test is its parent (a real `orch run start` exits and init reaps it)
    assert runs.state(runs.read(proj, tid)) == "alive"  # the agent still works: never two agents
    code, out, _ = run("run", "start", tid, "--mode", "oneshot", "--json")
    assert code == 2 and json.loads(out)["pending"] is True
    end = time.monotonic() + 15
    while runs.state(runs.read(proj, tid)) != "dead" and time.monotonic() < end:
        time.sleep(0.1)
    assert runs.state(runs.read(proj, tid)) == "dead"
    assert "Use CHF" in " ".join(i["text"] for i in runs.undelivered(proj, tid))
    code, out, _ = run(
        "run", "start", tid, "--mode", "oneshot", "--json"
    )  # now the dead claim is taken over without asking
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
        # orch asks which modes and which version it knows
        '[ "$1" = "--help" ] && { echo "choices: auto"; exit 0; }\n'
        '[ "$1" = "--version" ] && { echo "2.1.0 (Claude Code)"; exit 0; }\n'
        f'printf "%s " "$@" | tr "\\n" " " >> {shlex.quote(str(out))}; echo >> {shlex.quote(str(out))}\n'
        + (
            ""
            if resume_works
            else 'for a in "$@"; do [ "$a" = "--resume" ] && '
            '{ echo "No conversation found with session ID: x"; exit 1; }; done\n'
        )
        + "exit 0\n"
    )
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    return out


def test_resume_is_used_when_there_is_a_session_and_allow_goes_to_argv_only(proj, run, tmp_path, monkeypatch):
    calls = _fake_claude(tmp_path, monkeypatch, resume_works=True)
    config.set_key(proj, "workspace", "agent", "claude")
    config.set_permissions(proj, "ask")  # no `claude --help` probe in the fake's call log
    tid = _ticket_with_check(proj, run)
    old = "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"
    tickets.record_session(proj, tid, "claude", old, runs.host())
    code, out, err = run("run", "start", tid, "--mode", "oneshot", "--allow", "Bash(git push:*)", "--json")
    assert code == 0 and json.loads(out)["resumed"] is True and err == ""
    _wait(proj, tid)
    line = calls.read_text(encoding="utf-8").splitlines()[0]
    assert f"--resume {old}" in line and "--allowedTools Bash(git push:*)" in line
    assert tickets.sessions_for(proj, tid, tickets.load(proj, tid), "claude", runs.host()) == old
    # nothing was written for the allowance
    assert not (proj / ".claude").exists() and not list(proj.glob("**/settings*.json"))
    # --fresh starts a new conversation and records its id
    assert run("run", "start", tid, "--mode", "oneshot", "--fresh")[0] == 0
    _wait(proj, tid)
    second = calls.read_text(encoding="utf-8").splitlines()[1]
    assert "--session-id" in second and "--resume" not in second
    assert tickets.sessions_for(proj, tid, tickets.load(proj, tid), "claude", runs.host()) != old


def test_failed_resume_falls_back_to_fresh_once_and_records_the_new_id(
    proj, run, tmp_path, monkeypatch, subprocess_home
):
    calls = _fake_claude(tmp_path, monkeypatch, resume_works=False)
    config.set_key(proj, "workspace", "agent", "claude")
    config.set_permissions(proj, "ask")  # no `claude --help` probe in the fake's call log
    tid = _ticket_with_check(proj, run)
    old = "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"
    tickets.record_session(proj, tid, "claude", old, runs.host())
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    _wait(proj, tid)
    lines = calls.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and "--resume" in lines[0] and "--session-id" in lines[1]
    new = tickets.sessions_for(proj, tid, tickets.load(proj, tid), "claude", runs.host())
    assert new and new != old and new in lines[1]


def test_allow_is_ignored_with_one_notice_by_an_adapter_that_cannot_use_it(proj, run, gen):
    log = gen()
    tid = _ticket_with_check(proj, run)
    code, out, err = run("run", "start", tid, "--mode", "oneshot", "--allow", "Bash(rm:*)", "--json")
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
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    _wait(proj, tid)
    assert (
        tickets.sessions_for(proj, tid, tickets.load(proj, tid), "codex", runs.host())
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


def test_a_plain_failure_does_not_fall_back_to_fresh(proj, run, tmp_path, monkeypatch):
    d = tmp_path / "clbin"
    d.mkdir()
    out = tmp_path / "calls.txt"
    f = d / "claude"
    f.write_text(
        '#!/bin/sh\n[ "$1" = --version ] && exit 0\n'
        f"echo x >> {shlex.quote(str(out))}\necho 'rate limit reached'\nexit 1\n"
    )
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    config.set_key(proj, "workspace", "agent", "claude")
    config.set_permissions(proj, "ask")  # no `claude --help` probe in the fake's call log
    tid = _ticket_with_check(proj, run)
    old = "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"
    tickets.record_session(proj, tid, "claude", old, runs.host())
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    _wait(proj, tid)
    assert len(out.read_text().splitlines()) == 1  # one try, no second run
    assert tickets.sessions_for(proj, tid, tickets.load(proj, tid), "claude", runs.host()) == old


def test_the_fresh_fallback_carries_the_pending_input(proj, run, tmp_path, monkeypatch, subprocess_home):
    calls = _fake_claude(tmp_path, monkeypatch, resume_works=False)
    config.set_key(proj, "workspace", "agent", "claude")
    config.set_permissions(proj, "ask")  # no `claude --help` probe in the fake's call log
    tid = _ticket_with_check(proj, run)
    tickets.record_session(proj, tid, "claude", "f88ec2ca-0930-42dd-9d5e-00fbbd59067d", runs.host())
    runs.pending_add(proj, tid, "phone", "message", "Also add October")
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    _wait(proj, tid)
    lines = calls.read_text(encoding="utf-8").splitlines()
    assert "Also add October" in lines[0] and "Also add October" in lines[1]
    assert runs.undelivered(proj, tid) == []


def test_wrap_needs_the_exact_prompt_file_of_a_live_claim(proj, run, gen):
    gen()
    tid = _ticket_with_check(proj, run)
    rec = runs.claim(proj, tid, "x", "fake")
    other = proj / ".orch" / "run" / "other.txt"
    other.write_text("keep")
    code, _, err = run("run", "_wrap", rec["run"], "--ticket", tid, "--agent", "fake",
                       "--stdin-file", str(other), "--", "true")  # fmt: skip
    assert code == 2 and other.exists()
    code, _, _ = run("run", "_wrap", "r_nosuchrun", "--ticket", tid, "--agent", "fake", "--", "true")
    assert code == 2 and runs.read(proj, tid)["run"] == rec["run"]


def test_prompt_file_is_private_from_the_start(proj):
    p = proj / ".orch" / "run" / "x.txt"
    runs._atomic(p, "secret", 0o600)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_a_failed_step_says_why_in_the_ticket_history(proj, run, tmp_path, monkeypatch):
    """`claude -p` not logged in prints an error result and stops: the person sees why nothing happened."""
    d = tmp_path / "clbin"
    d.mkdir()
    f = d / "claude"
    err = {"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}
    f.write_text(f"#!/bin/sh\necho '{json.dumps(err)}'\nexit 1\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    config.set_key(proj, "workspace", "agent", "claude")
    config.set_permissions(proj, "ask")  # no `claude --help` probe in the fake's call log
    tid = _ticket_with_check(proj, run)
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    _wait(proj, tid)
    last = tickets.load(proj, tid)["history"][-1]
    assert last["text"] == "The agent stopped with an error: Not logged in · Please run /login"
    assert last["by"] == "agent:claude"
    assert tickets.load(proj, tid)["status"] == "waiting"  # never left Working


def test_failure_text_reads_the_tool_error_or_the_last_line():
    ok = '{"type": "result", "is_error": false, "result": "done"}'
    assert runs.failure_text(0, ok) is None and runs.failure_text(0, "all fine\n") is None
    assert runs.failure_text(1, "starting\nrate limit reached\n") == "rate limit reached"
    assert (
        runs.failure_text(0, '{"type": "result", "is_error": true, "result": "Not logged in"}')
        == "Not logged in"
    )
    assert runs.failure_text(2, '{"type": "system"}\n' + ok) == "exit code 2"
    assert runs.failure_text(3, "") == "exit code 3"


def test_a_continued_conversation_counts_as_used_now(proj, run, tmp_path, monkeypatch):
    _fake_claude(tmp_path, monkeypatch, resume_works=True)
    config.set_key(proj, "workspace", "agent", "claude")
    config.set_permissions(proj, "ask")  # no `claude --help` probe in the fake's call log
    tid = _ticket_with_check(proj, run)
    old = "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"
    tickets.record_session(proj, tid, "claude", old, runs.host())

    def stamp(t):
        t["sessions"][0]["last_used"] = "2026-01-01T00:00:00Z"

    tickets.apply_op(proj, tid, stamp)
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    _wait(proj, tid)
    s = tickets.load(proj, tid)["sessions"][0]
    assert s["id"] == old and s["last_used"] > "2026-01-01T00:00:00Z"


def test_a_stop_we_asked_for_is_not_logged_as_an_error(proj, run, tmp_path, monkeypatch):
    """Windows has no SIGTERM handler: a non-zero end after `orch run stop` is a normal end."""
    d = tmp_path / "clbin"
    d.mkdir()
    f = d / "claude"
    f.write_text("#!/bin/sh\nsleep 2\nexit 1\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    config.set_key(proj, "workspace", "agent", "claude")
    config.set_permissions(proj, "ask")  # no `claude --help` probe in the fake's call log
    tid = _ticket_with_check(proj, run)
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    deadline = time.time() + 10
    while time.time() < deadline and not (runs.read(proj, tid) or {}).get("agent_pid"):
        time.sleep(0.05)
    with runs.locked(proj, tid):
        rec = runs.read(proj, tid)
        rec["stop_requested"] = tickets.now()
        runs._write(proj, rec)
    _wait(proj, tid)
    assert not any("stopped with an error" in h["text"] for h in tickets.load(proj, tid)["history"])


def test_run_messages_name_the_ticket_by_its_key(proj, run):
    tid = _ticket_with_check(proj, run)
    key = tickets.load(proj, tid)["key"]
    assert key and run("run", "stop", tid)[1].strip() == f"Nothing is running on {key}."
    assert f"Claimed {key} " in run("run", "claim", tid, "--by", "agent:t")[1]


@pytest.mark.parametrize(
    "code, said", [(0, "The live session ended."), (3, "The live session ended with an error (exit code 3).")]
)
def test_a_live_session_that_ends_says_so_in_the_history(proj, run, code, said):
    """The live agent quit (or never got past its own first-run screens): the ticket says so."""
    tid = _ticket_with_check(proj, run)
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    assert (
        runs.wrap_live(
            proj, rec["run"], tid, "claude", [sys.executable, "-c", f"raise SystemExit({code})"], None
        )
        == code
    )
    last = tickets.load(proj, tid)["history"][-1]
    assert (last["text"], last["by"]) == (said, "agent:claude")
    assert runs.read(proj, tid) is None


def test_a_live_session_we_stopped_adds_no_end_line(proj, run):
    tid = _ticket_with_check(proj, run)
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    with runs.locked(proj, tid):
        r = runs.read(proj, tid)
        r["stop_requested"] = tickets.now()
        runs._write(proj, r)
    runs.wrap_live(proj, rec["run"], tid, "claude", [sys.executable, "-c", "raise SystemExit(1)"], None)
    assert not any("live session ended" in h["text"] for h in tickets.load(proj, tid)["history"])


def test_the_holder_line_says_the_start_in_local_time():
    from orch import cli_run, net

    rec = {"agent": "claude", "by": "human:t", "started_at": "2026-11-06T13:57:13Z"}
    assert cli_run._holder_line(rec, "t_abc123").endswith(f"since {net.when('2026-11-06T13:57:13Z')}.")


@pytest.mark.parametrize("sid", ["bad:id", "bad.id"])
@pytest.mark.parametrize("parsed", [False, True])
def test_invalid_output_session_does_not_end_run(proj, run, monkeypatch, sid, parsed):
    from orch import adapters

    tid = _ticket_with_check(proj, run)
    rec = runs.claim(proj, tid, "x", "codex")
    monkeypatch.setattr(runs, "_on_term", lambda *a: None)
    monkeypatch.setattr(runs, "_run_turn", lambda *a: (0, json.dumps({"thread_id": sid})))
    if parsed:  # defend the recording boundary even if an adapter returns an invalid ID
        monkeypatch.setattr(adapters, "parse_session", lambda *a: sid)
    assert runs.wrap(proj, rec["run"], tid, "codex", ["codex"]) == 0
    assert runs.read(proj, tid) is None
    ticket = tickets.load(proj, tid)
    assert not ticket.get("sessions")
    if parsed:
        assert "Skipped recording an invalid agent session id." in json.dumps(ticket)
