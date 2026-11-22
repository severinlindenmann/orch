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
    calls = {"stop": [], "watch": 0, "pages": [], "person": []}
    msgs = [
        {"type": "hello", "generation": "0123456789abcdef", "ticket": TID},
        {"type": "tabs", "tabs": [{"title": "<b>Shop</b>", "url": "https://shop.example/", "current": True}]},
        {"type": "frame", "jpeg": "AAAA", "w": 1280, "h": 800, "at": 1.0},
        {"type": "secret-ish", "key": "never relayed"},
        {"type": "end", "why": "stopped by a person"},
    ]

    def watch(d, stop_after=None, page=""):
        calls["watch"] += 1
        calls["pages"].append(page)
        yield from msgs

    def person(d, cmd, args):
        calls["person"].append((d.name, cmd, args))
        if args[1] == "not-mine":
            return {"ok": False, "out": "Another page has control of this browser."}
        return {
            "ok": True,
            "out": json.dumps({"state": "person", "epoch": 4, "mine": True, "page": "x", "sent": 2}),
        }

    def stop(d, gen):
        calls["stop"].append((d.name, gen))
        return {"ok": True, "out": "Stopped."}

    pkg = types.ModuleType("orch_browse")
    ch = types.ModuleType("orch_browse.channel")
    ch.watch, ch.stop, ch.person = watch, stop, person
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


def post(port, path, body, secret="secret", origin=None, extra=None, raw=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {
        "Content-Type": "application/json",
        "Origin": origin or f"http://127.0.0.1:{port}",
        "X-Orch-Page": secret,
        **(extra or {}),
    }
    conn.request("POST", path, raw if raw is not None else json.dumps(body).encode(), h)
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


# ---- every ticket's browser in one list (ORCH-1494: the Browser page and the small previews) ----


def _run(ws, tid, doc, channel=True, age=0.0):
    import os
    import time

    d = ws / ".orch" / "addons" / "browse" / "run" / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps(doc))
    if channel:
        (d / "channel.json").write_text(json.dumps({"key": "cd" * 32}))
    if age:
        t = time.time() - age
        os.utime(d / "state.json", (t, t))
    return d


def test_list_shows_open_and_recently_ended_without_keys(fake_browse, server, ws, monkeypatch):
    monkeypatch.setattr(browseview, "_on", lambda root: True)
    _run(
        ws,
        "t_old0001",
        {"state": "ended", "why": "closed after 15 minutes without a command"},
        False,
        age=2 * 86400,
    )
    _run(ws, "t_end0001", {"state": "ended", "why": "stopped by a person"}, False, age=600)
    _run(ws, "t_dead001", {"state": "ready", "generation": "ffffffffffffffff", "pid": 2**22 + 12345}, True)
    port = server()
    code, text = get(port, "/api/browse/list")
    assert code == 200
    doc = json.loads(text)
    assert doc["on"] is True
    rows = {r["ticket"]: r for r in doc["browsers"]}
    assert rows[TID]["open"] is True and rows[TID]["generation"] == "0123456789abcdef"
    assert rows[TID]["title"] == "T" and rows["t_end0001"]["title"] == ""  # no ticket file: no title
    assert rows["t_end0001"]["open"] is False and rows["t_end0001"]["why"] == "stopped by a person"
    assert "t_old0001" not in rows, "a browser that ended days ago is not listed"
    assert "t_dead001" not in rows or rows["t_dead001"]["open"] is False, "a broker that is gone is not live"
    assert doc["browsers"][0]["open"] is True, "open browsers come first"
    assert "ab" * 32 not in text and "cd" * 32 not in text and "address" not in text


def test_list_skips_links_and_odd_folders(fake_browse, ws, tmp_path, monkeypatch):
    monkeypatch.setattr(browseview, "_on", lambda root: True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "state.json").write_text(json.dumps({"state": "ready", "generation": "1" * 16}))
    (elsewhere / "channel.json").write_text("{}")
    base = ws / ".orch" / "addons" / "browse" / "run"
    (base / "t_link0001").symlink_to(elsewhere, target_is_directory=True)
    _run(ws, "not-a-ticket", {"state": "ready"})
    (base / "t_bad00001").mkdir()
    (base / "t_bad00001" / "state.json").write_text("[1, 2")
    tickets = [r["ticket"] for r in browseview.listing(ws)["browsers"]]
    assert tickets == [TID]


def test_list_needs_sign_in_and_says_off_without_the_add_on(server, monkeypatch):
    monkeypatch.setitem(sys.modules, "orch_browse", None)
    port = server(Person(False))
    assert get(port, "/api/browse/list")[0] == 403
    port = server()
    assert get(port, "/api/browse/list", {"Origin": "http://evil.example"})[0] == 403
    assert json.loads(get(port, "/api/browse/list")[1]) == {"on": False, "browsers": []}


def test_list_is_off_while_the_add_on_is_not_turned_on(fake_browse, ws):
    assert browseview.listing(ws) == {
        "on": False,
        "browsers": [],
    }  # installed (the stand-in) but not turned on here


