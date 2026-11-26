"""The watcher's runtime files in .orch/run/factory/ and how a running watcher is found again (R1.6, R8.4)."""

import os
import subprocess
import sys

import pytest

from orch_factory import runfiles, service

FOLDER = "Mein Ordner ü"


@pytest.fixture
def odd_ws(ws, tmp_path, monkeypatch):
    """A workspace in a folder with a space and an umlaut, run without any locale (launchd, `env -i`, a service)."""
    root = tmp_path / FOLDER / "Kunden Ä"
    (root / ".orch").mkdir(parents=True)
    monkeypatch.setenv("ORCH_ROOT", str(root))
    for name in ("LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES"):
        monkeypatch.delenv(name, raising=False)
    return root


def test_watcher_in_a_folder_with_spaces_and_umlauts_is_found_again(odd_ws):
    pid = service.start(odd_ws)
    try:
        assert service.running_pid(odd_ws) == pid
        assert service.running_pid(odd_ws, clean=False) == pid
    finally:
        assert service.stop(odd_ws) == "stopped"
    assert service.running_pid(odd_ws, clean=False) is None


def test_command_line_keeps_umlauts_without_a_locale(odd_ws):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "--dir", str(odd_ws)])
    try:
        assert runfiles.command(child.pid).endswith(f" --dir {odd_ws}")
    finally:
        child.kill()
        child.wait()


def test_runs_args_matches_whole_folder_names_with_spaces():
    cmd = f"python -P -m orch_factory --dir /x/{FOLDER} watch"
    assert runfiles.runs_args(cmd, ["-m", "orch_factory", "--dir", f"/x/{FOLDER}", "watch"])
    assert not runfiles.runs_args(cmd, ["-m", "orch_factory", "--dir", "/x/Mein", "watch"])
    longer = f"python -P -m orch_factory --dir /x/{FOLDER} 2 watch"
    assert not runfiles.runs_args(longer, ["-m", "orch_factory", "--dir", f"/x/{FOLDER}", "watch"])


def test_windows_grant_passes_a_folder_with_spaces_as_one_argument(odd_ws, monkeypatch):
    calls = []
    monkeypatch.setattr(runfiles, "WINDOWS", True)
    monkeypatch.setattr(runfiles, "user_sid", lambda: "S-1-5-21-1-2-3-1001")
    monkeypatch.setattr(runfiles, "_run", lambda cmd, **kw: calls.append(cmd))
    d = runfiles.run_dir(odd_ws, "factory")
    assert [c[1] for c in calls] == [str(odd_ws / ".orch" / "run"), str(d)]
    assert all(FOLDER in c[1] for c in calls)


def test_read_json_returns_nothing_for_anything_but_a_json_object(tmp_path):
    p = tmp_path / "rec.json"
    assert runfiles.read_json(p) is None  # missing
    for raw in (b"", b"[1, 2]", b"{not json", b"\xff\xfe"):
        p.write_bytes(raw)
        assert runfiles.read_json(p) is None, raw
    p.write_text('{"pid": 42}')
    assert runfiles.read_json(p) == {"pid": 42}
    link = tmp_path / "link.json"
    link.symlink_to(p)
    assert runfiles.read_json(link) is None
    assert runfiles.read_json(tmp_path) is None  # a folder


def test_write_json_replaces_a_link_and_never_writes_through_it(tmp_path):
    target = tmp_path / "elsewhere.json"
    target.write_text("keep")
    p = tmp_path / "factory.json"
    p.symlink_to(target)
    runfiles.write_json(p, {"pid": 7})
    assert target.read_text() == "keep"
    assert not p.is_symlink() and runfiles.read_json(p) == {"pid": 7}
    assert [x.name for x in tmp_path.iterdir() if x.name.startswith(".tmp-")] == []


def test_open_append_refuses_a_link(tmp_path):
    target = tmp_path / "elsewhere.log"
    target.write_text("keep")
    (tmp_path / "factory.log").symlink_to(target)
    with pytest.raises(RuntimeError, match="symbolic link"):
        runfiles.open_append(tmp_path / "factory.log")
    assert target.read_text() == "keep"


