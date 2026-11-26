"""The background server's runtime files and lifecycle (runfiles.py, service.py, `orch personal start|stop|status`).

Nothing here starts a real Personal process: the child is faked, so no way in, Mail or Calendar is touched."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from orch_personal import cli, runfiles, service

NONCE = "ab" * 16


@pytest.fixture
def odd(tmp_path, monkeypatch):
    """A workspace whose path has spaces and umlauts (OneDrive / a Swiss profile folder)."""
    root = tmp_path / "Mein Büro" / "Kunden Zürich ä"
    (root / ".orch" / "tickets").mkdir(parents=True)
    monkeypatch.setenv("ORCH_ROOT", str(root))
    return root


def _rec(root: Path, **kw) -> Path:
    f = service._dir(root) / "server.json"
    data = {"pid": os.getpid(), "port": 8433, "nonce": NONCE, "started": "Mon Nov 23 10:00:00 2026", **kw}
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


# --- runfiles -------------------------------------------------------------------------------------------------


def test_run_dir_is_private_in_a_path_with_spaces_and_umlauts(odd):
    d = runfiles.run_dir(odd, "personal")
    assert d == odd / ".orch" / "run" / "personal" and d.is_dir()
    if os.name != "nt":
        assert (d.stat().st_mode & 0o777) == 0o700
    assert runfiles.run_dir(odd, "personal") == d  # a second call keeps the folder


@pytest.mark.skipif(os.name == "nt", reason="symlinks need rights on Windows")
@pytest.mark.parametrize("which", [".orch/run", ".orch/run/personal"])
def test_run_dir_refuses_a_link(odd, tmp_path, which):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = odd / which
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symbolic link"):
        runfiles.run_dir(odd, "personal")
    assert list(elsewhere.iterdir()) == []


def test_run_dir_refuses_a_file_in_its_place(odd):
    (odd / ".orch" / "run").write_text("x")
    with pytest.raises(RuntimeError, match="is not a folder"):
        runfiles.run_dir(odd, "personal")


def test_private_folders_only_inside_this_workspaces_orch(tmp_path, odd):
    other = tmp_path / "other ws"
    (other / ".orch").mkdir(parents=True)
    assert runfiles.in_orch_area(odd / ".orch" / "run")
    assert runfiles.in_orch_area(odd / ".ORCH" / "x") == (os.path.normcase("A") == "a")  # casefold on Windows
    assert not runfiles.in_orch_area(odd / "plain")  # no .orch in the path at all
    assert not runfiles.in_orch_area(other / ".orch" / "run", root=odd)  # another workspace's .orch
    with pytest.raises(RuntimeError, match="will not change its rights"):
        runfiles.mkdir_private(odd / "run", odd)
    assert not (odd / "run").exists()
    with pytest.raises(RuntimeError, match="will not change its rights"):
        runfiles.check_orch_area(odd, odd)  # the workspace root itself: never


def test_grant_user_refuses_a_swapped_in_file(odd, monkeypatch):
    calls = []
    monkeypatch.setattr(runfiles, "user_sid", lambda: "S-1-5-21-1")
    monkeypatch.setattr(runfiles, "_run", lambda cmd, **kw: calls.append(cmd))
    runfiles.grant_user(odd / ".orch" / "gone", odd)  # vanished before the grant: nothing to do
    (odd / ".orch" / "f").write_text("x")
    with pytest.raises(RuntimeError, match="not a plain folder"):
        runfiles.grant_user(odd / ".orch" / "f", odd)
    assert calls == []
    runfiles.grant_user(odd / ".orch", odd)
    assert calls and calls[0][1] == str(odd / ".orch") and calls[0][-1] == "/L"


def test_read_json_takes_only_a_plain_json_object(odd, tmp_path):
    d = runfiles.run_dir(odd, "personal")
    assert runfiles.read_json(d / "missing.json") is None
    assert runfiles.read_json(d) is None  # a folder
    for i, body in enumerate((b"", b"[1, 2]", b"not json", b"\xff\xfe", b'"text"')):
        (d / f"{i}.json").write_bytes(body)
        assert runfiles.read_json(d / f"{i}.json") is None
    (d / "ok.json").write_text('{"pid": 42}')
    assert runfiles.read_json(d / "ok.json") == {"pid": 42}
    if os.name != "nt":
        (d / "link.json").symlink_to(d / "ok.json")
        assert runfiles.read_json(d / "link.json") is None


@pytest.mark.skipif(os.name == "nt", reason="symlinks need rights on Windows")
def test_write_json_replaces_a_link_and_open_append_refuses_one(odd, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    d = runfiles.run_dir(odd, "personal")
    (d / "server.json").symlink_to(victim)
    runfiles.write_json(d / "server.json", {"pid": 7})
    assert victim.read_text() == "keep me" and not (d / "server.json").is_symlink()
    assert json.loads((d / "server.json").read_text()) == {"pid": 7}
    (d / "server.log").symlink_to(victim)
    with pytest.raises(RuntimeError, match="symbolic link"):
        runfiles.open_append(d / "server.log")
    runfiles.remove(d / "server.log")
    assert victim.read_text() == "keep me" and not (d / "server.log").exists()
    runfiles.remove(d / "server.log")  # already gone: no error


def test_write_json_leaves_no_temp_file_when_it_fails(odd):
    d = runfiles.run_dir(odd, "personal")
    with pytest.raises(TypeError):
        runfiles.write_json(d / "server.json", {"bad": object()})
    assert list(d.iterdir()) == []


def test_posix_denied_message_names_the_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(runfiles, "WINDOWS", False)
    e = runfiles._denied(tmp_path / "Ordner ä", PermissionError(13, "denied"))
    assert "Ordner ä" in str(e) and "not writable" in str(e)
    assert runfiles.system_icacls().lower().endswith("icacls.exe")


@pytest.mark.parametrize("pid", [None, "123", True, 0, 1, -5, 2**31, 1.5])
def test_no_pid_from_a_file_counts_unless_it_is_a_real_one(pid):
    assert not runfiles.valid_pid(pid)
    assert not runfiles.alive(pid)
    assert runfiles.proc_start(pid) is None


def test_alive_and_identity_of_this_process():
    me = os.getpid()
    assert runfiles.alive(me)
    assert runfiles.proc_start(me)
    if os.name != "nt":
        assert "python" in runfiles.command(me).lower() or "pytest" in runfiles.command(me).lower()


def test_ps_failure_means_unknown(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("ps", 5)

    monkeypatch.setattr(runfiles, "_run", boom)
    if os.name != "nt":
        assert runfiles.proc_start(os.getpid()) is None
        assert runfiles.command(os.getpid()) == ""
    seen = {}
    monkeypatch.setattr(runfiles, "_run", lambda cmd, **kw: seen.update(kw) or SimpleNamespace(stdout="  \n"))
    if os.name != "nt":
        assert runfiles.proc_start(os.getpid()) is None  # empty answer: unknown, never ""
        assert seen["env"]["LC_ALL"] == "C"  # the English date on a Mac set to German too


def test_runs_args_matches_a_folder_with_spaces_exactly(odd):
    root = str(odd.resolve())
    args = ["-m", "orch_personal", "--dir", root, "serve"]
    assert runfiles.runs_args(f"/usr/bin/python3 -P -m orch_personal --dir {root} serve --port 8433", args)
    assert runfiles.runs_args(f"python -m orch_personal --dir {root} serve", args)
    assert not runfiles.runs_args(f"python -m orch_personal --dir {root} 2 serve", args)
    assert not runfiles.runs_args(f"python -m orch_personal --dir {root}x serve", args)


# --- service --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"pid": 1},
        {"port": True},  # JSON true is not port 1
        {"port": 0},
        {"port": 70000},
        {"port": "8433"},
        {"nonce": "short"},
        {"nonce": "AB" * 16},
        {"started": None},
    ],
)
def test_a_damaged_record_counts_as_not_running(odd, bad):
    _rec(odd, **bad)
    assert service._record(odd) is None
    assert service.running(odd) is None
    assert not (service._dir(odd) / "server.json").exists()  # stale: dropped
    assert service.stop(odd) == "not running"


def test_record_that_is_not_ours_is_never_signalled(odd, monkeypatch):
    sent = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append(sig) if sig else None)
    _rec(odd, started="a different start time")
    assert service.running(odd) is None
    _rec(odd, started="a different start time")
    assert service.stop(odd) == "not verified"
    assert sent == [] and not (service._dir(odd) / "server.json").exists()


@pytest.fixture
def live(odd, monkeypatch):
    """A real Personal server in this process, with the start nonce, so the identity check runs end to end."""
    from orch_personal.server import make_server

    monkeypatch.setenv("ORCH_PERSONAL_NONCE", NONCE)
    srv = make_server(odd, 0, vouch=lambda: None)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    port = srv.server_address[1]
    me = os.getpid()
    started = runfiles.proc_start(me)
    root = str(odd.resolve())
    monkeypatch.setattr(
        runfiles, "command", lambda pid: f"{sys.executable} -P -m orch_personal --dir {root} serve"
    )
    yield SimpleNamespace(port=port, pid=me, started=started)
    srv.shutdown()
    srv.server_close()


def test_identity_check_against_a_real_server(odd, live):
    assert service._is_ours(odd, live.pid, live.port, NONCE, live.started)
    assert not service._is_ours(odd, live.pid, live.port, "cd" * 16, live.started)  # another start's nonce
    assert not service._is_ours(odd, live.pid, live.port, NONCE, "other start")  # a reused pid
    assert not service._is_ours(odd.parent, live.pid, live.port, NONCE, live.started)  # another folder
    assert service.ident(live.port, "zz") is None  # a malformed challenge gets 404
    _rec(odd, port=live.port, started=live.started)
    assert service.running(odd) == {"pid": live.pid, "port": live.port}


def test_identity_check_refuses_a_wrong_answer(odd, monkeypatch):
    me = os.getpid()
    started = runfiles.proc_start(me)
    root = str(odd.resolve())
    monkeypatch.setattr(runfiles, "command", lambda pid: f"python -m orch_personal --dir {root} serve")
    for answer in (None, {"pid": me + 1, "mac": "x"}, {"pid": me, "mac": 5}, {"pid": me, "mac": "ü"}):
        monkeypatch.setattr(service, "ident", lambda port, c, a=answer: a)
        assert not service._is_ours(odd, me, 8433, NONCE, started)


def test_ident_is_none_when_nothing_answers():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert service.ident(port, "ab" * 16) is None


@pytest.mark.parametrize(
    ("value", "port"),
    [
        ("9000", 9000),
        ("", None),
        ("80", None),
        ("70000", None),
        ("abc", None),
        ("²", None),
        ("８４３１", None),
    ],
)
def test_preferred_port_takes_only_a_plain_number(monkeypatch, value, port):
    monkeypatch.setenv("ORCH_PREFERRED_PORT", value)
    assert service._preferred_port() == port


class FakeChild:
    """subprocess.Popen stand-in: writes the ready file like `serve --ready-file` would (or exits early)."""

    def __init__(self, ready_body=None, exit_code=None):
        self.ready_body, self.exit_code, self.terminated, self.cmd, self.kw = (
            ready_body,
            exit_code,
            False,
            None,
            {},
        )

    def __call__(self, cmd, **kw):
        self.cmd, self.kw = cmd, kw
        if self.ready_body is not None:
            ready = Path(cmd[cmd.index("--ready-file") + 1])
            ready.write_text(json.dumps(self.ready_body), encoding="utf-8")
        return self

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True


@pytest.fixture
def spawn(odd, monkeypatch):
    from orch import procs

    monkeypatch.setattr(procs, "wait_port_free", lambda port, timeout=5.0: True)
    monkeypatch.delenv("ORCH_PREFERRED_PORT", raising=False)

    def use(child):  # only service's own name: ps and other threads keep the real subprocess
        monkeypatch.setattr(service, "subprocess", SimpleNamespace(Popen=child, STDOUT=subprocess.STDOUT))
        return child

    return use


def test_start_records_the_checked_server(odd, spawn, monkeypatch):
    me = os.getpid()
    child = spawn(FakeChild({"pid": me, "port": 9123}))
    checked = []
    monkeypatch.setattr(service, "_wait_answer", lambda port, pid: None)
    monkeypatch.setattr(service, "_is_ours", lambda *a: checked.append(a) or True)
    assert service.start(odd) == {"pid": me, "port": 9123}
    rec = json.loads((service._dir(odd) / "server.json").read_text())
    assert rec["pid"] == me and rec["port"] == 9123 and rec["nonce"] == checked[0][3]
    assert child.cmd[1:4] == ["-P", "-m", "orch_personal"]  # the workspace is never on the import path
    assert child.cmd[child.cmd.index("--dir") + 1] == str(odd.resolve())
    assert child.cmd[-3:] == ["--port", "8433", "--auto-port"]
    assert child.kw["cwd"] == odd.resolve() and child.kw["env"]["ORCH_PERSONAL_NONCE"] == checked[0][3]
    assert [p.name for p in service._dir(odd).iterdir() if p.name.startswith("ready-")] == []


def test_start_returns_the_running_one(odd, spawn, monkeypatch):
    monkeypatch.setattr(service, "running", lambda root: {"pid": 4242, "port": 8433})
    child = spawn(FakeChild({"pid": 1, "port": 1}))
    assert service.start(odd) == {"pid": 4242, "port": 8433} and child.cmd is None


def test_start_says_where_the_log_is_when_the_child_exits(odd, spawn):
    child = spawn(FakeChild(None, exit_code=1))
    with pytest.raises(RuntimeError, match=r"server\.log"):
        service.start(odd)
    assert not child.terminated and not (service._dir(odd) / "server.json").exists()


@pytest.mark.parametrize("body", [{"pid": 4242, "port": "8433"}, {"pid": 4242, "port": 9123}])
def test_start_refuses_a_server_that_is_not_this_start(odd, spawn, monkeypatch, body):
    child = spawn(FakeChild(body))
    monkeypatch.setattr(service, "_wait_answer", lambda port, pid: None)
    monkeypatch.setattr(service, "_is_ours", lambda *a: False)
    with pytest.raises(RuntimeError, match="Personal was not started"):
        service.start(odd)
    assert child.terminated and not (service._dir(odd) / "server.json").exists()
    assert [p.name for p in service._dir(odd).iterdir() if p.name.startswith("ready-")] == []


def test_start_on_a_busy_chosen_port_is_refused(odd, spawn, monkeypatch):
    from orch import procs

    monkeypatch.setattr(procs, "wait_port_free", lambda port, timeout=5.0: False)
    child = spawn(FakeChild({"pid": 1, "port": 1}))
    with pytest.raises(RuntimeError, match="port 9999"):
        service.start(odd, 9999)
    assert child.cmd is None


def test_wait_answer_stops_when_the_server_is_gone(monkeypatch):
    asked = []
    monkeypatch.setattr(service, "ident", lambda port, c: asked.append(c))
    service._wait_answer(9, 1)  # pid 1 never counts: no waiting at all
    assert asked == []
    monkeypatch.setattr(service, "alive", lambda pid: True)
    monkeypatch.setattr(service, "ident", lambda port, c: {"pid": 5})
    service._wait_answer(9, 4242)  # any answer ends the wait at once


def test_stop_a_verified_server(odd, monkeypatch):
    from orch import procs

    sent = []
    monkeypatch.setattr(service, "_is_ours", lambda *a: True)
    monkeypatch.setattr(procs.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    monkeypatch.setattr(procs.sys, "platform", "linux")
    _rec(odd, pid=4242)
    assert service.stop(odd) == "stopped"
    assert sent and sent[0][0] == 4242 and not (service._dir(odd) / "server.json").exists()


# --- orch personal start | open | stop | status ---------------------------------------------------------------


def test_cli_start_open_status_stop(odd, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(service, "start", lambda root: {"pid": 4242, "port": 8433})
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    assert cli.main(["--dir", str(odd), "start", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "running": True,
        "pid": 4242,
        "url": "http://127.0.0.1:8433",
    }
    assert cli.main(["--dir", str(odd), "open", "--no-browser"]) == 0 and opened == []
    assert cli.main(["--dir", str(odd), "open"]) == 0 and opened == ["http://127.0.0.1:8433"]
    capsys.readouterr()
    monkeypatch.setattr(service, "running", lambda root: None)
    assert cli.main(["--dir", str(odd), "status"]) == 1
    assert "Personal is not running." in capsys.readouterr().out
    monkeypatch.setattr(service, "running", lambda root: {"pid": 4242, "port": 8433})
    assert cli.main(["--dir", str(odd), "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["url"] == "http://127.0.0.1:8433"
    monkeypatch.setattr(service, "stop", lambda root: "not verified")
    assert cli.main(["--dir", str(odd), "stop", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"stopped": False, "note": "not verified"}


@pytest.mark.parametrize("cmd", ["start", "stop", "status"])
def test_cli_lifecycle_errors_are_plain(odd, monkeypatch, capsys, cmd):
    """A run folder that is a file, a taskkill that fails, a child that never answers: one plain sentence."""

    def boom(root):
        raise RuntimeError("The service could not be stopped. Try again in a moment.")

    monkeypatch.setattr(service, cmd if cmd != "status" else "running", boom)
    assert cli.main(["--dir", str(odd), cmd]) == 2
    assert capsys.readouterr().err == "Refused: The service could not be stopped. Try again in a moment.\n"


def test_cli_outside_a_workspace_is_refused(tmp_path, capsys):
    assert cli.main(["--dir", str(tmp_path / "kein Ordner ü"), "status"]) == 2
    assert "orch init" in capsys.readouterr().err


def test_serve_falls_back_to_a_free_port_and_writes_the_ready_file(odd, monkeypatch, capsys):
    from orch_personal import inbox, meetings, meetings_live, server, ways

    tried = []

    class Srv:
        server_address = ("127.0.0.1", 9555)
        closed = False

        def serve_forever(self):
            raise KeyboardInterrupt  # what SIGTERM turns into

        def server_close(self):
            Srv.closed = True

    def make(root, port):
        tried.append(port)
        if port:
            raise OSError("address in use")
        return Srv()

    monkeypatch.setattr(server, "make_server", make)
    loops = []
    for mod, name in (
        (ways, "daily"),
        (meetings, "pickup_loop"),
        (meetings_live, "look_loop"),
        (inbox, "refresh_loop"),
    ):
        monkeypatch.setattr(mod, name, lambda root, stop, n=name: loops.append((n, stop)))
    monkeypatch.setattr("signal.signal", lambda *a: None)
    d = runfiles.run_dir(odd, "personal")
    ready = d / "ready-x.json"
    assert (
        cli.main(["--dir", str(odd), "serve", "--port", "8433", "--auto-port", "--ready-file", str(ready)])
        == 0
    )
    assert tried == [8433, 0] and Srv.closed
    assert json.loads(ready.read_text()) == {"pid": os.getpid(), "port": 9555}
    assert len(loops) == 4 and all(stop.is_set() for _, stop in loops)  # the loops end with the server
    assert "http://127.0.0.1:9555" in capsys.readouterr().out


def test_serve_without_auto_port_does_not_hide_a_busy_port(odd, monkeypatch):
    from orch_personal import server

    def make(root, port):
        raise OSError("address in use")

    monkeypatch.setattr(server, "make_server", make)
    with pytest.raises(OSError):
        cli.main(["--dir", str(odd), "serve", "--port", "8433"])
