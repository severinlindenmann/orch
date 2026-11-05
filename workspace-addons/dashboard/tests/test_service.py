import json
import time
import urllib.request

import pytest

from orch_dashboard import service
from orch_dashboard.cli import main


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_start_status_stop(ws, capsys):
    cur = service.start(ws, port=_free_port())
    try:
        assert service.start(ws) == cur  # no second one
        with urllib.request.urlopen(service.url(cur["port"]) + "/", timeout=5) as r:
            assert r.status == 200
        assert main(["--dir", str(ws), "status", "--json"]) == 0
        st = json.loads(capsys.readouterr().out)
        assert st == {"running": True, "pid": cur["pid"], "url": service.url(cur["port"])}
    finally:
        assert service.stop(ws)
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
    monkeypatch.setattr(service, "_nonce_of", lambda port: "someone-else")
    with pytest.raises(RuntimeError, match="Something else answers"):
        service.start(ws, port=_free_port())
    assert service.running(ws) is None and not list((ws / ".orch/addons/dashboard").glob("ready-*"))


def test_busy_port_falls_back_to_a_free_one(ws, monkeypatch):
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        monkeypatch.setattr(service, "DEFAULT_PORT", busy)
        cur = service.start(ws)
        try:
            assert cur["port"] != busy
            with urllib.request.urlopen(service.url(cur["port"]) + "/ready", timeout=5) as r:
                assert r.status == 200
        finally:
            service.stop(ws)


def test_stale_file_is_dropped(ws):
    f = ws / ".orch/addons/dashboard/server.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"pid": 999999, "port": 1}))
    assert service.running(ws) is None and not f.exists()
