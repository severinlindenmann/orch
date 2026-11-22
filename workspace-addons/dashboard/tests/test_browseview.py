"""The browser add-on's live view in the dashboard (ORCH-1493): stream and Stop behind the terminal's checks."""

import functools
import http.client
import json
import sys
import threading
import types

import pytest

from orch_dashboard import browseview, framepass
from orch_dashboard.server import make_server

TID = "t_abc123"


class Person:
    def __init__(self, ok=True):
        self.ok = ok

    def can_act(self, headers, port):
        return self.ok and headers.get("X-Orch-Page") == "secret"

    def authed(self, headers, port):
        return self.can_act(headers, port)

    def cookie_ok(self, headers, port):
        return self.ok

    revoked = False


@pytest.fixture
def fake_browse(monkeypatch):
    """A stand-in for the browse add-on's channel module: no browser, scripted messages."""
    calls = {"stop": [], "watch": 0}
    msgs = [
        {"type": "hello", "generation": "0123456789abcdef", "ticket": TID},
        {"type": "tabs", "tabs": [{"title": "<b>Shop</b>", "url": "https://shop.example/", "current": True}]},
        {"type": "frame", "jpeg": "AAAA", "w": 1280, "h": 800, "at": 1.0},
        {"type": "secret-ish", "key": "never relayed"},
        {"type": "end", "why": "stopped by a person"},
    ]

    def watch(d, stop_after=None):
        calls["watch"] += 1
        yield from msgs

    def stop(d, gen):
        calls["stop"].append((d.name, gen))
        return {"ok": True, "out": "Stopped."}

    pkg = types.ModuleType("orch_browse")
    ch = types.ModuleType("orch_browse.channel")
    ch.watch, ch.stop = watch, stop
    pkg.channel = ch
    monkeypatch.setitem(sys.modules, "orch_browse", pkg)
    monkeypatch.setitem(sys.modules, "orch_browse.channel", ch)
    return calls


@pytest.fixture
def ws(tmp_path):
    (tmp_path / ".orch" / "tickets").mkdir(parents=True)
    (tmp_path / ".orch" / "tickets" / f"{TID}.json").write_text(json.dumps({"id": TID, "title": "T"}))
    run = tmp_path / ".orch" / "addons" / "browse" / "run" / TID
    run.mkdir(parents=True)
    (run / "state.json").write_text(json.dumps({"state": "ready", "generation": "0123456789abcdef"}))
    (run / "channel.json").write_text(json.dumps({"address": "x", "family": "AF_UNIX", "key": "ab" * 32}))
    return tmp_path


@pytest.fixture
def server(ws):
    made = []

    def start(person=None):
        srv = make_server(ws, 0, orch_bin=sys.executable)
        srv.RequestHandlerClass = functools.partial(srv.RequestHandlerClass, session=person or Person())
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        made.append(srv)
        return srv.server_address[1]

    yield start
    for srv in made:
        srv.shutdown()
        srv.server_close()


def get(port, path, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path, headers={"Host": f"127.0.0.1:{port}", **(headers or {})})
    r = conn.getresponse()
    return r.status, r.read().decode()


def post(port, path, body, secret="secret", origin=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {
        "Content-Type": "application/json",
        "Origin": origin or f"http://127.0.0.1:{port}",
        "X-Orch-Page": secret,
    }
    conn.request("POST", path, json.dumps(body).encode(), h)
    r = conn.getresponse()
    return r.status, r.read().decode()


def events(text):
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        out.append((lines.get("event"), json.loads(lines.get("data", "{}"))))
    return out


def test_signed_in_page_gets_the_stream_and_odd_messages_are_dropped(fake_browse, server):
    port = server()
    code, text = get(port, f"/api/browse/stream?ticket={TID}")
    assert code == 200
    ev = events(text)
    assert [e[0] for e in ev] == ["hello", "tabs", "frame", "end"]
    assert ev[2][1]["jpeg"] == "AAAA" and ev[3][1]["final"] is True
    assert "never relayed" not in text and "ab" * 32 not in text  # the broker's key never reaches the page


def test_stream_needs_sign_in_and_same_origin(fake_browse, server):
    port = server(Person(False))
    assert get(port, f"/api/browse/stream?ticket={TID}")[0] == 403
    assert get(port, f"/api/browse/state?ticket={TID}")[0] == 403
    port = server()
    assert get(port, f"/api/browse/stream?ticket={TID}", {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert get(port, f"/api/browse/stream?ticket={TID}", {"Origin": "http://evil.example"})[0] == 403
    assert fake_browse["watch"] == 0


def test_unknown_ticket_or_odd_folder_is_no_browser(fake_browse, server, ws):
    port = server()
    for ref in ("../etc", "t_nothere", "%2e%2e%2f"):
        code, text = get(port, f"/api/browse/stream?ticket={ref}")
        assert code == 200 and events(text) == [("end", {"why": browseview.NO_BROWSER, "final": False})]
    assert fake_browse["watch"] == 0


def test_state_says_open_without_the_key(fake_browse, server):
    port = server()
    code, text = get(port, f"/api/browse/state?ticket={TID}")
    assert code == 200 and json.loads(text) == {"open": True, "generation": "0123456789abcdef"}


def test_stop_needs_the_persons_session_and_names_the_generation(fake_browse, server):
    port = server()
    body = {"ticket": TID, "generation": "0123456789abcdef"}
    assert post(port, "/api/browse/stop", body, secret="wrong")[0] == 403
    assert post(port, "/api/browse/stop", body, origin="http://evil.example")[0] == 403
    assert post(port, "/api/browse/stop", {"ticket": TID})[0] == 400
    assert post(port, "/api/browse/stop", {"ticket": TID, "generation": "../../x"})[0] == 404
    assert fake_browse["stop"] == []
    code, text = post(port, "/api/browse/stop", body)
    assert code == 200 and json.loads(text)["ok"] is True
    assert fake_browse["stop"] == [(TID, "0123456789abcdef")]


def test_without_the_add_on_it_says_so(server, monkeypatch):
    monkeypatch.setitem(sys.modules, "orch_browse", None)
    port = server()
    _code, text = get(port, f"/api/browse/stream?ticket={TID}")
    assert events(text) == [("end", {"why": browseview.NOT_ON, "final": True})]
    assert json.loads(get(port, f"/api/browse/state?ticket={TID}")[1]) == {"open": False}


def test_no_add_on_frame_may_watch_or_stop_a_browser():
    assert not framepass.ALL_ROOT_PATHS & {"/api/browse/stream", "/api/browse/state", "/api/browse/stop"}
