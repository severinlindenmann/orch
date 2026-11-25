"""`orch insights …`: plain answers and next steps on every path, never a traceback."""

import json
import os
import socket

import pytest

from orch_insights import checkup_core as cc
from orch_insights import cli


def test_no_workspace_says_run_orch_init(tmp_path, capsys):
    folder = tmp_path / "Kein Arbeitsbereich ä"
    folder.mkdir()
    assert cli.main(["--dir", str(folder), "status"]) == 2
    assert "Run `orch init` first" in capsys.readouterr().err


def test_the_workspace_is_found_from_a_subfolder_with_spaces_and_umlauts(tmp_path, monkeypatch, capsys):
    root = tmp_path / "Mein Ördner" / "Kunde Zürich"
    deep = root / "Unterlagen 2026" / "Präsentation"
    deep.mkdir(parents=True)
    (root / ".orch").mkdir()
    assert cli.find_workspace(deep) == root.resolve()
    seen = []
    monkeypatch.setattr(cli.service, "running", lambda r: seen.append(r))
    assert cli.main(["--dir", str(deep), "status", "--json"]) == 1
    assert seen == [root.resolve()] and json.loads(capsys.readouterr().out) == {"running": False}


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="POSIX modes")
def test_a_read_only_insights_folder_is_a_plain_refusal(ws, capsys):
    """Seen live: a .orch/insights folder that cannot be written gave a traceback, so the dashboard got no answer."""
    folder = ws / ".orch" / "insights"
    folder.mkdir()
    folder.chmod(0o500)
    try:
        assert cli.main(["--dir", str(ws), "checkup", "list", "--json"]) == 2
        out = json.loads(capsys.readouterr().out)
        assert out["code"] == "not_available" and "make it writable" in out["error"]
        assert cli.main(["--dir", str(ws), "checkup", "list"]) == 2
        assert capsys.readouterr().out.startswith("Refused: The .orch/insights folder cannot be written")
    finally:
        folder.chmod(0o700)


def test_a_value_error_inside_a_check_is_not_called_bad_json(ws, monkeypatch, capsys):
    """Only the draft is parsed as JSON; another failure is never reported as "not valid JSON"."""

    def broken(root):
        b"\xe4".decode("utf-8")

    monkeypatch.setattr(cc, "listing", broken)
    assert cli.main(["--dir", str(ws), "checkup", "list", "--json"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["code"] == "not_available" and "JSON" not in out["error"]


def test_a_refusal_without_json_reads_as_words(ws, capsys):
    assert cli.main(["--dir", str(ws), "checkup", "show", "pr_nonexist01"]) == 2
    assert capsys.readouterr().out.strip() == "Refused: That proposal does not exist."


def test_needs_shows_nothing_when_the_check_up_cannot_be_read(ws, monkeypatch, capsys):
    from orch_insights import needs

    def boom(root):
        raise OSError("unreadable")

    monkeypatch.setattr(needs, "from_env", boom)
    assert cli.main(["--dir", str(ws), "needs"]) == 0
    assert capsys.readouterr().out.strip() == "Nothing needs you here."
    monkeypatch.setattr(needs, "from_env", lambda root: [{"title": "Check-up", "text": "2 ideas"}])
    assert cli.main(["--dir", str(ws), "needs"]) == 0
    assert capsys.readouterr().out.strip() == "Check-up: 2 ideas"


def test_open_opens_the_browser_and_start_prints_the_address(ws, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(cli.service, "start", lambda root: {"pid": 42, "port": 8431})
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    assert cli.main(["--dir", str(ws), "open"]) == 0
    assert opened == ["http://127.0.0.1:8431"]
    assert cli.main(["--dir", str(ws), "start"]) == 0
    assert opened == ["http://127.0.0.1:8431"]  # start never opens a browser
    assert capsys.readouterr().out.split() == ["http://127.0.0.1:8431"] * 2


def test_stop_and_status_when_running(ws, monkeypatch, capsys):
    monkeypatch.setattr(cli.service, "running", lambda root: {"pid": 42, "port": 8431})
    monkeypatch.setattr(cli.service, "stop", lambda root: "stopped")
    assert cli.main(["--dir", str(ws), "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"running": True, "pid": 42, "url": "http://127.0.0.1:8431"}
    assert cli.main(["--dir", str(ws), "stop"]) == 0
    assert capsys.readouterr().out.strip() == "Insights: stopped."


@pytest.mark.parametrize("as_json", [True, False])
def test_a_failed_start_gives_the_reason_not_a_traceback(ws, monkeypatch, capsys, as_json):
    def fail(root):
        raise RuntimeError("Insights did not start within 15 seconds.")

    monkeypatch.setattr(cli.service, "start", fail)
    assert cli.main(["--dir", str(ws), "start", *(["--json"] if as_json else [])]) == 2
    got = capsys.readouterr()
    if as_json:
        assert json.loads(got.out) == {"error": "Insights did not start within 15 seconds."}
    else:
        assert got.out == "" and got.err.strip() == "Insights did not start within 15 seconds."


@pytest.fixture
def serving(monkeypatch):
    """serve without blocking: the server stops at once, SIGTERM handling stays pytest's."""
    made = []

    class Server:
        def __init__(self, root, port):
            made.append(port)
            self.server_address = ("127.0.0.1", port or 50123)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            made.append("closed")

    monkeypatch.setattr(cli.signal, "signal", lambda *a: None)
    monkeypatch.setattr(cli, "make_server", lambda root, port: Server(root, port))
    return made


def test_serve_writes_the_bound_port_to_the_ready_file(ws, serving, capsys):
    ready = ws / ".orch" / "run" / "insights" / "ready-abc.json"
    ready.parent.mkdir(parents=True)
    assert cli.main(["--dir", str(ws), "serve", "--port", "8431", "--ready-file", str(ready)]) == 0
    assert json.loads(ready.read_text()) == {"pid": os.getpid(), "port": 8431}
    assert serving == [8431, "closed"]
    assert capsys.readouterr().out.strip() == "Insights: http://127.0.0.1:8431"


def test_no_command_serves_on_the_default_port(ws, serving):
    assert cli.main(["--dir", str(ws)]) == 0
    assert serving == [cli.DEFAULT_PORT, "closed"]


def test_a_busy_port_falls_back_only_with_auto_port(ws, monkeypatch, capsys):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        monkeypatch.setattr(cli.signal, "signal", lambda *a: None)
        assert cli.main(["--dir", str(ws), "serve", "--port", str(busy)]) == 2
        assert capsys.readouterr().err.strip()
        real = cli.make_server
        servers = []

        def make(root, port):
            srv = real(root, port)
            servers.append(srv)
            srv.serve_forever = lambda: (_ for _ in ()).throw(KeyboardInterrupt)
            return srv

        monkeypatch.setattr(cli, "make_server", make)
        assert cli.main(["--dir", str(ws), "serve", "--port", str(busy), "--auto-port"]) == 0
        assert len(servers) == 1 and servers[0].server_address[1] != busy
