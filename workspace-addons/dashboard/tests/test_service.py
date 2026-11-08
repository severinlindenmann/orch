import json
import os
import socket
import time
import urllib.error
import urllib.request

import pytest

from orch_dashboard import service
from orch_dashboard.cli import main


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def kills(monkeypatch):
    """Record every real signal; signal 0 (is it alive?) still goes to the OS. No test sends a real signal to a
    pid it did not start."""
    sent, real = [], os.kill

    def fake(pid, sig):
        if sig == 0:
            return real(pid, 0)
        sent.append((pid, sig))

    monkeypatch.setattr(os, "kill", fake)
    return sent


def _rundir(ws):
    return ws / ".orch" / "run" / "dashboard"


def test_start_status_stop(ws, capsys):
    cur = service.start(ws, port=_free_port())
    try:
        assert service.start(ws) == cur  # no second one
        with urllib.request.urlopen(service.url(cur["port"]) + "/", timeout=5) as r:
            assert r.status == 200
        assert main(["--dir", str(ws), "status", "--json"]) == 0
        st = json.loads(capsys.readouterr().out)
        assert st == {"running": True, "pid": cur["pid"], "url": service.url(cur["port"])}
        assert (_rundir(ws) / "server.json").is_file() and not (ws / ".orch/addons/dashboard").exists()
    finally:
        assert service.stop(ws) == "stopped"
    for _ in range(50):
        if not service.alive(cur["pid"]):
            break
        time.sleep(0.1)
    assert main(["--dir", str(ws), "status", "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == {"running": False}
    assert main(["--dir", str(ws), "stop", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"stopped": False}


def test_start_json_gives_the_url(ws, capsys):
    try:
        assert main(["--dir", str(ws), "start", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        cur = service.running(ws)
        assert out["running"] is True and out["url"] == service.url(cur["port"]) and out["pid"] == cur["pid"]
    finally:
        service.stop(ws)


def test_planted_module_in_the_workspace_is_not_run(ws):
    (ws / "orch_dashboard.py").write_text("open('PLANTED', 'w').write('x')\n")
    (ws / "json.py").write_text("open('PLANTED', 'w').write('x')\n")
    cur = service.start(ws, port=_free_port())
    try:
        with urllib.request.urlopen(service.url(cur["port"]) + "/", timeout=5) as r:
            assert r.status == 200
    finally:
        service.stop(ws)
    assert not (ws / "PLANTED").exists()


def test_start_refuses_when_the_port_answers_with_another_nonce(ws, monkeypatch):
    monkeypatch.setattr(service, "ident", lambda port, c: {"mac": "0" * 64, "pid": 4242})
    with pytest.raises(RuntimeError, match="Something else answers"):
        service.start(ws, port=_free_port())
    monkeypatch.undo()
    assert service.running(ws) is None and not list(_rundir(ws).glob("ready-*"))


def test_busy_port_falls_back_to_a_free_one(ws, monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        monkeypatch.setattr(service, "DEFAULT_PORT", busy)
        cur = service.start(ws)
        try:
            assert cur["port"] != busy
            assert service.ident(cur["port"], "ab" * 16)["pid"] == cur["pid"]
        finally:
            service.stop(ws)


@pytest.mark.parametrize("pid", [-1, 0, 1, "parent", "self"])
def test_committed_pid_file_is_never_signalled(ws, kills, capsys, pid):
    """A repo can force-add .orch/run/dashboard/server.json (or an old .orch/addons/dashboard/server.json)."""
    pid = {"parent": os.getppid(), "self": os.getpid()}.get(pid, pid)
    rec = {"pid": pid, "port": _free_port(), "nonce": "0" * 32, "started": "x"}
    _rundir(ws).mkdir(parents=True)
    (_rundir(ws) / "server.json").write_text(json.dumps(rec))
    (ws / ".orch/addons/dashboard").mkdir(parents=True)
    (ws / ".orch/addons/dashboard/server.json").write_text(json.dumps(rec))
    assert service.running(ws) is None
    assert main(["--dir", str(ws), "stop", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["stopped"] is False
    assert kills == []
    assert main(["--dir", str(ws), "status", "--json"]) == 1  # status is not fooled either


def _echo_server(answer):
    """A local listener that answers /ready like a dashboard would, with whatever it wants."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(answer(self.path)).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.mark.parametrize("who", ["parent", "self"])
def test_a_listener_that_echoes_another_pid_gets_nothing_signalled(ws, kills, who):
    """It even knows the nonce (it can read .orch/run/) and answers the challenge correctly: the pid is not a
    dashboard of this folder (start time / command line), so nothing is signalled."""
    pid = {"parent": os.getppid(), "self": os.getpid()}[who]
    nonce = "a" * 32
    srv = _echo_server(lambda path: {"pid": pid, "mac": service.mac(nonce, path.partition("?c=")[2])})
    try:
        rec = {"pid": pid, "port": srv.server_address[1], "nonce": nonce,
               "started": service.runfiles.proc_start(pid) or "x"}
        _rundir(ws).mkdir(parents=True)
        (_rundir(ws) / "server.json").write_text(json.dumps(rec))
        assert service.stop(ws) == "not verified" and kills == []
    finally:
        srv.shutdown()
        srv.server_close()


def test_ready_never_serves_the_nonce(ws):
    cur = service.start(ws, port=_free_port())
    try:
        nonce = json.loads((_rundir(ws) / "server.json").read_text())["nonce"]
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(service.url(cur["port"]) + "/ready", timeout=5)
        got = service.ident(cur["port"], "cd" * 16)
        assert nonce not in json.dumps(got) and got["mac"] == service.mac(nonce, "cd" * 16)
    finally:
        service.stop(ws)


def test_symlinks_are_never_followed(ws, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    _rundir(ws).mkdir(parents=True)
    (_rundir(ws) / "server.json").symlink_to(victim)
    assert service.running(ws) is None and victim.read_text() == "keep me"
    (_rundir(ws) / "server.log").symlink_to(victim)
    with pytest.raises(RuntimeError, match="symbolic link"):
        service.start(ws, port=_free_port())
    assert victim.read_text() == "keep me"


def test_run_folder_symlink_is_refused(ws, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (ws / ".orch/run").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symbolic link"):
        service.start(ws, port=_free_port())
    assert list(elsewhere.iterdir()) == []


def test_command_line_must_name_exactly_this_folder(ws, kills, monkeypatch):
    me, root = os.getpid(), str(ws.resolve())
    rec = {"pid": me, "port": 1, "nonce": "b" * 32, "started": service.runfiles.proc_start(me)}
    _rundir(ws).mkdir(parents=True)
    (_rundir(ws) / "server.json").write_text(json.dumps(rec))
    monkeypatch.setattr(service.runfiles, "command", lambda pid: f"python -P -m orch_dashboard --dir {root}2 serve")
    monkeypatch.setattr(service, "ident", lambda port, c: {"pid": me, "mac": service.mac("b" * 32, c)})
    assert service.stop(ws) == "not verified" and kills == []
