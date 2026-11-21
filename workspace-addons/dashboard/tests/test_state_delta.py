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


def _run(i: int, step: int) -> dict:
    """A helper's run row as `orch run status` gives it: its ages tick every poll (ORCH-524)."""
    return {
        "running": True,
        "state": "idle",
        "agent": "claude",
        "claim": {"mode": "live", "session": f"s{i:04d}", "live": {"since": "2026-11-18T10:00:00Z"}},
        "age_seconds": 4000 + step * 5,
        "last_activity": {"at": "2026-11-18T10:00:00Z", "text": "Claude started", "seconds": 7000 + step * 5},
        "screen": "waiting at the prompt " * 8,
    }


def _state(n: int, lines: int = 40) -> dict:
    s = {
        "workspace": "Busy",
        "now": "2026-11-18T12:00:00Z",
        "tickets": [_ticket(i, lines) for i in range(n)],
        "runs": {f"t_{i:06d}": _run(i, 0) for i in range(0, min(n, 250), 5)},  # 50 helpers at most
        "settings": {"diag": {"notes": {"bytes": 1000, "files": 3}}, "agents": [{"name": "claude"}] * 20},
        "needs": [],
        "review": {"cards": [], "answered": [], "accepted": []},
        "auto_update_note": None,
        "start_line": None,
    }
    s["rev"] = state_rev(s)
    return s


def _work(state: dict, step: int, busy: int = 3) -> dict:
    """A few seconds of helpers working: `busy` tickets get a history line and move to the top (the newest
    change first, as the real state is ordered), every run's age ticks, the diagnostics notes grow."""
    s = copy.deepcopy(state)
    moved = []
    for j in range(busy):
        t = s["tickets"][(step * busy + j) * 7 % len(s["tickets"])]
        t["history"].append(
            {"at": f"2026-11-18T12:00:{step:02d}Z", "who": "agent:claude", "text": f"step {step}"}
        )
        t["updated_at"] = f"2026-11-18T12:00:{step:02d}Z"
        moved.append(t["id"])
    s["tickets"] = [t for t in s["tickets"] if t["id"] in moved] + [
        t for t in s["tickets"] if t["id"] not in moved
    ]
    for run in s["runs"].values():
        run["age_seconds"] += 5
        run["last_activity"]["seconds"] += 5
    s["settings"]["diag"]["notes"]["bytes"] += 7000
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
    b["runs"]["t_000000"]["age_seconds"] += 5  # a field of an entry of a top-level object
    b["runs"]["t_000007"] = _run(7, 1)  # a new entry
    del b["runs"]["t_000005"]  # an entry gone
    del b["runs"]["t_000000"]["screen"]  # a field gone: the entry is sent whole
    b["settings"]["agents"] = []  # an entry that is not an object
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
    assert "runs" not in d["set"] and set(d["patch"]["runs"]) == {"set", "drop"}


def test_a_ticking_run_age_sends_only_that_field():
    """ORCH-524: at 10,000 tickets with 70 helpers every poll sent all run rows (49 KB) because each row's age ticks."""
    a = _state(250, lines=1)
    b = _work(a, 1)
    d = state_delta.delta(state_delta.fingerprint(a), state_delta.fingerprint(b), b, a["rev"])
    assert "runs" not in d["set"] and "settings" not in d["set"]
    row = d["patch"]["runs"]["fields"]["t_000005"]
    assert row == {"age_seconds": 4005, "last_activity": b["runs"]["t_000005"]["last_activity"]}
    assert d["patch"]["settings"] == {"fields": {"diag": {"notes": {"bytes": 8000, "files": 3}}}}


@node
def test_a_delta_for_another_revision_is_refused_by_the_page():
    a, b = _state(3, lines=1), _work(_state(3, lines=1), 1)
    d = state_delta.delta(state_delta.fingerprint(a), state_delta.fingerprint(b), b, a["rev"])
    assert _apply({**a, "rev": "something-else"}, d) is None


def _to_top(state: dict, picks: list[int]) -> dict:
    """What the real state does when helpers write: the changed tickets move to the top of the order."""
    s = copy.deepcopy(state)
    moved = [s["tickets"][i] for i in picks]
    s["tickets"] = moved + [t for i, t in enumerate(s["tickets"]) if i not in set(picks)]
    s.pop("rev")
    s["rev"] = state_rev(s)
    return s


def test_tickets_that_move_to_the_top_cost_a_few_order_pieces_not_every_id():
    """ORCH-524: at 10,000 tickets every changed poll sent the whole order (10,000 ids, about 60 KB packed), because a
    changed ticket moves to the top. Now the order comes as pieces of the order the page holds."""
    a = _state(10_000, lines=0)
    b = _to_top(a, [5000, 17, 9998])
    d = state_delta.delta(state_delta.fingerprint(a), state_delta.fingerprint(b), b, a["rev"])
    assert d["order"] == ["t_005000", "t_000017", "t_009998", [0, 17], [18, 4982], [5001, 4997], "t_009999"]
    assert len(json.dumps(d["order"])) < 200


@node
def test_the_page_builds_the_order_back_from_its_pieces():
    a = _state(40, lines=1)
    b = _to_top(a, [30, 2])
    b["tickets"].insert(5, _ticket(77, lines=1))  # a new ticket in the middle
    del b["tickets"][20]  # a ticket gone
    b.pop("rev")
    b["rev"] = state_rev(b)
    d = state_delta.delta(state_delta.fingerprint(a), state_delta.fingerprint(b), b, a["rev"])
    assert any(isinstance(p, list) for p in d["order"])
    assert _apply(a, d) == b
    bad = {**d, "order": [[0, 999]]}  # a piece outside what the page holds: the page asks for the whole state
    assert _apply(a, bad) is None


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


def test_a_picture_link_with_its_version_is_kept_without_asking_again(busy_server):
    """ORCH-524: pictures are fetched once, then served from the browser's cache. The page puts the file's time and
    size in the link (`v`); such a link may be kept a year, so a redraw or a reload does not ask the server at all,
    and a new version of the file gets a new link. Without `v`, or for a download, the browser keeps asking."""
    from orch_dashboard.server import FILE_KEPT

    port, _ = busy_server
    pic = "/api/file?t=t_other000x&k=artifacts&n=shot.png"
    code, body, h, _ = _get(port, pic + "&v=2026-11-18T10%3A00%3A00Z~102404")
    assert code == 200 and len(body) > 100_000
    assert h["Cache-Control"] == FILE_KEPT == "private, max-age=31536000, immutable" and h["ETag"]
    code, body, h2, _ = _get(port, pic + "&v=2026-11-18T10%3A00%3A00Z~102404", {"If-None-Match": h["ETag"]})
    assert code == 304 and body == b"" and h2["Cache-Control"] == FILE_KEPT  # a 304 keeps it kept
    for plain in (pic, pic + "&v=", pic + "&v=" + "x" * 65, pic + "&v=1~2&dl=1"):
        assert _get(port, plain)[2]["Cache-Control"] == "private, no-cache", plain


def test_an_unknown_revision_still_gets_the_whole_state(busy_server):
    port, cache = busy_server
    cache._store(_state(3, lines=1), None)
    _, body, _, _ = _get(port, "/api/state?have=deadbeef0000")
    d = json.loads(body)
    assert "delta" not in d and len(d["tickets"]) == 3
