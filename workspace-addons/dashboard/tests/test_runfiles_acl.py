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
    monkeypatch.setattr(runfiles, "_run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(runfiles, "system_icacls", lambda: "C:\\Windows\\System32\\icacls.exe")
    return calls


def test_new_folders_grant_the_current_user_only(tmp_path, win):
    (tmp_path / ".orch").mkdir()
    d = runfiles.run_dir(tmp_path, "x")
    assert d.is_dir()
    assert [c[2:] for c in win] == [["/grant", f"*{SID}:(OI)(CI)F", "/L"]] * 2  # .orch/run and .orch/run/x
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
    monkeypatch.setattr(runfiles, "_run", lambda *a, **k: calls.append(a))
    (tmp_path / ".orch").mkdir()
    runfiles.run_dir(tmp_path, "x")
    assert calls == []


def test_icacls_failure_does_not_break(tmp_path, monkeypatch, win):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(runfiles, "_run", boom)
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
    monkeypatch.setattr(runfiles, "grant_user", lambda d, root=None: None)
    (tmp_path / ".orch" / "run" / "x").mkdir(parents=True)

    def deny(*a, **k):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(runfiles.os, "scandir", deny)
    with pytest.raises(RuntimeError, match=r"made by orch running as administrator.*\.orch\\run\\x"):
        runfiles.run_dir(tmp_path, "x")


def test_icacls_comes_from_the_system_folder_not_the_environment(monkeypatch):
    monkeypatch.setattr(runfiles, "WINDOWS", True)
    monkeypatch.setenv("SystemRoot", "D:\\evil")
    assert "evil" not in runfiles.system_icacls()
    assert runfiles.system_icacls().lower().endswith("icacls.exe")


def test_a_link_swapped_in_after_mkdir_is_never_granted(tmp_path, win, monkeypatch):
    (tmp_path / ".orch").mkdir()
    real = runfiles.is_link
    monkeypatch.setattr(runfiles, "reparse", lambda p: p.name == "run")  # a junction at .orch/run
    with pytest.raises(RuntimeError, match="not a plain folder|symbolic link"):
        runfiles.run_dir(tmp_path, "x")
    assert win == []
    assert real(tmp_path / ".orch" / "run")


def test_junction_swapped_between_mkdir_and_grant_is_refused(tmp_path, win, monkeypatch):
    (tmp_path / ".orch" / "run").mkdir(parents=True)
    monkeypatch.setattr(runfiles, "reparse", lambda p: True)
    with pytest.raises(RuntimeError, match="not a plain folder"):
        runfiles.mkdir_private(tmp_path / ".orch" / "run" / "new")
    assert win == []


def test_an_existing_junction_is_refused(tmp_path, monkeypatch):
    (tmp_path / ".orch" / "run" / "x").mkdir(parents=True)
    monkeypatch.setattr(runfiles, "reparse", lambda p: p.name == "x")
    with pytest.raises(RuntimeError, match="symbolic link"):
        runfiles.run_dir(tmp_path, "x")


# ---- scope guard (I11b): rights change only inside the workspace's .orch folder


def test_never_outside_the_orch_folder(tmp_path, win, monkeypatch):
    shared = tmp_path / "Public" / "i11b"  # a shared helper folder, also the current folder
    shared.mkdir(parents=True)
    monkeypatch.chdir(shared)
    for target in (shared, shared / "new", tmp_path, tmp_path / "Public" / "new"):
        with pytest.raises(RuntimeError, match=r"\.orch folder"):
            runfiles.mkdir_private(target)
        with pytest.raises(RuntimeError, match=r"\.orch folder"):
            runfiles.grant_user(target)
    assert not (shared / "new").exists() and not (tmp_path / "Public" / "new").exists()
    assert win == []  # no icacls call at all


def test_junction_escape_from_orch_is_refused(tmp_path, win):
    outside = tmp_path / "Public" / "i11b"
    outside.mkdir(parents=True)
    (tmp_path / ".orch").mkdir()
    (tmp_path / ".orch" / "esc").symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match=r"\.orch folder"):
        runfiles.mkdir_private(tmp_path / ".orch" / "esc" / "new")  # real path is outside .orch
    with pytest.raises(RuntimeError, match=r"\.orch folder"):
        runfiles.grant_user(tmp_path / ".orch" / "esc")
    assert win == [] and not (outside / "new").exists()


def test_run_dir_from_a_public_like_cwd_touches_only_orch(tmp_path, win, monkeypatch):
    ws = tmp_path / "Public" / "i11b"
    (ws / ".orch").mkdir(parents=True)
    monkeypatch.chdir(ws)  # orch start run from inside the shared folder (its root is the workspace)
    runfiles.run_dir(ws, "x")
    assert [c[1] for c in win] == [str(ws / ".orch" / "run"), str(ws / ".orch" / "run" / "x")]


def test_a_folder_that_is_only_named_orch_does_not_count(tmp_path):
    """The rule is anchored to THIS workspace: ws/.orch yes; another folder named .orch (a stray one, another
    workspace's) no, even when the caller passes the real workspace root."""
    ws = tmp_path / "ws"
    (ws / ".orch" / "run").mkdir(parents=True)
    stray = tmp_path / "elsewhere" / ".orch" / "run"
    stray.mkdir(parents=True)
    assert runfiles.in_orch_area(ws / ".orch" / "run" / "x", ws)
    assert runfiles.in_orch_area(ws / ".orch", ws)
    assert not runfiles.in_orch_area(stray, ws)
    assert not runfiles.in_orch_area(ws, ws)
    with pytest.raises(RuntimeError, match=r"\.orch folder"):
        runfiles.mkdir_private(stray / "new", ws)
    assert not (stray / "new").exists()
