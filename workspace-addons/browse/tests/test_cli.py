import io
import json
import sys
import types
from pathlib import Path

import pytest

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
    monkeypatch.setattr(broker, "GRACE_SECONDS", 0.01)
    woke, hard = [], []
    b.hard_exit = lambda: hard.append(1)
    b.watchdog(lambda: woke.append(1))
    b.hard = hard
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


def test_damaged_site_list_opens_nothing_with_a_plain_line(ws, capsys):
    paths.sites_file(ws, "t_abc123").parent.mkdir(parents=True, exist_ok=True)
    paths.sites_file(ws, "t_abc123").write_text("{ not json", encoding="utf-8")
    assert cli.main(["open", "http://site.test/", "--ticket", "t_abc123"]) == 2
    assert "damaged" in capsys.readouterr().out


def test_test_browser_is_ignored_outside_a_strict_test_home(monkeypatch):
    monkeypatch.setenv("ORCH_BROWSE_TEST_BROWSER", "/tmp/wrapper.sh")
    monkeypatch.delenv("ORCH_HOME_STRICT", raising=False)
    assert broker.test_browser() is None
    monkeypatch.setenv("ORCH_HOME_STRICT", "0")
    assert broker.test_browser() is None
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    assert broker.test_browser() == "/tmp/wrapper.sh"
    monkeypatch.delenv("ORCH_BROWSE_TEST_BROWSER")
    assert broker.test_browser() is None


def test_a_hung_page_step_ends_the_broker_hard(ws, monkeypatch):
    b = broker.Broker(ws, "t_abc123")
    b.filter, b.browser = _Fake(), _Fake()
    b.busy_since = b.last - broker.STEP_SECONDS - 1
    assert _watch(b, monkeypatch) == [1] and "hung" in b.stop_why
    assert b.hard == [1]  # the main thread never said it closed: exit hard
    b = broker.Broker(ws, "t_abc123")
    b.filter, b.browser = _Fake(alive=False), _Fake()
    b.closed.set()
    _watch(b, monkeypatch)
    assert b.hard == []


class _Conn:
    def __init__(self, left=False):
        self.sent = []
        self.left = left

    def send_bytes(self, b):
        self.sent.append(json.loads(b))

    def poll(self, timeout=0):
        return self.left  # a watcher's other side sends nothing; it only closes

    def recv_bytes(self, n):
        raise EOFError

    def close(self):
        pass


def test_a_slow_watcher_gets_only_the_newest_picture():
    w = broker.Watcher(_Conn())
    for i in range(100):
        w.put({"type": "frame", "n": i})
    w.put({"type": "event", "text": "x"})
    import threading
    import time

    t = threading.Thread(target=w.run, kwargs={"heartbeat": 0.01})
    t.start()
    time.sleep(0.2)
    w.end("closed")
    t.join(5)
    frames = [m for m in w.conn.sent if m["type"] == "frame"]
    assert [f["n"] for f in frames] == [99]
    assert w.conn.sent[-1]["type"] == "end" or any(m["type"] == "end" for m in w.conn.sent)


def test_a_watcher_whose_other_side_closed_ends_without_waiting_for_the_beat():
    w = broker.Watcher(_Conn(left=True), "pageA")
    import threading

    t = threading.Thread(target=w.run, kwargs={"heartbeat": 60})
    t.start()
    t.join(5)
    assert not t.is_alive() and w.gone and w.conn.sent == []


def test_the_newest_owner_state_replaces_the_older_one():
    w = broker.Watcher(_Conn())
    w.put({"type": "control", "state": "finishing"})
    w.put({"type": "event", "text": "x"})
    w.put({"type": "control", "state": "person"})
    assert [m.get("state") for m in w.queue] == [None, "person"]


def test_jpeg_size_reads_the_frame_header():
    sof = (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x10"
        + b"\x00" * 14
        + b"\xff\xc0\x00\x11\x08\x03\x20\x05\x00"
        + b"\x00" * 12
    )
    assert broker._jpeg_size(sof) == (1280, 800)
    assert broker._jpeg_size(b"not a jpeg") == (0, 0)


def test_watching_is_not_activity(ws):
    b = broker.Broker(ws, "t_abc123")
    before = b.last
    b._broadcast({"type": "frame"})
    w = broker.Watcher(_Conn())
    with b.wlock:
        b.watchers.add(w)
    b._broadcast({"type": "event", "text": "y"})
    assert b.last == before and w.queue


def test_the_end_gets_through_a_full_queue():
    w = broker.Watcher(_Conn())
    for i in range(80):
        w.put({"type": "event", "text": str(i)})
    w.end("closed")
    w.run(heartbeat=0.01)
    assert w.conn.sent == [{"type": "end", "why": "closed"}]


