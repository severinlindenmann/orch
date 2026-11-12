"""Opus review of PR #292 (adversarial). Copy into workspace/tests/ and run:
uv run pytest -q tests/test_rev292_adversarial.py -p no:cacheprovider"""

import os
import shlex
import stat
import subprocess
import time
from pathlib import Path

import pytest
import test_run_wrap
import test_start_watchdog as W

from orch import adapters, runs, tickets

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX process tests")


@pytest.fixture(autouse=True)
def _child_home(request):
    """The detached wrapper is a child `orch`: it needs an ORCH_HOME it trusts (conftest subprocess_home)."""
    if "proj" in request.fixturenames:
        request.getfixturevalue("subprocess_home")


_wait = test_run_wrap._wait


def test_kill_tree_keeps_the_exit_status_of_our_child():
    """kill_tree must not reap: a reaped Popen reports returncode 0 (a killed agent looks like a success)."""
    p = subprocess.Popen(["sleep", "30"], start_new_session=True)
    time.sleep(0.1)
    runs.kill_tree(p.pid)
    assert p.wait(timeout=5) < 0


def _always_hangs(tmp_path, monkeypatch, ignore_term=True):
    d = tmp_path / "clbin"
    d.mkdir()
    calls = tmp_path / "claude-calls.txt"
    f = d / "claude"
    f.write_text(
        "#!/bin/sh\n"
        '[ "$1" = "--help" ] && { echo "choices: auto"; exit 0; }\n'
        '[ "$1" = "--version" ] && { echo "2.1.0 (Claude Code)"; exit 0; }\n'
        f"echo x >> {shlex.quote(str(calls))}\n"
        + ("trap '' TERM; " if ignore_term else "")
        + "sleep 30; exit 0\n"
    )
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ["PATH"])
    return calls


@pytest.mark.parametrize("ignore_term", [True, False])
def test_a_start_that_hangs_twice_is_reported_and_not_started_a_third_time(
    proj, run, tmp_path, monkeypatch, ignore_term
):
    calls = _always_hangs(tmp_path, monkeypatch, ignore_term)
    monkeypatch.setenv("ORCH_RUN_START_WATCHDOG_SECONDS", "1")
    tid = W._setup(proj, run)
    assert run("run", "start", tid, "--mode", "oneshot")[0] == 0
    _wait(proj, tid, timeout=30)
    assert len(calls.read_text().splitlines()) == 2  # one fresh retry, never a loop
    hist = [h["text"] for h in tickets.load(proj, tid)["history"]]
    assert any("error" in h or "got going" in h for h in hist), hist  # a person sees it did not work
    assert tickets.sessions_for(proj, tid, tickets.load(proj, tid), "claude", runs.host()) is None


@pytest.mark.parametrize("sid", ["../../etc/passwd", "a/b", "/abs", ".hidden", ""])
def test_transcript_check_refuses_odd_session_ids(proj, sid, tmp_path):
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path), "HOME": str(tmp_path)}
    # odd ids are refused outright (fresh start), never "can't tell, trust the id"
    assert adapters.transcript_exists("claude", sid, proj, env) is False


def test_transcript_check_stays_below_the_tool_folder(proj, tmp_path):
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg"), "HOME": str(tmp_path)}
    folder = "".join(c if c.isalnum() else "-" for c in str(proj.resolve()))
    d = tmp_path / "cfg" / "projects" / folder
    d.mkdir(parents=True)
    # an id with dots (or anything outside the shared session-id rule) is never resumed, file or not
    (d / "abc..def.jsonl").write_text("{}")
    assert adapters.transcript_exists("claude", "abc..def", proj, env) is False
    assert adapters.transcript_exists("claude", "abc-def", proj, env) is False
    (d / "abc-def.jsonl").write_text("{}")
    assert adapters.transcript_exists("claude", "abc-def", proj, env) is True
    assert Path(d / "abc-def.jsonl").resolve().is_relative_to((tmp_path / "cfg").resolve())


def test_env_pointing_elsewhere_only_switches_resume_off_or_trusts_the_id(proj, tmp_path):
    """CLAUDE_CONFIG_DIR under another's control: folder missing -> None (old behaviour, trust the id);
    folder present without file -> False (fresh start). Never more than resume vs fresh."""
    env = {"CLAUDE_CONFIG_DIR": str(tmp_path / "nowhere"), "HOME": str(tmp_path)}
    assert adapters.transcript_exists("claude", "s1", proj, env) is None