def test_no_add_on_frame_may_list_browsers():
    assert "/api/browse/list" not in framepass.ALL_ROOT_PATHS


# ---- take over and give back (ORCH-1495) ----

GEN = "0123456789abcdef"


def test_each_stream_has_its_own_page_id_in_its_hello(fake_browse, server):
    port = server()
    a = events(get(port, f"/api/browse/stream?ticket={TID}")[1])[0][1]["page"]
    b = events(get(port, f"/api/browse/stream?ticket={TID}")[1])[0][1]["page"]
    assert a and b and a != b and fake_browse["pages"] == [a, b]


def test_take_give_input_pass_on_to_the_broker(fake_browse, server):
    port = server()
    code, text = post(
        port,
        "/api/browse/take",
        {"ticket": TID, "generation": GEN, "page": "p1", "epoch": 3, "action": "take"},
    )
    assert code == 200 and json.loads(text) == {"state": "person", "epoch": 4, "mine": True, "sent": 2}
    events_ = [{"t": "down", "x": 1, "y": 2, "button": "left", "count": 1}]
    body = {
        "ticket": TID,
        "generation": GEN,
        "page": "p1",
        "epoch": 4,
        "w": 1280,
        "h": 800,
        "events": events_,
    }
    assert post(port, "/api/browse/input", body)[0] == 200
    assert (
        post(port, "/api/browse/give", {"ticket": TID, "generation": GEN, "page": "p1", "epoch": 4})[0] == 200
    )
    sent = fake_browse["person"]
    assert [c[1] for c in sent] == ["take", "input", "give"]
    assert sent[0][2] == [GEN, "p1", "3", "take"]
    assert json.loads(sent[1][2][3]) == {"w": 1280, "h": 800, "events": events_}
    code, text = post(
        port, "/api/browse/give", {"ticket": TID, "generation": GEN, "page": "not-mine", "epoch": 4}
    )
    assert code == 409 and "Another page" in text


@pytest.mark.parametrize("path", ["/api/browse/take", "/api/browse/give", "/api/browse/input"])
def test_take_over_routes_need_the_fence_the_session_and_json(fake_browse, server, path):
    port = server()
    body = {"ticket": TID, "generation": GEN, "page": "p1", "epoch": 1}
    if path.endswith("take"):
        body["action"] = "take"
    if path.endswith("input"):
        body.update(w=1280, h=800, events=[{"t": "move", "x": 1, "y": 1}])
    assert post(port, path, body, secret="wrong")[0] == 403  # the page secret: the person's own session
    assert post(port, path, body, origin="http://evil.example")[0] == 403
    assert post(port, path, body, extra={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert post(port, path, body, extra={"Content-Type": "text/plain"})[0] in (403, 415)
    # an add-on frame (its pass header, origin null) never reaches them
    assert post(port, path, body, origin="null", extra={"X-Orch-Frame": "a" * 30})[0] in (401, 403)
    assert post(port, path, {**body, "more": 1})[0] == 400
    assert post(port, path, {**body, "epoch": True})[0] == 400
    assert post(port, path, {**body, "epoch": -1})[0] == 400
    assert post(port, path, {**body, "generation": "../x"})[0] == 400
    assert post(port, path, {**body, "page": ""})[0] == 400
    assert post(port, path, {**body, "page": "p" * 65})[0] == 400
    assert post(port, path, body, raw=b"[1,")[0] == 400
    assert post(port, path, body, raw=b"{" + b" " * 40000 + b"}")[0] == 400  # too big
    assert fake_browse["person"] == []
    assert post(port, path, {**body, "ticket": "t_nothere"})[0] == 404


def test_input_and_take_values_are_checked(fake_browse, server):
    port = server()
    base = {"ticket": TID, "generation": GEN, "page": "p1", "epoch": 1}
    assert post(port, "/api/browse/take", {**base, "action": "steal"})[0] == 400
    for w, h, ev in ((0, 800, []), (1280, 5000, []), (1280, 800, {"t": "move"}), ("1280", 800, [])):
        assert post(port, "/api/browse/input", {**base, "w": w, "h": h, "events": ev})[0] == 400
    assert fake_browse["person"] == []


def test_no_add_on_frame_may_take_over():
    assert not framepass.ALL_ROOT_PATHS & {"/api/browse/take", "/api/browse/give", "/api/browse/input"}


def test_list_says_who_drives_and_what_the_helper_asks(fake_browse, ws, monkeypatch):
    monkeypatch.setattr(browseview, "_on", lambda root: True)
    _run(
        ws,
        TID,
        {"state": "ready", "generation": GEN, "control": {"state": "paused", "asking": "Please sign in"}},
    )
    row = browseview.listing(ws)["browsers"][0]
    assert row["control"] == "paused" and row["asking"] == "Please sign in"
    _run(ws, TID, {"state": "ready", "generation": GEN, "control": {"state": "helper"}})
    row = browseview.listing(ws)["browsers"][0]
    assert "control" not in row and "asking" not in row
