"""Something other than a regular file planted in .orch/run/factory/: the watcher commands answer, never hang."""

import os

import pytest

from orch_factory import runfiles, service

posix = pytest.mark.skipif(os.name == "nt", reason="FIFOs are POSIX")


@posix
def test_a_fifo_in_place_of_the_record_never_hangs_status_or_stop(ws, run):
    os.mkfifo(runfiles.run_dir(ws, "factory") / "factory.json")
    assert run("status", code=1) == {"running": False}  # the fixture's timeout fails a hang
    assert run("stop") == {"stopped": False}


@posix
def test_a_fifo_in_place_of_the_log_refuses_start_instead_of_hanging(ws, run):
    os.mkfifo(runfiles.run_dir(ws, "factory") / "factory.log")
    refused = run("start", code=2)
    assert "not a regular file" in refused["error"] and "Remove it" in refused["error"]
    assert run("status", code=1) == {"running": False}


def test_a_folder_in_place_of_the_log_refuses_start(ws, run):
    (runfiles.run_dir(ws, "factory") / "factory.log").mkdir()
    refused = run("start", code=2)
    assert "not a regular file" in refused["error"] and "administrator" not in refused["error"]


def test_a_linked_run_folder_is_refused_with_what_to_do(ws, run, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (ws / ".orch" / "run").symlink_to(elsewhere, target_is_directory=True)
    assert run("status", code=1) == {"running": False}
    for cmd in ("start", "stop"):  # stop used to say a recorded process "is not the Factory watcher"
        refused = run(cmd, code=2)
        assert "symbolic link" in refused["error"] and "Remove it" in refused["error"]
    assert list(elsewhere.iterdir()) == []


def test_page_url_needs_a_verified_watcher_and_a_real_port(ws, monkeypatch):
    d = runfiles.run_dir(ws, "factory")
    runfiles.write_json(d / "factory.json", {"pid": os.getpid(), "nonce": "e" * 32, "port": 8123})
    assert service.page_url(ws) is None  # this test process is not a verified watcher
    monkeypatch.setattr(service, "_verified", lambda root, rec: rec and rec["pid"])
    assert service.page_url(ws) == "http://127.0.0.1:8123"
    for port in (0, 65536, "8123", True, None, 80.0):
        runfiles.write_json(d / "factory.json", {"pid": os.getpid(), "nonce": "e" * 32, "port": port})
        assert service.page_url(ws) is None
