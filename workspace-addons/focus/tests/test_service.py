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


def test_a_watch_only_restart_asks_for_the_old_port_and_may_move_on(ws, monkeypatch):
    """The person's restart of a watch-only Focus tries its old port first but is not pinned to it: a port
    another server took meanwhile (parallel CI workers share 8430) must not fail the start."""
    from orch import procs

    monkeypatch.setattr(service, "running", lambda root: {"pid": 4242, "port": 8555})
    monkeypatch.setattr(
        service.runfiles,
        "read_json",
        lambda path: {"watch_only": True} if path.name == "server.json" else None,
    )
    stopped = []
    monkeypatch.setattr(service, "stop", lambda root: stopped.append(root) or "stopped")
    monkeypatch.setattr(procs, "wait_port_free", lambda port, *a, **k: False)  # the old port is still taken
    from orch import tickets

    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    seen = []

    def spawn(cmd, *args, **kwargs):
        seen.append(cmd)
        raise RuntimeError("reached spawn")

    monkeypatch.setattr(service.subprocess, "Popen", spawn)
    with pytest.raises(RuntimeError, match="reached spawn"):
        service.start(ws)
    assert stopped and seen
    cmd = seen[0]
    assert cmd[cmd.index("--port") + 1] == "8555" and "--auto-port" in cmd


@pytest.mark.slow
def test_a_persons_start_restarts_focus_a_helper_started(ws, monkeypatch):
    """Watch-only (a helper started it): the person's start replaces it (its old port when free)."""
    from orch import adapters

    for k, v in list(os.environ.items()):
        if adapters.detect_env({k: v}):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ORCH_AGENT", "claude")
    try:
        cur = service.start(ws)
        assert service.start(ws) == cur
        monkeypatch.delenv("ORCH_AGENT")
        new = service.start(ws)
        assert new["pid"] != cur["pid"]  # its old port when free, else another (parallel tests share ports)
        assert json.loads((service._dir(ws) / "server.json").read_text())["watch_only"] is False
    finally:
        assert service.stop(ws) in ("stopped", "not running")


# ORCH-1443 (owner): a restart (an add-on added, removed or updated) keeps the runs Focus started; only Ctrl+C
# or a real stop ends them. Core marks the stop of a restart with ORCH_SERVICE_RESTART=1.
def _fake_server(ws, monkeypatch, pid=4242):
    import orch.procs

    monkeypatch.setattr(
        service, "_record", lambda root: {"pid": pid, "port": 9, "nonce": "0" * 32, "started": "x"}
    )
    monkeypatch.setattr(orch.procs, "stop_tree", lambda pid, verified=None: True)


def test_the_stop_of_a_restart_leaves_a_mark_for_that_server_only(ws, monkeypatch):
    _fake_server(ws, monkeypatch)
    monkeypatch.setenv(service.RESTART_ENV, "1")
    assert service.stop(ws) == "stopped"
    assert service.take_restart_mark(ws, pid=4242) is True
    assert service.take_restart_mark(ws, pid=4242) is False  # used once
    assert service.stop(ws) == "stopped"
    assert service.take_restart_mark(ws, pid=999) is False  # another server's mark is not this one's restart
    assert not service._restart_mark(ws).exists()


def test_a_real_stop_leaves_no_mark_and_clears_an_old_one(ws, monkeypatch):
    _fake_server(ws, monkeypatch)
    monkeypatch.delenv(service.RESTART_ENV, raising=False)
    service.stop(ws, restart=True)
    assert service.stop(ws) == "stopped"
    assert service.take_restart_mark(ws, pid=4242) is False


def test_a_failed_stop_of_a_restart_leaves_no_mark(ws, monkeypatch):
    import orch.procs

    _fake_server(ws, monkeypatch)

    def boom(pid, verified=None):
        raise RuntimeError("taskkill failed")

    monkeypatch.setattr(orch.procs, "stop_tree", boom)
    with pytest.raises(RuntimeError):
        service.stop(ws, restart=True)
    assert not service._restart_mark(ws).exists()


def test_an_old_restart_mark_does_not_count(ws, monkeypatch):
    _fake_server(ws, monkeypatch)
    service.stop(ws, restart=True)
    import time

    assert (
        service.take_restart_mark(ws, now=time.time() + service.RESTART_MARK_SECONDS + 5, pid=4242) is False
    )


def test_serve_ends_the_started_runs_unless_it_is_a_restart(ws, monkeypatch):
    ended = []

    class Srv:
        server_address = ("127.0.0.1", 1)

        def serve_forever(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "make_server", lambda *a, **k: Srv())
    monkeypatch.setattr(cli, "stop_started", lambda srv: ended.append(srv))
    monkeypatch.setattr(cli.signal, "signal", lambda *a: None)  # keep pytest's own SIGTERM handler
    args = cli.argparse.Namespace(port=0, ready_file=None)
    cli._serve(args, ws)
    assert len(ended) == 1  # Ctrl+C or a real stop: the runs Focus started end
    service.runfiles.write_json(
        service._restart_mark(ws), {"at": __import__("time").time(), "pid": os.getpid()}
    )
    cli._serve(args, ws)
    assert len(ended) == 1  # a restart: they keep running
