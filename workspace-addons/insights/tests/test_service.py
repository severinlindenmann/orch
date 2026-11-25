"""The background Insights page: start, status and stop, and that nothing read from .orch/run is trusted alone."""

import json
import os
import shutil
import socket
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from orch_insights import cli, service

CORE_SRC = Path(__file__).resolve().parents[3] / "workspace" / "src"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def spaced(tmp_path, monkeypatch):
    """A workspace in a folder with spaces and umlauts; the started child finds the core like this test does."""
    root = tmp_path / "Mein Ördner mit Leerzeichen" / "Kundenprojekt Zürich"
    (root / ".orch").mkdir(parents=True)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(CORE_SRC), os.environ.get("PYTHONPATH", "")]))
    monkeypatch.delenv("ORCH_PREFERRED_PORT", raising=False)
    return root


@pytest.fixture
def kills(monkeypatch):
    """Record every real signal; signal 0 (is it alive?) still goes to the OS."""
    sent, real = [], os.kill

    def fake(pid, sig):
        if sig == 0:
            return real(pid, 0)
        sent.append((pid, sig))

    monkeypatch.setattr(os, "kill", fake)
    return sent


def _rundir(root):
    return root / ".orch" / "run" / "insights"


def _gone(pid):
    for _ in range(50):
        if hasattr(os, "WNOHANG"):  # a child of this test process lingers as a zombie that still "is alive"
            try:
                os.waitpid(pid, os.WNOHANG)
            except OSError:
                pass
        if not service.alive(pid):
            return True
        time.sleep(0.1)
    return False


def test_start_status_stop_in_a_folder_with_spaces_and_umlauts(spaced, capsys):
    cur = service.start(spaced, port=_free_port())
    try:
        assert service.start(spaced) == cur  # the running one is verified, no second one
        assert service.running(spaced) == cur
        with urllib.request.urlopen(service.url(cur["port"]) + "/", timeout=5) as r:
            assert r.status == 200
        assert cli.main(["--dir", str(spaced), "status"]) == 0
        assert capsys.readouterr().out.strip() == f"Insights: {service.url(cur['port'])}"
        assert not list(_rundir(spaced).glob("ready-*"))
    finally:
        assert service.stop(spaced) == "stopped"
    assert _gone(cur["pid"])
    assert not (_rundir(spaced) / "server.json").exists()
    assert cli.main(["--dir", str(spaced), "status"]) == 1
    assert capsys.readouterr().out.strip() == "Insights is not running."
    assert cli.main(["--dir", str(spaced), "stop"]) == 0
    assert capsys.readouterr().out.strip() == "Insights: not running."


def test_start_refuses_a_port_that_answers_with_another_nonce(spaced, monkeypatch):
    monkeypatch.setattr(service, "ident", lambda port, c: {"mac": "0" * 64, "pid": 4242})
    monkeypatch.setattr(service, "ANSWER_WAIT", 0.5)
    with pytest.raises(RuntimeError, match="Something else answers"):
        service.start(spaced, port=_free_port())
    monkeypatch.undo()
    assert service.running(spaced) is None
    assert not list(_rundir(spaced).glob("ready-*")) and not (_rundir(spaced) / "server.json").exists()


@pytest.mark.skipif(not shutil.which("false"), reason="needs a program that exits at once")
def test_a_child_that_exits_at_once_points_to_the_log(spaced, monkeypatch):
    monkeypatch.setattr(sys, "executable", shutil.which("false"))
    with pytest.raises(RuntimeError, match=r"did not start\. See \.orch/run/insights/server\.log"):
        service.start(spaced, port=_free_port())
    assert (_rundir(spaced) / "server.log").is_file()
    assert not list(_rundir(spaced).glob("ready-*")) and not (_rundir(spaced) / "server.json").exists()


