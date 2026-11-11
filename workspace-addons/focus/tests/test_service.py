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


def test_open_takes_a_ticket_key(ws, capsys):
    p = ws / ".orch" / "tickets" / "t_inv7c2ab.json"
    t = json.loads(p.read_text()) if p.exists() else {"id": "t_inv7c2ab"}
    t["key"] = "INV-3"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(t))
    try:
        assert cli.main(["--dir", str(ws), "open", "inv-3", "--no-open", "--json"]) == 0
        out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert out["url"].endswith("/t/t_inv7c2ab")
    finally:
        service.stop(ws)


@pytest.mark.slow
@pytest.mark.skipif(os.name == "nt", reason="ps is POSIX")
def test_stop_finds_a_service_started_under_another_language(ws, monkeypatch):
    """fb20: started under one Mac language, stopped under another -> still stopped, record removed."""
    monkeypatch.setenv("LC_ALL", "de_CH.UTF-8")
    monkeypatch.setenv("LANG", "de_CH.UTF-8")
    cur = service.start(ws)
    try:
        monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        assert service.stop(ws) == "stopped"
        assert not (service._dir(ws) / "server.json").exists()
    finally:
        try:
            os.kill(cur["pid"], 15)
        except OSError:
            pass


@pytest.mark.parametrize("matches", [False, True])
def test_windows_stop_checks_record_before_taskkill(ws, monkeypatch, matches):
    from unittest.mock import Mock

    from orch import procs

    rec = {"pid": 4242, "port": 8430, "nonce": "a" * 32, "started": "original"}
    service.runfiles.write_json(service._dir(ws) / "server.json", rec)
    monkeypatch.setattr(service.runfiles, "proc_start", lambda pid: "original" if matches else "reused")
    monkeypatch.setattr(service, "alive", lambda pid: True)
    monkeypatch.setattr(service.runfiles, "command", lambda pid: "ignored")
    monkeypatch.setattr(service.runfiles, "runs_args", lambda *args: True)
    monkeypatch.setattr(service, "ident", lambda port, c: {"pid": 4242, "mac": service.mac(rec["nonce"], c)})
    run = Mock()
    monkeypatch.setattr(procs.sys, "platform", "win32")
    monkeypatch.setattr(procs, "_run", run)
    assert service.stop(ws) == ("stopped" if matches else "not verified")
    if matches:
        assert run.call_args.args[0] == ["taskkill", "/PID", "4242", "/T", "/F"]
    else:
        run.assert_not_called()


def test_start_waits_for_old_listener_before_spawn(ws, monkeypatch):
    from unittest.mock import MagicMock

    from orch import procs

    now = [0.0]
    monkeypatch.setattr(procs.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(procs.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    probe = MagicMock(side_effect=[MagicMock(), MagicMock(), ConnectionRefusedError()])
    monkeypatch.setattr(procs.socket, "create_connection", probe)

    def spawn(*args, **kwargs):
        assert probe.call_count == 3
        assert now[0] == pytest.approx(0.2)
        raise RuntimeError("reached spawn after port freed")

    monkeypatch.setattr(service.subprocess, "Popen", spawn)
    with pytest.raises(RuntimeError, match="reached spawn after port freed"):
        service.start(ws, port=8430)
