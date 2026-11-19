"""ORCH-517: an idle Home tab on a busy workspace sent about 20 MB a minute (the whole state on every change, the same
pictures again on every redraw). A changed state now sends only what changed; pictures are revalidated by content
hash. The budget test replays an idle minute and fails when it costs more than 200 KB."""

import copy
import gzip
import http.client
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from orch_dashboard import state_delta
from orch_dashboard.data import state_rev
from orch_dashboard.state_cache import StateCache

WEB = Path(__file__).resolve().parents[1] / "src" / "orch_dashboard" / "web"
HARNESS = Path(__file__).parent / "helpers_harness.js"
node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

IDLE_MINUTE_BUDGET = 200_000  # bytes an idle Home tab may cost a minute (the owner's target)
POLLS_A_MINUTE = 12  # the report: /api/state 12 times in 60 s
PICTURES_A_POLL = 3  # the report: /api/file 36 times in 60 s


def _ticket(i: int, lines: int = 40) -> dict:
    return {
        "id": f"t_{i:06d}",
        "key": f"ORCH-{i}",
        "title": f"Ticket number {i} about the dashboard and its pages",
        "status": "done" if i % 5 else "active",
        "updated_at": f"2026-11-18T10:{i % 60:02d}:00Z",
        "checklist": [
            {"id": f"c{n}", "text": f"Step {n} of ticket {i}", "done": n % 2 == 0} for n in range(6)
        ],
        "history": [
            {
                "at": f"2026-11-{1 + n % 18:02d}T{n % 24:02d}:{i % 60:02d}:{n % 60:02d}Z",
                "who": "agent:claude",
                "text": f"Line {n} of ticket {i}: checked the page, ran the tests (exit 0), {i * 7919 + n * 104729} bytes",
            }
            for n in range(lines)
        ],
    }


def _state(n: int, lines: int = 40) -> dict:
    s = {
        "workspace": "Busy",
        "now": "2026-11-18T12:00:00Z",
        "tickets": [_ticket(i, lines) for i in range(n)],
        "runs": [],
        "needs": [],
        "review": {"cards": [], "answered": [], "accepted": []},
        "auto_update_note": None,
        "start_line": None,
    }
    s["rev"] = state_rev(s)
    return s


def _work(state: dict, step: int, busy: int = 3) -> dict:
    """A few seconds of helpers working: `busy` tickets get a history line, the runs change."""
    s = copy.deepcopy(state)
    for j in range(busy):
        t = s["tickets"][(step * busy + j) * 7 % len(s["tickets"])]
        t["history"].append(
            {"at": f"2026-11-18T12:00:{step:02d}Z", "who": "agent:claude", "text": f"step {step}"}
        )
        t["updated_at"] = f"2026-11-18T12:00:{step:02d}Z"
    s["runs"] = [{"ticket": "t_000000", "beat": step}]
    s.pop("rev")
    s["rev"] = state_rev(s)
    return s


