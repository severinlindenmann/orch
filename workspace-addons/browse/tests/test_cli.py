import json

from orch_browse import broker, channel, cli, paths


def run(capsys, *argv):
    code = cli.main(list(argv))
    return code, capsys.readouterr().out


def test_person_adds_and_removes_sites(ws, capsys):
    code, out = run(capsys, "sites", "add", "t_abc123", "https://Example.com/x", "docs.python.org")
    assert code == 0, out
    code, out = run(capsys, "sites", "list", "--ticket", "t_abc123", "--json")
    assert json.loads(out)["sites"] == ["docs.python.org", "example.com"]
    code, out = run(capsys, "sites", "remove", "t_abc123", "example.com")
    assert paths.load_sites(ws, "t_abc123") == ["docs.python.org"]


def test_helper_cannot_change_the_site_list(ws, capsys, monkeypatch):
    monkeypatch.setenv("ORCH_RUN", "r1")
    code, out = run(capsys, "sites", "add", "t_abc123", "example.com")
    assert code == 2 and "Only a person" in out
    assert paths.load_sites(ws, "t_abc123") == []
    code, out = run(capsys, "setup")
    assert code == 2


def test_local_sites_are_refused(ws, capsys):
    for bad in ("localhost", "127.0.0.1", "nas.local", "router"):
        code, _out = run(capsys, "sites", "add", "t_abc123", bad)
        assert code == 2, bad
    assert paths.load_sites(ws, "t_abc123") == []


def test_ticket_from_the_run(ws, capsys, monkeypatch):
    monkeypatch.setenv("ORCH_TICKET", "t_abc123")
    code, out = run(capsys, "status")
    assert code == 0 and "No browser is open" in out
    monkeypatch.delenv("ORCH_TICKET")
    code, out = run(capsys, "status")
    assert code == 2 and "Which ticket" in out


def test_commands_need_an_open_browser(ws, capsys):
    code, out = run(capsys, "look", "--ticket", "t_abc123")
    assert code == 2 and "No browser is open" in out


def test_launch_options_never_name_a_profile_port_or_extension():
    args = broker.launch_args()
    assert "--use-mock-keychain" in args and "--password-store=basic" in args
    assert not [a for a in args if a.startswith(broker.REFUSED_ARGS)]
    assert any(a.startswith("--host-resolver-rules=MAP * ~NOTFOUND") for a in args)
    assert "--disable-quic" in args


def test_channel_refuses_a_caller_without_the_key(tmp_path):
    from multiprocessing import AuthenticationError
    from multiprocessing.connection import Client

    run_dir = tmp_path / "r"
    run_dir.mkdir()
    listener, _wake = channel.listen(run_dir)
    info = json.loads((run_dir / "channel.json").read_text())
    import threading

    got = []
    t = threading.Thread(target=lambda: got.append(channel.accept(listener)))
    t.start()
    try:
        with Client(info["address"], family=info["family"], authkey=b"wrong" * 6):
            pass
    except (AuthenticationError, OSError, EOFError):
        pass
    t.join(10)
    assert got == [None]
    channel.close(listener, run_dir)
    assert not (run_dir / "channel.json").exists()


class _Fake:
    def __init__(self, alive=True, connected=True):
        self._alive, self._connected = alive, connected

    def alive(self):
        return self._alive

    def is_connected(self):
        return self._connected


def _watch(b, monkeypatch):
    monkeypatch.setattr(broker, "HEALTH_SECONDS", 0.01)
    woke = []
    b.watchdog(lambda: woke.append(1))
    return woke


def test_filter_down_or_browser_gone_stops_the_broker(ws, monkeypatch):
    b = broker.Broker(ws, "t_abc123")
    b.filter, b.browser = _Fake(alive=False), _Fake()
    assert _watch(b, monkeypatch) == [1] and "network filter stopped" in b.stop_why
    b = broker.Broker(ws, "t_abc123")
    b.filter, b.browser = _Fake(), _Fake(connected=False)
    assert _watch(b, monkeypatch) == [1] and "went away" in b.stop_why
    b = broker.Broker(ws, "t_abc123")
    b.filter, b.browser = _Fake(), _Fake()
    b.last -= broker.IDLE_SECONDS + 1
    assert _watch(b, monkeypatch) == [1] and "15 minutes" in b.stop_why
