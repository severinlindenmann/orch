"""Runtime files in .orch/run/<name>/ on POSIX: a workspace folder with spaces and umlauts, links refused, broken
or hostile files read as "nothing there", and the process checks failing safe."""

import os
import subprocess
import threading

import pytest

from orch_dashboard import runfiles


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(runfiles, "WINDOWS", False)
    r = tmp_path / "Mein Büro" / "Kunde Zürich"
    (r / ".orch").mkdir(parents=True)
    return r


def test_run_dir_in_a_folder_with_spaces_and_umlauts_is_private(root):
    d = runfiles.run_dir(root, "dashboard")
    assert d == root / ".orch" / "run" / "dashboard" and d.is_dir()
    assert oct(d.stat().st_mode & 0o777) == oct(0o700)
    assert runfiles.run_dir(root, "dashboard") == d  # a second run uses the same folder
    assert runfiles.in_orch_area(d) and runfiles.in_orch_area(d, root)
    assert not runfiles.in_orch_area(root) and not runfiles.in_orch_area(root / "elsewhere")


def test_run_dir_refuses_links_and_files(root, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (root / ".orch" / "run").symlink_to(other)
    with pytest.raises(RuntimeError, match="symbolic link"):
        runfiles.run_dir(root, "dashboard")
    (root / ".orch" / "run").unlink()
    (root / ".orch" / "run").mkdir()
    (root / ".orch" / "run" / "dashboard").write_text("")
    with pytest.raises(RuntimeError, match="is not a folder"):
        runfiles.run_dir(root, "dashboard")


def test_json_round_trip_with_umlauts(root):
    d = runfiles.run_dir(root, "dashboard")
    runfiles.write_json(d / "server.json", {"dir": str(root), "pid": 4242})
    assert runfiles.read_json(d / "server.json") == {"dir": str(root), "pid": 4242}
    assert [p.name for p in d.iterdir()] == ["server.json"]  # no temp file left


def test_a_failed_write_keeps_the_old_file_and_leaves_no_temp_file(root):
    d = runfiles.run_dir(root, "dashboard")
    runfiles.write_json(d / "server.json", {"pid": 1234})
    with pytest.raises(TypeError):
        runfiles.write_json(d / "server.json", {"pid": object()})
    assert runfiles.read_json(d / "server.json") == {"pid": 1234}
    assert [p.name for p in d.iterdir()] == ["server.json"]


def test_write_replaces_a_link_and_never_writes_through_it(root, tmp_path):
    d = runfiles.run_dir(root, "dashboard")
    target = tmp_path / "victim.json"
    target.write_text("keep")
    (d / "server.json").symlink_to(target)
    assert runfiles.read_json(d / "server.json") is None
    runfiles.write_json(d / "server.json", {"pid": 7})
    assert target.read_text() == "keep"
    assert not (d / "server.json").is_symlink() and runfiles.read_json(d / "server.json") == {"pid": 7}


@pytest.mark.parametrize("content", [b"", b"{not json", b"[1, 2]", b'"text"', b"\xff\xfe"])
def test_broken_files_read_as_nothing(root, content):
    p = runfiles.run_dir(root, "dashboard") / "server.json"
    p.write_bytes(content)
    assert runfiles.read_json(p) is None


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX only")
def test_missing_files_folders_and_fifos_read_as_nothing_without_hanging(root):
    d = runfiles.run_dir(root, "dashboard")
    assert runfiles.read_json(d / "gone.json") is None
    (d / "dir.json").mkdir()
    assert runfiles.read_json(d / "dir.json") is None
    os.mkfifo(d / "pipe.json")
    got = []
    t = threading.Thread(target=lambda: got.append(runfiles.read_json(d / "pipe.json")), daemon=True)
    t.start()
    t.join(5)
    hung = t.is_alive()
    if hung:  # unblock the hung reader so the run goes on, then fail
        os.close(os.open(d / "pipe.json", os.O_WRONLY | os.O_NONBLOCK))
        t.join(5)
    assert not hung and got == [None]


def test_append_refuses_a_link_and_remove_never_follows_one(root, tmp_path):
    d = runfiles.run_dir(root, "dashboard")
    target = tmp_path / "victim.log"
    target.write_text("keep")
    (d / "server.log").symlink_to(target)
    with pytest.raises(RuntimeError, match="symbolic link"):
        runfiles.open_append(d / "server.log")
    runfiles.remove(d / "server.log")
    runfiles.remove(d / "never-there.log")
    assert target.read_text() == "keep" and not (d / "server.log").exists()
    with runfiles.open_append(d / "server.log") as f:
        f.write("Grüße\n")
    assert (d / "server.log").read_text(encoding="utf-8") == "Grüße\n"


def test_posix_write_errors_name_the_folder(root, monkeypatch):
    d = runfiles.run_dir(root, "dashboard")

    def deny(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(runfiles.tempfile, "mkstemp", deny)
    with pytest.raises(RuntimeError, match="is not writable"):
        runfiles.write_json(d / "server.json", {})


@pytest.mark.parametrize("pid", [None, "123", 1.0, True, 0, 1, -5, 2**31])
def test_a_pid_from_a_file_counts_only_when_it_is_a_real_pid(pid):
    assert not runfiles.valid_pid(pid)
    assert runfiles.alive(pid) is False
    assert runfiles.proc_start(pid) is None


def test_this_process_is_alive_and_has_a_start_and_command():
    assert runfiles.alive(os.getpid())
    assert runfiles.proc_start(os.getpid())
    assert "python" in runfiles.command(os.getpid()).lower()


@pytest.mark.parametrize("err", [OSError("no ps"), subprocess.TimeoutExpired("ps", 5)])
def test_a_failing_ps_means_unknown_never_a_crash(monkeypatch, err):
    def boom(*a, **k):
        raise err

    monkeypatch.setattr(runfiles, "_run", boom)
    assert runfiles.proc_start(os.getpid()) is None
    assert runfiles.command(os.getpid()) == ""


def test_runs_args_matches_whole_arguments_only():
    ws = "/Users/jürg/Mein Büro"
    cmd = f"/usr/bin/python3 -m orch_dashboard --dir {ws} serve"
    assert runfiles.runs_args(cmd, ["-m", "orch_dashboard", "--dir", ws, "serve"])
    assert runfiles.runs_args(cmd + " --quiet", ["--dir", ws, "serve"])
    assert not runfiles.runs_args(cmd, ["--dir", "/Users/jürg/Mein", "serve"])
    assert not runfiles.runs_args(cmd.replace("Büro", "Büro2"), ["--dir", ws, "serve"])


def test_folder_rights_change_only_inside_the_orch_folder(root):
    with pytest.raises(RuntimeError, match="not inside the workspace's .orch folder"):
        runfiles.mkdir_private(root / "x")
    assert runfiles.mkdir_private(root / ".orch" / "neu", root) is True
    assert runfiles.mkdir_private(root / ".orch" / "neu", root) is False
    runfiles.check_orch_area(root / ".orch" / "neu")
