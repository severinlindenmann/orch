"""Runtime files in .orch/run/insights: private folders, no links followed, plain messages on Windows."""

import json
import os
import subprocess
import sys

import pytest

from orch_insights import runfiles

SID = "S-1-5-21-111-222-333-1001"
POSIX = pytest.mark.skipif(os.name == "nt", reason="POSIX modes and symlinks")


@pytest.fixture
def spaced(tmp_path):
    root = tmp_path / "Mein Ördner" / "Projekt Ä Ö Ü"
    (root / ".orch").mkdir(parents=True)
    return root


@pytest.fixture
def win(monkeypatch):
    """Windows simulated: every icacls call is recorded, none runs."""
    calls = []
    monkeypatch.setattr(runfiles, "WINDOWS", True)
    monkeypatch.setattr(runfiles, "user_sid", lambda: SID)
    monkeypatch.setattr(runfiles, "_run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(runfiles, "system_icacls", lambda: "C:\\Windows\\System32\\icacls.exe")
    return calls


@POSIX
def test_run_dir_in_a_folder_with_spaces_and_umlauts_is_private(spaced):
    d = runfiles.run_dir(spaced, "insights")
    assert d == spaced / ".orch" / "run" / "insights" and d.is_dir()
    assert (d.stat().st_mode & 0o777) == 0o700 and ((d.parent.stat().st_mode) & 0o777) == 0o700
    assert runfiles.run_dir(spaced, "insights") == d  # a second call keeps the folder


@POSIX
@pytest.mark.parametrize("link", ["run", "insights"])
def test_run_dir_refuses_a_link_and_writes_nothing_through_it(spaced, tmp_path, link):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    run = spaced / ".orch" / "run"
    if link == "run":
        run.symlink_to(outside, target_is_directory=True)
    else:
        run.mkdir()
        (run / "insights").symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symbolic link"):
        runfiles.run_dir(spaced, "insights")
    assert list(outside.iterdir()) == []


def test_run_dir_refuses_a_file_where_the_folder_belongs(spaced):
    (spaced / ".orch" / "run").write_text("x")
    with pytest.raises(RuntimeError, match="is not a folder"):
        runfiles.run_dir(spaced, "insights")


def test_windows_grants_only_the_current_user_inside_orch(spaced, win):
    d = runfiles.run_dir(spaced, "insights")
    assert [c[1] for c in win] == [str(spaced / ".orch" / "run"), str(d)]
    assert all(c[2:] == ["/grant", f"*{SID}:(OI)(CI)F", "/L"] for c in win)
    win.clear()
    runfiles.run_dir(spaced, "insights")
    assert win == []  # existing folders are left as they are


def test_windows_icacls_failure_does_not_break_the_start(spaced, win, monkeypatch):
    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 20)

    monkeypatch.setattr(runfiles, "_run", slow)
    assert runfiles.run_dir(spaced, "insights").is_dir()


def test_no_sid_means_no_grant(spaced, win, monkeypatch):
    monkeypatch.setattr(runfiles, "user_sid", lambda: None)
    runfiles.run_dir(spaced, "insights")
    assert win == []


def test_rights_never_change_outside_the_orch_folder(tmp_path, win, monkeypatch):
    shared = tmp_path / "Öffentlich" / "geteilt"
    shared.mkdir(parents=True)
    monkeypatch.chdir(shared)
    for target in (shared, shared / "neu", tmp_path / ".orch-not" / "x"):
        with pytest.raises(RuntimeError, match=r"\.orch folder"):
            runfiles.mkdir_private(target)
        with pytest.raises(RuntimeError, match=r"\.orch folder"):
            runfiles.grant_user(target)
    assert not (shared / "neu").exists() and win == []


def test_another_workspaces_orch_is_not_inside_this_one(tmp_path):
    a, b = tmp_path / "a ws", tmp_path / "b ws"
    (a / ".orch").mkdir(parents=True)
    (b / ".orch").mkdir(parents=True)
    assert runfiles.in_orch_area(a / ".orch" / "run", a)
    assert not runfiles.in_orch_area(b / ".orch" / "run", a)
    assert not runfiles.in_orch_area(tmp_path / "no orch here")


def test_windows_denied_folder_says_what_to_do(spaced, monkeypatch):
    monkeypatch.setattr(runfiles, "WINDOWS", True)
    monkeypatch.setattr(runfiles, "grant_user", lambda d, root=None: None)
    (spaced / ".orch" / "run" / "insights").mkdir(parents=True)

    def deny(*a, **k):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(runfiles.os, "scandir", deny)
    with pytest.raises(RuntimeError, match=r"administrator window.*\.orch\\run\\insights"):
        runfiles.run_dir(spaced, "insights")


