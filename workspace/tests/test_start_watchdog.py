"""A start that shows no sign of life is stopped and started fresh; a session the tool never saved is never
resumed (testnet 8 Nov: a first start hung 10 min under launchd, then `--resume` of it failed)."""

import json
import os
import re
import shlex
import stat

import pytest
import test_run_wrap

from orch import config, runs, tickets

pytestmark = pytest.mark.skipif(os.name == "nt", reason="detached wrapper tests use shell stubs")


@pytest.fixture(autouse=True)
def _child_home(request):
    """The detached wrapper is a child `orch`: it needs an ORCH_HOME it trusts (conftest subprocess_home)."""
    if "proj" in request.fixturenames:
        request.getfixturevalue("subprocess_home")


_wait = test_run_wrap._wait


def _stub(tmp_path, monkeypatch, hang_first: bool):
    """A stand-in `claude` on PATH (never the real one): logs its arguments; with hang_first, its first call
    prints nothing, ignores SIGTERM and sleeps; every other call prints one stream line and ends."""
    d = tmp_path / "clbin"
    d.mkdir()
    calls = tmp_path / "claude-calls.txt"
    first = tmp_path / "first-done"
    f = d / "claude"
    f.write_text(
        "#!/bin/sh\n"
        '[ "$1" = "--help" ] && { echo "choices: auto"; exit 0; }\n'
        f'echo "$*" | tr "\\n" " " >> {shlex.quote(str(calls))}; echo >> {shlex.quote(str(calls))}\n'
        + (
            f"if [ ! -f {shlex.quote(str(first))} ]; then : > {shlex.quote(str(first))}; "
            "trap '' TERM; sleep 30; exit 0; fi\n"
            if hang_first
            else ""
        )
        + 'echo \'{"type":"result","is_error":false,"result":"ok"}\'\n'
        "exit 0\n"
    )
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    return calls


def _setup(proj, run):
    config.set_key(proj, "workspace", "agent", "claude")
    config.set_permissions(proj, "ask")  # no `claude --help` probe in the call log
    return json.loads(run("ticket", "new", "Plan the dinner", "--json", "--by", "human:t")[1])["id"]


def _session_dir(proj):
    base = os.environ["CLAUDE_CONFIG_DIR"]  # the test's own folder (conftest), never the real ~/.claude
    folder = re.sub(r"[^A-Za-z0-9]", "-", str(proj.resolve()))
    d = os.path.join(base, "projects", folder)
    os.makedirs(d, exist_ok=True)
    return d


def test_a_start_with_no_sign_of_life_is_stopped_and_started_fresh(proj, run, tmp_path, monkeypatch):
    calls = _stub(tmp_path, monkeypatch, hang_first=True)
    monkeypatch.setenv("ORCH_RUN_START_WATCHDOG_SECONDS", "1")
    tid = _setup(proj, run)
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    _wait(proj, tid, timeout=20)
    lines = calls.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and all("--session-id" in ln and "--resume" not in ln for ln in lines)
    ids = [re.search(r"--session-id (\S+)", ln).group(1) for ln in lines]
    assert ids[0] != ids[1]
    # the hung one is never kept; the one that worked is
    assert tickets.sessions_for(tickets.load(proj, tid), "claude", runs.host()) == ids[1]
    assert any("no sign of life" in h["text"] for h in tickets.load(proj, tid)["history"])


def test_a_session_without_a_saved_conversation_is_never_resumed(proj, run, tmp_path, monkeypatch):
    calls = _stub(tmp_path, monkeypatch, hang_first=False)
    tid = _setup(proj, run)
    old = "f88ec2ca-0930-42dd-9d5e-00fbbd59067d"
    tickets.record_session(proj, tid, "claude", old, runs.host())
    d = _session_dir(proj)  # the tool knows this folder, but not that conversation
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    _wait(proj, tid)
    first = calls.read_text(encoding="utf-8").splitlines()[0]
    assert "--resume" not in first and "--session-id" in first
    # a session whose conversation is saved is resumed
    with open(os.path.join(d, f"{old}.jsonl"), "w") as f:
        f.write("{}\n")
    tickets.record_session(proj, tid, "claude", old, runs.host())
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    _wait(proj, tid)
    assert f"--resume {old}" in calls.read_text(encoding="utf-8").splitlines()[1]


def test_a_new_session_the_tool_did_not_save_is_not_kept(proj, run, tmp_path, monkeypatch):
    _stub(tmp_path, monkeypatch, hang_first=False)
    tid = _setup(proj, run)
    _session_dir(proj)  # folder there, the stub writes no conversation file
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    _wait(proj, tid)
    assert tickets.sessions_for(tickets.load(proj, tid), "claude", runs.host()) is None


def test_a_quiet_generic_agent_is_not_stopped(proj, run, monkeypatch, gen):
    """Only an agent that streams its steps is expected to talk at once; a generic one may work quietly."""
    gen("--silent 2")
    monkeypatch.setenv("ORCH_RUN_START_WATCHDOG_SECONDS", "0.5")
    tid = json.loads(run("ticket", "new", "Quiet", "--json", "--by", "human:t")[1])["id"]
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    _wait(proj, tid)
    assert not any("no sign of life" in h["text"] for h in tickets.load(proj, tid)["history"])


gen = test_run_wrap.gen


def test_input_of_a_start_that_hangs_twice_waits_for_the_next_start(proj, run, tmp_path, monkeypatch):
    """Review #292: when both tries hang, the person's text is not lost: it is undelivered again."""
    import test_rev292_adversarial as A

    A._always_hangs(tmp_path, monkeypatch, ignore_term=False)
    monkeypatch.setenv("ORCH_RUN_START_WATCHDOG_SECONDS", "1")
    tid = _setup(proj, run)
    runs.pending_add(proj, tid, "human:t", "message", "Also invite Anna")
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    _wait(proj, tid, timeout=30)
    assert [i["text"] for i in runs.undelivered(proj, tid)] == ["Also invite Anna"]
