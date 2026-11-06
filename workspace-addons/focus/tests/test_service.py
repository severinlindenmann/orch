import json
import os
import urllib.request

import pytest

from orch_focus import cli, service


@pytest.mark.slow
def test_start_status_stop(ws, capsys):
    try:
        cur = service.start(ws)
        assert cur["pid"] > 1
        assert service.running(ws)["port"] == cur["port"]
        assert cli.main(["--dir", str(ws), "status", "--json"]) == 0
        data = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert data["running"] is True and data["url"] == f"http://127.0.0.1:{cur['port']}"
        assert service.start(ws) == cur  # a second start is the same server
        with urllib.request.urlopen(data["url"] + "/ready?c=" + "a" * 32, timeout=5) as r:
            assert json.loads(r.read())["pid"] == cur["pid"]
    finally:
        assert service.stop(ws) in ("stopped", "not running")
    assert service.running(ws) is None
    assert cli.main(["--dir", str(ws), "status", "--json"]) == 1


def test_stop_ignores_a_pid_file_that_is_not_focus(ws):
    d = service._dir(ws)
    (d / "server.json").write_text(
        json.dumps({"pid": os.getpid(), "port": 9, "nonce": "0" * 32, "started": "x"})
    )
    assert service.stop(ws) == "not verified"


def test_open_prints_the_ticket_address(ws, capsys):
    try:
        assert cli.main(["--dir", str(ws), "open", "t_inv7c2ab", "--no-open", "--json"]) == 0
        out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert out["url"].endswith("/t/t_inv7c2ab") and out["running"] is True
    finally:
        service.stop(ws)