def test_view_is_an_empty_valid_tab(capsys):
    """The dashboard draws the Browser page itself (panel "browser", ORCH-1494); the view only answers."""
    assert cli.main(["view", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "orch.addon-view/1" and doc["blocks"] == [] and doc["generated_at"].endswith("Z")


def test_a_clear_drops_the_old_tabs_picture():
    w = broker.Watcher(_Conn())
    w.put({"type": "frame", "n": 1})
    w.put({"type": "clear"})
    assert w.frame is None and w.queue == [{"type": "clear"}]
    w.put({"type": "frame", "n": 2})
    assert w.frame == {"type": "frame", "n": 2}


@pytest.fixture
def core(monkeypatch):
    """The real orch core importable (it is, inside orch's tool env): its person check asks at a terminal."""
    src = Path(__file__).resolve().parents[3] / "workspace" / "src"
    monkeypatch.syspath_prepend(str(src))
    yield
    for name in [m for m in sys.modules if m == "orch" or m.startswith("orch.")]:
        del sys.modules[name]


class _Tty(io.StringIO):
    def isatty(self):
        return True


def _fake_download(monkeypatch):
    ran = []
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **k: ran.append(a) or types.SimpleNamespace(returncode=0)
    )
    return ran


def test_setup_refusal_in_a_helper_shell_names_the_own_terminal(ws, capsys, monkeypatch, core):
    ran = _fake_download(monkeypatch)
    monkeypatch.setenv("ORCH_AGENT", "claude")
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(""))
    code, out = run(capsys, "setup")
    assert code == 2 and "your own terminal" in out and not ran


def test_setup_typed_with_bang_in_a_helper_session_asks_at_the_terminal(ws, capsys, monkeypatch, core):
    ran = _fake_download(monkeypatch)
    monkeypatch.setenv("ORCH_AGENT", "claude")  # a ! command carries the helper session's environment
    monkeypatch.setattr(cli.sys, "stdin", _Tty("n\n"))
    code, out = run(capsys, "setup")
    assert code == 2 and "Not confirmed" in out and not ran
    monkeypatch.setattr(cli.sys, "stdin", _Tty("y\n"))
    code, out = run(capsys, "setup")
    assert code == 0 and "ready" in out and ran


def _dry_run(monkeypatch, where):
    out = (
        f"Chrome Headless Shell (playwright chromium-headless-shell v1248)\n  Install location:    {where}\n"
    )
    monkeypatch.setattr(
        cli.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=out)
    )


def test_setup_check_says_whether_the_browser_is_downloaded(tmp_path, capsys, monkeypatch):
    where = tmp_path / "chromium_headless_shell-1248"
    _dry_run(monkeypatch, where)
    code, out = run(capsys, "setup", "--check")
    assert code == 2 and "orch browse setup" in out
    where.mkdir()  # a half-finished download has no marker yet
    assert run(capsys, "setup", "--check")[0] == 2
    (where / "INSTALLATION_COMPLETE").write_text("")
    code, out = run(capsys, "setup", "--check")
    assert code == 0 and "downloaded" in out


def test_setup_check_never_downloads_even_for_a_helper(tmp_path, capsys, monkeypatch):
    calls = []
    monkeypatch.setenv("ORCH_RUN", "r1")
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda argv, **k: calls.append(argv) or types.SimpleNamespace(returncode=1, stdout=""),
    )
    assert run(capsys, "setup", "--check")[0] == 2
    assert calls and all("--dry-run" in argv for argv in calls)