def test_a_busy_chosen_port_is_refused_with_a_next_step(spaced, monkeypatch):
    import orch.procs

    monkeypatch.setattr(orch.procs, "wait_port_free", lambda port, timeout=5.0: False)
    with pytest.raises(RuntimeError, match="Something else answers on port 8999; try again in a moment"):
        service.start(spaced, port=8999)
    assert not (_rundir(spaced) / "server.log").exists()  # nothing was started


@pytest.mark.parametrize(
    "value, port",
    [("8500", 8500), ("1024", 1024), ("80", None), ("65536", None), ("", None), ("abc", None), ("²", None),
     ("８５００", None), ("-1", None)],
)  # fmt: skip
def test_preferred_port_takes_only_a_plain_valid_number(monkeypatch, value, port):
    monkeypatch.setenv("ORCH_PREFERRED_PORT", value)
    assert service._preferred_port() == port


GOOD = {"pid": 4242, "port": 8431, "nonce": "a" * 32, "started": "x"}


@pytest.mark.parametrize(
    "record",
    [
        "not json",
        "[]",
        json.dumps({**GOOD, "pid": 1}),
        json.dumps({**GOOD, "pid": True}),
        json.dumps({**GOOD, "port": 0}),
        json.dumps({**GOOD, "port": "8431"}),
        json.dumps({**GOOD, "port": 70000}),
        json.dumps({**GOOD, "nonce": "A" * 32}),
        json.dumps({**GOOD, "nonce": "a" * 31}),
        json.dumps({**GOOD, "started": None}),
    ],
)
def test_a_broken_run_record_counts_as_not_running(ws, kills, capsys, record):
    _rundir(ws).mkdir(parents=True)
    (_rundir(ws) / "server.json").write_text(record)
    assert cli.main(["--dir", str(ws), "stop", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"stopped": False, "note": "not running"}
    assert service.running(ws) is None
    assert not (_rundir(ws) / "server.json").exists()  # dropped, rewritten on the next start
    assert kills == []


@pytest.mark.parametrize("who", ["self", "parent"])
def test_a_committed_record_naming_a_live_process_is_never_signalled(ws, kills, capsys, who):
    pid = {"self": os.getpid(), "parent": os.getppid()}[who]
    rec = {**GOOD, "pid": pid, "port": _free_port(), "started": service.runfiles.proc_start(pid) or "x"}
    _rundir(ws).mkdir(parents=True)
    (_rundir(ws) / "server.json").write_text(json.dumps(rec))
    assert cli.main(["--dir", str(ws), "stop", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"stopped": False, "note": "not verified"}
    assert kills == [] and not (_rundir(ws) / "server.json").exists()


@pytest.mark.skipif(os.name == "nt", reason="the command line check is POSIX only")
def test_identity_needs_this_folder_on_the_command_line(ws, monkeypatch):
    """A server for another workspace whose path starts the same (".../workspace2") is not ours."""
    pid = os.getpid()
    monkeypatch.setattr(service.runfiles, "proc_start", lambda p: "t")
    monkeypatch.setattr(service, "ident", lambda port, c: {"pid": pid, "mac": service.mac("a" * 32, c)})
    other = f"python -P -m orch_insights --dir {ws.resolve()}2 serve --port 1"
    monkeypatch.setattr(service.runfiles, "command", lambda p: other)
    assert not service._is_ours(ws, pid, 8431, "a" * 32, "t")
    monkeypatch.setattr(
        service.runfiles, "command", lambda p: other.replace(f"{ws.resolve()}2", str(ws.resolve()))
    )
    assert service._is_ours(ws, pid, 8431, "a" * 32, "t")
    assert not service._is_ours(ws, pid, 8431, "b" * 32, "t")  # a wrong nonce
    assert not service._is_ours(ws, pid, 8431, "a" * 32, "other start")  # a reused pid


def test_ident_is_none_when_nothing_answers():
    assert service.ident(_free_port(), "ab" * 16) is None
