"""Windows: a run folder made by an elevated process stays usable for the same user without elevation (#168)."""

import subprocess

import pytest

from orch_dashboard import runfiles

SID = "S-1-5-21-111-222-333-1001"


@pytest.fixture
def win(monkeypatch):
    calls = []
    monkeypatch.setattr(runfiles, "WINDOWS", True)
    monkeypatch.setattr(runfiles, "user_sid", lambda: SID)
    monkeypatch.setattr(runfiles.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    return calls


def test_new_folders_grant_the_current_user_only(tmp_path, win):
    (tmp_path / ".orch").mkdir()
    d = runfiles.run_dir(tmp_path, "x")
    assert d.is_dir()
    assert [c[2:] for c in win] == [["/grant", f"*{SID}:(OI)(CI)F"]] * 2  # .orch/run and .orch/run/x
    assert [c[1] for c in win] == [str(tmp_path / ".orch" / "run"), str(d)]
    assert all(c[0].lower().endswith("icacls.exe") and "system32" in c[0].lower() for c in win)
    assert not any("Everyone" in " ".join(c) or "Users" in " ".join(c) for c in win)


def test_existing_folders_are_not_touched(tmp_path, win):
    (tmp_path / ".orch" / "run" / "x").mkdir(parents=True)
    runfiles.run_dir(tmp_path, "x")
    assert win == []


def test_posix_never_calls_icacls(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runfiles, "WINDOWS", False)
    monkeypatch.setattr(runfiles.subprocess, "run", lambda *a, **k: calls.append(a))
    (tmp_path / ".orch").mkdir()
    runfiles.run_dir(tmp_path, "x")
    assert calls == []


def test_icacls_failure_does_not_break(tmp_path, monkeypatch, win):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(runfiles.subprocess, "run", boom)
    (tmp_path / ".orch").mkdir()
    assert runfiles.run_dir(tmp_path, "x").is_dir()


def test_admin_made_folder_gives_a_plain_message(tmp_path, monkeypatch):
    monkeypatch.setattr(runfiles, "WINDOWS", True)
    d = tmp_path / ".orch" / "run" / "x"
    d.mkdir(parents=True)

    def deny(*a, **k):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(runfiles.tempfile, "mkstemp", deny)
    monkeypatch.setattr(runfiles.os, "open", deny)
    for call in (
        lambda: runfiles.write_json(d / "server.json", {}),
        lambda: runfiles.open_append(d / "server.log"),
    ):
        with pytest.raises(RuntimeError) as e:
            call()
        msg = str(e.value)
        assert "made by orch running as administrator" in msg and ".orch\\run\\x" in msg
        assert "PermissionError" not in msg


def test_admin_made_folder_is_reported_when_it_is_opened(tmp_path, monkeypatch):
    monkeypatch.setattr(runfiles, "WINDOWS", True)
    monkeypatch.setattr(runfiles, "grant_user", lambda d: None)
    (tmp_path / ".orch" / "run" / "x").mkdir(parents=True)

    def deny(*a, **k):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(runfiles.os, "scandir", deny)
    with pytest.raises(RuntimeError, match=r"made by orch running as administrator.*\.orch\\run\\x"):
        runfiles.run_dir(tmp_path, "x")