def test_outside_a_workspace_says_where_to_go(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ORCH_ROOT", str(tmp_path / "nowhere"))
    code, out = run(capsys, "status", "--ticket", "t_abc123")
    assert code == 2 and "No orch workspace here" in out


def test_workspace_found_from_a_subfolder_with_spaces_and_umlauts(tmp_path, capsys, monkeypatch):
    root = tmp_path / "OneDrive - Müller AG" / "Projekte Ä"
    (root / ".orch" / "tickets").mkdir(parents=True)
    (root / ".orch" / "tickets" / "t_abc123.json").write_text('{"id": "t_abc123"}', encoding="utf-8")
    sub = root / "Unterordner ö"
    sub.mkdir()
    monkeypatch.delenv("ORCH_ROOT", raising=False)
    monkeypatch.delenv("ORCH_TICKET", raising=False)
    monkeypatch.chdir(sub)
    code, out = run(capsys, "sites", "add", "t_abc123", "example.com")
    assert code == 0, out
    assert paths.load_sites(root, "t_abc123") == ["example.com"]


def test_unknown_ticket_and_unknown_command(ws, capsys):
    code, out = run(capsys, "status", "--ticket", "t_zzzz99")
    assert code == 2 and "No ticket t_zzzz99" in out
    code, out = run(capsys, "fly", "--ticket", "t_abc123")
    assert code == 2 and "Unknown command 'fly'" in out and "orch browse open" in out
    for argv in ([], ["help"]):
        code, out = run(capsys, *argv)
        assert code == 0 and out.startswith("orch browse:")


def test_site_list_empty_states_and_mistakes(ws, capsys):
    code, out = run(capsys, "sites", "list", "--ticket", "t_abc123")
    assert code == 0 and "empty" in out
    code, out = run(capsys, "sites", "list", "--ticket", "t_abc123", "--json")
    assert json.loads(out) == {"ticket": "t_abc123", "sites": []}
    code, out = run(capsys, "sites", "add", "--ticket", "t_abc123")
    assert code == 2 and out.startswith("orch browse sites [list|add|remove]")
    code, out = run(capsys, "sites", "rename", "t_abc123", "example.com")
    assert code == 2 and out.startswith("orch browse sites")
    code, out = run(capsys, "sites", "add", "t_abc123", "user@example.com")
    assert code == 2 and out.startswith("Not added:")
    code, out = run(capsys, "open", "https://example.com/", "--ticket", "t_abc123")
    assert code == 2 and "site list is empty" in out and "orch browse sites add t_abc123" in out


@pytest.mark.parametrize("text", ['["example.com"]', '{"sites": [5]}', "{ not json"])
def test_a_damaged_site_list_says_so_and_a_person_can_write_it_again(ws, capsys, text):
    paths.sites_file(ws, "t_abc123").parent.mkdir(parents=True, exist_ok=True)
    paths.sites_file(ws, "t_abc123").write_text(text, encoding="utf-8")
    code, out = run(capsys, "sites", "list", "--ticket", "t_abc123")
    assert code == 2 and "damaged" in out and "a person fixes it" in out
    code, out = run(capsys, "open", "https://example.com/", "--ticket", "t_abc123")
    assert code == 2 and "damaged" in out
    code, out = run(capsys, "sites", "add", "t_abc123", "example.com")
    assert code == 0 and paths.load_sites(ws, "t_abc123") == ["example.com"]


def test_status_and_close_without_a_browser_say_so_with_the_last_reason(ws, capsys):
    paths.write_state(paths.run_dir(ws, "t_abc123"), {"state": "ended", "why": "idle for 15 minutes"})
    code, out = run(capsys, "status", "--ticket", "t_abc123")
    assert code == 0 and "No browser is open" in out and "Last time: idle for 15 minutes." in out
    code, out = run(capsys, "close", "--ticket", "t_abc123")
    assert code == 0 and "No browser is open" in out


def _fake_broker(monkeypatch, answers):
    """A broker that answers ping and then the given answers in order; records what was sent."""
    sent = []

    def call(run, cmd, args, timeout=120, slow=None):
        sent.append((cmd, args))
        if cmd == "ping":
            return {"ok": True, "out": "pong"}
        if slow:
            slow[1]()
        return answers.pop(0)

    monkeypatch.setattr(channel, "call", call)
    monkeypatch.setattr(channel, "person", lambda run, cmd, args: None)
    return sent


def test_ask_person_waits_and_says_why_a_step_is_slow(ws, capsys, monkeypatch):
    sent = _fake_broker(monkeypatch, [{"ok": True, "out": "Given back. Look again."}])
    monkeypatch.setattr(
        channel, "person", lambda run, cmd, args: {"ok": True, "out": json.dumps({"state": "person"})}
    )
    code = cli.main(["ask-person", "sign in to the shop", "--ticket", "t_abc123"])
    out, err = capsys.readouterr()
    assert code == 0 and "Given back" in out
    assert ("ask", ["sign in to the shop"]) in sent
    assert "Waiting for a person" in err and "A person is using the browser" in err


def test_a_slow_step_with_the_helper_in_control_or_an_odd_answer_says_nothing(ws, capsys, monkeypatch):
    for who in ({"ok": True, "out": json.dumps({"state": "helper"})}, {"ok": True, "out": "not json"}, None):
        _fake_broker(monkeypatch, [{"ok": False, "out": "Element 9 is not on the page. Look again."}])
        monkeypatch.setattr(channel, "person", lambda run, cmd, args, w=who: w)
        code = cli.main(["click", "9", "--ticket", "t_abc123"])
        out, err = capsys.readouterr()
        assert code == 2 and "Look again" in out and err == ""


def test_a_broker_that_stops_mid_step_says_how_to_start_again(ws, capsys, monkeypatch):
    _fake_broker(monkeypatch, [None])
    code, out = run(capsys, "look", "--ticket", "t_abc123")
    assert code == 2 and "The browser stopped" in out and "orch browse open" in out
