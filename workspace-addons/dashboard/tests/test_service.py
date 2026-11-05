import json
import time
import urllib.request

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


def test_start_json_gives_the_url(ws, capsys, monkeypatch):
    port = _free_port()
    monkeypatch.setattr(service, "_pick_port", lambda: port)
    try:
        assert main(["--dir", str(ws), "start", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["running"] is True and out["url"] == f"http://127.0.0.1:{port}"
    finally:
        service.stop(ws)


def test_stale_file_is_dropped(ws):
    f = ws / ".orch/addons/dashboard/server.json"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps({"pid": 999999, "port": 1}))
    assert service.running(ws) is None and not f.exists()