def test_posix_denied_write_names_the_folder(spaced, monkeypatch):
    monkeypatch.setattr(runfiles, "WINDOWS", False)
    d = runfiles.run_dir(spaced, "insights")

    def deny(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(runfiles.tempfile, "mkstemp", deny)
    with pytest.raises(RuntimeError, match="is not writable"):
        runfiles.write_json(d / "server.json", {})


@POSIX
def test_read_json_takes_only_a_plain_file_with_an_object(spaced, tmp_path):
    d = runfiles.run_dir(spaced, "insights")
    assert runfiles.read_json(d / "missing.json") is None
    (d / "list.json").write_text("[1]")
    (d / "empty.json").write_text("")
    (d / "broken.json").write_text("{nope")
    (d / "folder.json").mkdir()
    secret = tmp_path / "secret.json"
    secret.write_text('{"pid": 4242}')
    (d / "link.json").symlink_to(secret)
    for name in ("list", "empty", "broken", "folder", "link"):
        assert runfiles.read_json(d / f"{name}.json") is None, name
    runfiles.write_json(d / "ok.json", {"pid": 4242, "Ort": "Zürich"})
    assert runfiles.read_json(d / "ok.json") == {"pid": 4242, "Ort": "Zürich"}
    assert not list(d.glob(".tmp-*"))


@POSIX
def test_write_json_replaces_a_link_and_never_writes_its_target(spaced, tmp_path):
    d = runfiles.run_dir(spaced, "insights")
    target = tmp_path / "victim.json"
    target.write_text("keep")
    (d / "server.json").symlink_to(target)
    runfiles.write_json(d / "server.json", {"pid": 4242})
    assert target.read_text() == "keep"
    assert not (d / "server.json").is_symlink() and json.loads((d / "server.json").read_text()) == {
        "pid": 4242
    }


@POSIX
def test_log_appends_and_refuses_a_link(spaced, tmp_path):
    d = runfiles.run_dir(spaced, "insights")
    for line in ("eins\n", "zwei\n"):
        with runfiles.open_append(d / "server.log") as f:
            f.write(line)
    assert (d / "server.log").read_text(encoding="utf-8") == "eins\nzwei\n"
    target = tmp_path / "victim.log"
    target.write_text("keep")
    (d / "other.log").symlink_to(target)
    with pytest.raises(RuntimeError, match="symbolic link"):
        runfiles.open_append(d / "other.log")
    runfiles.remove(d / "other.log")
    runfiles.remove(d / "never-there.json")  # a missing file is fine
    assert target.read_text() == "keep" and not (d / "other.log").exists()


@pytest.mark.parametrize("pid", [None, "42", True, False, 0, 1, -5, 2**31, 4.2])
def test_odd_pids_are_never_alive_or_asked_about(pid, monkeypatch):
    monkeypatch.setattr(runfiles, "_run", lambda *a, **k: pytest.fail("no ps for an odd pid"))
    assert not runfiles.valid_pid(pid) and not runfiles.alive(pid) and runfiles.proc_start(pid) is None


def test_a_finished_process_is_not_alive():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert runfiles.alive(os.getpid()) and not runfiles.alive(p.pid)


@pytest.mark.skipif(os.name == "nt", reason="ps is POSIX only")
@pytest.mark.parametrize("error", [OSError("no ps"), subprocess.TimeoutExpired("ps", 5)])
def test_ps_failure_means_unknown(monkeypatch, error):
    def boom(*a, **k):
        raise error

    monkeypatch.setattr(runfiles, "_run", boom)
    assert runfiles.proc_start(os.getpid()) is None and runfiles.command(os.getpid()) == ""


@pytest.mark.skipif(os.name == "nt", reason="ps is POSIX only")
def test_start_time_is_read_in_english_whatever_the_language(monkeypatch):
    seen = []

    def ps(cmd, **kw):
        seen.append(kw["env"])
        return subprocess.CompletedProcess(cmd, 0, "Wed Nov 25 11:38:38 2026\n", "")

    monkeypatch.setenv("LANG", "de_CH.UTF-8")
    monkeypatch.setattr(runfiles, "_run", ps)
    assert runfiles.proc_start(4242) == "Wed Nov 25 11:38:38 2026"
    assert seen[0]["LC_ALL"] == "C" and seen[0]["LANG"] == "C"


def test_command_line_match_is_whole_words_with_spaces_and_umlauts():
    root = "/Users/anna/Mein Ördner/Projekt Zürich"
    want = ["-m", "orch_insights", "--dir", root, "serve"]
    cmd = f"/usr/bin/python3 -P -m orch_insights --dir {root} serve --ready-file x --port 8431"
    assert runfiles.runs_args(cmd, want)
    assert runfiles.runs_args(f"python -m orch_insights --dir {root} serve", want)  # at the very end
    assert not runfiles.runs_args(cmd.replace("Zürich", "Zürich 2"), want)
    assert not runfiles.runs_args(f"python -m orch_insights --dir {root}2 serve", want)
    assert not runfiles.runs_args("", want)