def test_write_in_a_read_only_folder_says_what_is_wrong(tmp_path):
    d = tmp_path / "ro"
    d.mkdir()
    d.chmod(0o500)
    try:
        if os.access(d, os.W_OK):
            pytest.skip("running as a user that can write anywhere")
        with pytest.raises(RuntimeError, match="not writable"):
            runfiles.write_json(d / "factory.json", {})
        with pytest.raises(RuntimeError, match="not writable"):
            runfiles.open_append(d / "factory.log")
    finally:
        d.chmod(0o700)


def test_pids_from_a_file_are_checked_before_use():
    for bad in (None, True, 0, 1, -5, 2**31, "123", 12.0):
        assert not runfiles.valid_pid(bad), bad
        assert not runfiles.alive(bad)
        assert runfiles.proc_start(bad) is None
    assert runfiles.alive(os.getpid()) and runfiles.proc_start(os.getpid())


def test_ps_that_fails_gives_no_identity(monkeypatch):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 5)

    monkeypatch.setattr(runfiles, "_run", boom)
    assert runfiles.proc_start(os.getpid()) is None
    assert runfiles.command(os.getpid()) == ""


def test_run_dir_refuses_a_linked_or_wrong_run_folder(ws, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / ".orch" / "run").symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symbolic link"):
        runfiles.run_dir(ws, "factory")
    assert service.running_pid(ws) is None  # the view never crashes on it
    with pytest.raises(RuntimeError, match="symbolic link"):  # refused with what to do, nothing signalled
        service.stop(ws)
    assert list(outside.iterdir()) == []
    (ws / ".orch" / "run").unlink()
    (ws / ".orch" / "run").mkdir()
    (ws / ".orch" / "run" / "factory").write_text("a file, not a folder")
    with pytest.raises(RuntimeError, match="not a folder"):
        runfiles.run_dir(ws, "factory")


def test_private_folders_only_inside_the_workspaces_orch_folder(odd_ws, tmp_path):
    assert runfiles.in_orch_area(odd_ws / ".orch" / "run" / "factory")  # found from the path itself
    assert not runfiles.in_orch_area(tmp_path / "no-orch-here")
    with pytest.raises(RuntimeError, match="will not change its rights"):
        runfiles.mkdir_private(odd_ws / "loose", odd_ws)
    assert not (odd_ws / "loose").exists()


def test_status_and_stop_with_nothing_recorded(ws):
    assert service.running_pid(ws) is None
    assert service.page_url(ws) is None
    assert service.stop(ws) == "not running"
    service.forget(ws, None)  # nothing to forget, nothing raised


def test_announce_needs_the_nonce_from_start(ws, monkeypatch):
    monkeypatch.delenv(service.NONCE_ENV, raising=False)
    assert service.announce(ws) is None
    monkeypatch.setenv(service.NONCE_ENV, "not-a-nonce")
    assert service.announce(ws) is None
    assert not (ws / ".orch" / "run" / "factory" / "factory.json").exists()


def test_forget_leaves_another_watchers_record(ws):
    d = runfiles.run_dir(ws, "factory")
    rec = {"pid": os.getpid() + 1, "nonce": "d" * 32, "started": "x"}
    runfiles.write_json(d / "factory.json", rec)
    service.forget(ws, "d" * 32)  # same nonce, other pid: not ours
    service.forget(ws, "e" * 32)
    assert runfiles.read_json(d / "factory.json") == rec


def test_start_lock_refuses_something_that_is_not_a_file(ws):
    d = runfiles.run_dir(ws, "factory")
    os.mkfifo(d / "start.lock")
    with pytest.raises(RuntimeError, match="not a regular file"):
        service.start(ws, wait=0.3)


def test_a_watcher_that_dies_at_once_is_reported_with_the_log(ws, tmp_path, monkeypatch):
    dead = tmp_path / "dead-python"
    dead.write_text("#!/bin/sh\necho 'boom' >&2\nexit 3\n")
    dead.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(dead))
    with pytest.raises(RuntimeError, match=r"did not start\. See \.orch/run/factory/factory\.log"):
        service.start(ws, wait=0.3)
    assert "boom" in (ws / ".orch" / "run" / "factory" / "factory.log").read_text()
    assert service.running_pid(ws, clean=False) is None
