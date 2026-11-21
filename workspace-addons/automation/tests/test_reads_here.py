"""ORCH-634: a plain read of the scheduler (`ticket list --all`, `run status` ...) is answered by the core in this
process when ORCH_BIN is this very orch, never by one new process per read; anything else runs the command."""

import subprocess
import sys

import pytest

from orch_automation import orchcli

pytest.importorskip("orch.reads")


@pytest.fixture
def same_orch(tmp_path, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("same_orch reads a POSIX launcher")
    mine = tmp_path / "orch"
    mine.write_text(f"#!{sys.executable}\nfrom orch_entry import main\n")
    monkeypatch.setenv("ORCH_BIN", str(mine))
    return mine


def _no_process(*a, **k):
    raise AssertionError(f"a new process for a read: {a}")


def test_a_plain_read_starts_no_process(same_orch, tmp_path, monkeypatch):
    from orch import reads

    asked = []
    monkeypatch.setattr(reads, "answer", lambda root, argv: asked.append(argv) or [{"id": "t_abcdef"}])
    monkeypatch.setattr(orchcli, "_run", _no_process)
    assert orchcli.call(tmp_path, "ticket", "list", "--all", by=False) == [{"id": "t_abcdef"}]
    assert asked == [["ticket", "list", "--all", "--json"]]


def test_a_read_the_core_does_not_answer_here_runs_the_command(same_orch, tmp_path, monkeypatch):
    from orch import reads

    def not_here(root, argv):
        raise reads.NotHere(" ".join(argv))

    started = []
    monkeypatch.setattr(reads, "answer", not_here)
    monkeypatch.setattr(
        orchcli,
        "_run",
        lambda cmd, **k: started.append(cmd) or subprocess.CompletedProcess(cmd, 0, "[1]", ""),
    )
    assert orchcli.call(tmp_path, "relay", "inbox", "--since", "3", "--wait", "30", by=False) == [1]
    assert started and started[0][1:3] == ["relay", "inbox"]


def test_a_write_or_another_orch_is_never_answered_here(tmp_path, monkeypatch, same_orch):
    from orch import reads

    monkeypatch.setattr(reads, "answer", lambda *a: pytest.fail("a write answered from memory"))
    started = []
    monkeypatch.setattr(
        orchcli,
        "_run",
        lambda cmd, **k: started.append(cmd) or subprocess.CompletedProcess(cmd, 0, "{}", ""),
    )
    assert orchcli.call(tmp_path, "log", "t_abcdef", "x") == {}
    other = tmp_path / "fake"
    other.write_text(f"#!{sys.executable}\nprint('[]')\n")
    monkeypatch.setenv("ORCH_BIN", str(other))
    assert orchcli.call(tmp_path, "ticket", "list", "--all", by=False) == {}
    assert len(started) == 2


def test_a_bare_or_relative_orch_bin_is_found_as_the_command_finds_it(same_orch, tmp_path, monkeypatch):
    """ORCH_BIN=orch goes through PATH; a relative ORCH_BIN is read from the workspace (the command's cwd)."""
    same_orch.chmod(0o755)  # PATH finds only a runnable file
    monkeypatch.setenv("PATH", str(same_orch.parent))
    assert orchcli._launcher(tmp_path, "orch") == str(same_orch)
    ws = tmp_path / "ws"
    (ws / "bin").mkdir(parents=True)
    assert orchcli._launcher(ws, "bin/orch") == str(ws / "bin" / "orch")