def _apply(held: dict, d: dict) -> dict:
    out = subprocess.run(
        [
            "node",
            str(HARNESS),
            str(WEB / "helpers.js"),
            json.dumps({"fn": "applyStateDelta", "args": [held, d]}),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


@node
def test_a_delta_applied_by_the_page_gives_the_new_state():
    a = _state(8, lines=3)
    b = copy.deepcopy(a)
    b["tickets"][2]["status"] = "review"  # a field changed
    b["tickets"][4]["history"].append(
        {"at": "2026-11-18T12:00:01Z", "who": "x", "text": "new"}
    )  # a line added
    b["tickets"][6]["history"] = b["tickets"][6]["history"][1:]  # the oldest line dropped: sent whole
    del b["tickets"][3]["checklist"]  # a field gone
    b["tickets"].append(_ticket(99, lines=2))  # a new ticket
    del b["tickets"][5]  # a ticket gone
    b["tickets"][0], b["tickets"][1] = b["tickets"][1], b["tickets"][0]  # the order changed
    b["needs"] = [{"id": "n1"}]  # a top-level key changed
    b["build"] = {"v": 1}  # a new top-level key
    b["now"] = "2026-11-18T12:00:05Z"
    b.pop("rev")
    b["rev"] = state_rev(b)
    d = state_delta.delta(state_delta.fingerprint(a), state_delta.fingerprint(b), b, a["rev"])
    held = {**a, "renew_result": {"ok": True}}  # a click's answer added its own key: gone after the delta
    assert _apply(held, d) == b
    rows = {r["id"]: r for r in d["upsert"]}
    assert rows["t_000004"]["~append"]["history"] == [b["tickets"][4]["history"][-1]]
    assert "~append" not in rows["t_000006"] and len(rows["t_000006"]["history"]) == 2
    assert len(json.dumps(d)) < len(json.dumps(b)) / 2


@node
def test_a_delta_for_another_revision_is_refused_by_the_page():
    a, b = _state(3, lines=1), _work(_state(3, lines=1), 1)
    d = state_delta.delta(state_delta.fingerprint(a), state_delta.fingerprint(b), b, a["rev"])
    assert _apply({**a, "rev": "something-else"}, d) is None


def test_tickets_without_distinct_ids_get_the_whole_state():
    s = _state(2, lines=1)
    s["tickets"][1]["id"] = s["tickets"][0]["id"]
    assert state_delta.fingerprint(s) is None


def _get(port, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request("GET", path, headers={"Host": f"127.0.0.1:{port}", **(headers or {})})
    r = c.getresponse()
    body = r.read()
    head = sum(len(k) + len(v) + 4 for k, v in r.getheaders()) + 17  # status line and headers
    return r.status, body, dict(r.getheaders()), len(body) + head


@pytest.fixture
def busy_server(ws, act_orch):
    from orch_dashboard.server import make_server

    srv = make_server(ws, 0, orch_bin=str(act_orch))
    cache = StateCache(ws, None)
    cache.get = lambda: cache._served()  # the test decides when the state changes
    srv.state_cache = cache
    pic = ws / ".orch" / "tickets" / "t_other000x" / "artifacts"
    pic.mkdir(parents=True)
    (pic / "shot.png").write_bytes(b"\x89PNG" + bytes(range(256)) * 400)  # a 100 KB picture
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], cache
    srv.shutdown()
    srv.server_close()


def test_an_idle_minute_on_a_busy_workspace_costs_under_200_kb(busy_server):
    port, cache = busy_server
    state = _state(500, lines=80)
    cache._store(state, None)
    gz = {"Accept-Encoding": "gzip"}
    code, body, h, _ = _get(port, "/api/state", gz)  # the page opens: the whole state once (not counted)
    assert code == 200 and len(gzip.decompress(body)) > 4_000_000  # a realistic busy workspace
    held = json.loads(gzip.decompress(body))
    pic = "/api/file?t=t_other000x&k=artifacts&n=shot.png"
    _, _, ph, _ = _get(port, pic)
    tag = ph["ETag"]
    spent = 0
    for step in range(POLLS_A_MINUTE):
        state = _work(state, step)
        cache._store(state, None)
        code, body, h, cost = _get(port, "/api/state?have=" + held["rev"], gz)
        assert code == 200
        spent += cost
        d = json.loads(gzip.decompress(body) if h.get("Content-Encoding") == "gzip" else body)
        assert d.get("delta") is True and d["set"]["rev"] == state["rev"]
        held = {**held, **d["set"]}  # the page's merge is checked in the tests above; here only the revision
        for _ in range(PICTURES_A_POLL):  # Home draws its pictures again: the browser asks "still this?"
            code, body, _, cost = _get(port, pic, {"If-None-Match": tag})
            assert code == 304 and body == b""
            spent += cost
    assert spent < IDLE_MINUTE_BUDGET, f"an idle minute cost {spent} bytes"


def test_a_changed_picture_is_sent_again(busy_server, ws):
    port, _ = busy_server
    pic = "/api/file?t=t_other000x&k=artifacts&n=shot.png"
    _, _, h, _ = _get(port, pic)
    assert h["Cache-Control"] == "private, no-cache" and h["ETag"]
    (ws / ".orch" / "tickets" / "t_other000x" / "artifacts" / "shot.png").write_bytes(b"\x89PNG new")
    code, body, h2, _ = _get(port, pic, {"If-None-Match": h["ETag"]})
    assert code == 200 and body == b"\x89PNG new" and h2["ETag"] != h["ETag"]


def test_an_unknown_revision_still_gets_the_whole_state(busy_server):
    port, cache = busy_server
    cache._store(_state(3, lines=1), None)
    _, body, _, _ = _get(port, "/api/state?have=deadbeef0000")
    d = json.loads(body)
    assert "delta" not in d and len(d["tickets"]) == 3
