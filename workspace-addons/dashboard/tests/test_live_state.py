"""ORCH-522: the live page's state holds open and recently finished tickets as short rows, plus counts of every
ticket; a whole ticket (a finished one too) loads alone from GET /api/ticket/<id>."""

import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

from orch_dashboard import data


def _iso(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(root, tid, status, days_ago, history=3, parent=None, evidence=0):
    folder = root / ".orch" / "tickets"
    folder.mkdir(parents=True, exist_ok=True)
    at = _iso(days_ago)
    t = {
        "schema": "orch.ticket/1",
        "id": tid,
        "title": tid,
        "status": status,
        "created_at": at,
        "updated_at": at,
        "history": [{"at": at, "by": "agent:claude", "text": f"line {i}"} for i in range(history)],
        "checklist": [
            {
                "id": "c1",
                "text": "step",
                "done": True,
                "evidence": [{"type": "note", "ref": f"e{i}"} for i in range(evidence)],
            }
        ],
    }
    if parent:
        t["parent"] = parent
    (folder / f"{tid}.json").write_text(json.dumps(t))


def test_live_ids_keep_open_and_recent_finished_only():
    now = time.time()
    rows = [
        {"id": "t_open01", "status": "open", "updated_at": _iso(400)},
        {"id": "t_waits1", "status": "waiting", "updated_at": _iso(30)},
        {"id": "t_rev001", "status": "review", "updated_at": _iso(90)},
        {"id": "t_done01", "status": "done", "updated_at": _iso(1)},
        {"id": "t_drop01", "status": "dropped", "updated_at": _iso(2)},
        {"id": "t_old001", "status": "done", "updated_at": _iso(30)},
    ]
    assert set(data.live_ids(rows, now)) == {"t_open01", "t_waits1", "t_rev001", "t_done01", "t_drop01"}


def test_live_ids_cap_recent_finished_newest_first(monkeypatch):
    monkeypatch.setattr(data, "RECENT_MAX", 2)
    rows = [{"id": f"t_done0{i}", "status": "done", "updated_at": _iso(i / 10)} for i in range(5)]
    assert data.live_ids(rows) == ["t_done00", "t_done01"]


def test_counts_cover_every_ticket():
    rows = [{"status": "done"}, {"status": "done"}, {"status": "open"}, {"status": "nonsense"}]
    assert data.ticket_counts(rows) == {"total": 3, "by_status": {"done": 2, "open": 1}}


def test_slim_row_keeps_tail_done_line_and_chat_lines():
    hist = [{"at": "x", "text": f"line {i}"} for i in range(20)]
    hist[4] = {"at": "x", "kind": "done", "text": "Marked it finished"}
    hist[7] = {"at": "x", "text": "from the phone", "in_chat": True}
    t = {"id": "t_a", "history": hist, "checklist": [{"id": "c1", "evidence": [1, 2, 3, 4]}, {"id": "c2"}]}
    row = data.slim_row(t)
    assert row["slim"] is True
    assert [e["text"] for e in row["history"]] == [
        "Marked it finished",
        "from the phone",
        "line 17",
        "line 18",
        "line 19",
    ]
    assert row["history_more"] == 15
    assert row["checklist"][0]["evidence"] == [3, 4] and row["checklist"][0]["evidence_more"] == 2
    assert row["checklist"][1] == {"id": "c2"}
    assert len(t["history"]) == 20 and len(t["checklist"][0]["evidence"]) == 4, (
        "the whole ticket stays untouched"
    )


def test_slim_row_cuts_page_only_parts_and_answer_cards():
    t = {
        "id": "t_a",
        "history": [],
        "refs": [{"url": "https://x"}],
        "art": {"x": {}},
        "questions": [
            {
                "id": "q1",
                "text": "Pick",
                "answer": "A",
                "answered_by": "human:pat",
                "asked_at": "2026-11-23T00:20:00Z",
                "answered_at": "2026-11-23T00:21:00Z",
                "card": {"big": 1},
                "digest": "d",
            },
            {"id": "q2", "text": "Open", "answer": None, "card": {"kind": "draft"}, "digest": "e"},
        ],
    }
    row = data.slim_row(t)
    assert row["slim"] is True and "refs" not in row and "art" not in row
    # ORCH-1658: the times stay, so the live layer's chat can place the question and its answer
    assert row["questions"][0] == {
        "id": "q1",
        "text": "Pick",
        "answer": "A",
        "answered_by": "human:pat",
        "asked_at": "2026-11-23T00:20:00Z",
        "answered_at": "2026-11-23T00:21:00Z",
    }
    assert row["questions"][1] == t["questions"][1], "an open question stays whole (Home answers it)"


def test_slim_row_leaves_a_short_ticket_whole():
    t = {"id": "t_a", "history": [{"text": "a"}], "checklist": []}
    assert data.slim_row(t) is t


def test_live_state_holds_open_and_recent_with_counts_and_parts(tmp_path):
    _write(tmp_path, "t_epic01", "active", 1)
    # standalone (no core) a Done file reads as Review, so the finished ones here are Won't do
    _write(
        tmp_path, "t_part01", "dropped", 60, parent="t_epic01"
    )  # old: not in the live state, still counted
    _write(tmp_path, "t_part02", "open", 0, parent="t_epic01", history=12, evidence=5)
    _write(tmp_path, "t_recent", "dropped", 2)
    _write(tmp_path, "t_oldone", "dropped", 90)
    s = data.load_state(tmp_path, with_settings=True)
    by = {t["id"]: t for t in s["tickets"]}
    assert set(by) == {"t_epic01", "t_part02", "t_recent"}
    assert s["ticket_counts"] == {"total": 5, "by_status": {"active": 1, "open": 1, "dropped": 3}}
    assert by["t_epic01"]["parts_total"] == 2 and by["t_epic01"]["children"] == ["t_part02", "t_part01"]
    assert by["t_part02"]["slim"] is True and len(by["t_part02"]["history"]) == data.HISTORY_TAIL
    assert "slim" not in by["t_recent"]


def test_snapshot_keeps_every_ticket_whole(tmp_path):
    _write(tmp_path, "t_open01", "open", 0, history=12)
    _write(tmp_path, "t_oldone", "dropped", 90)
    s = data.load_state(tmp_path, with_addons=False)
    by = {t["id"]: t for t in s["tickets"]}
    assert set(by) == {"t_open01", "t_oldone"} and "slim" not in by["t_open01"]
    assert len(by["t_open01"]["history"]) == 12


def test_read_ticket_gives_the_whole_finished_ticket(tmp_path):
    _write(tmp_path, "t_epic01", "active", 1)
    _write(tmp_path, "t_part01", "dropped", 60, parent="t_epic01", history=12)
    t = data.read_ticket(tmp_path, None, "t_part01")
    assert t["id"] == "t_part01" and len(t["history"]) == 12 and "slim" not in t
    assert data.read_ticket(tmp_path, None, "t_nothere") is None
    assert data.read_ticket(tmp_path, None, "../etc") is None


def _get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_http_ticket_route(server, ws):
    code, body = _get(server + "/api/ticket/t_7k3f9q")
    assert code == 200 and json.loads(body)["ticket"]["id"] == "t_7k3f9q"
    assert _get(server + "/api/ticket/t_nothere1") == (200, b'{"ticket":null}')  # no 404: no console error
    assert _get(server + "/api/ticket/..%2F..%2Fetc")[0] in (403, 404)


def test_review_answered_is_capped_newest_first(monkeypatch):
    rows = [{"id": f"q{i}", "at": f"2026-11-{i:02d}"} for i in range(1, 400)]

    def fake(orch_bin, args, root, timeout=5.0):
        return rows if "--answered" in args else None

    monkeypatch.setattr(data, "run_orch", fake)
    got = data.load_review(None, "x")["answered"]
    assert len(got) == data.ANSWERED_MAX and got[0]["id"] == "q1"


def test_index_rows_are_kept_until_a_ticket_file_changes(tmp_path, monkeypatch):
    """The ticket page, a key lookup and a click each asked the index for every row (a quarter second at 10,000
    tickets); the rows are kept while no ticket file changed."""
    import os
    import sys
    import types

    reads = []

    def rows(root, include_hidden=False):
        reads.append(1)
        return [
            {"id": f.stem, "status": json.loads(f.read_text())["status"]}
            for f in sorted((root / ".orch" / "tickets").glob("t_*.json"))
        ]

    mod = types.ModuleType("orch.ticketindex")
    mod.rows = rows
    monkeypatch.setitem(sys.modules, "orch.ticketindex", mod)
    import orch

    # `from orch import ticketindex` takes the package attribute once the real module was imported (another
    # import on the way in does that), not sys.modules
    monkeypatch.setattr(orch, "ticketindex", mod, raising=False)
    monkeypatch.setattr(data, "_ROWS", {})
    _write(tmp_path, "t_aaaaaa", "open", 0)
    first = data._index_rows(tmp_path)
    assert data._index_rows(tmp_path) == first and len(reads) == 1
    data._index_rows(tmp_path)[0]["status"] = "changed by a caller"  # a caller's list is its own copy
    assert data._index_rows(tmp_path) == first and first[0]["status"] == "open" and len(reads) == 1
    _write(tmp_path, "t_bbbbbb", "open", 0)  # a new ticket
    assert [r["id"] for r in data._index_rows(tmp_path)] == ["t_aaaaaa", "t_bbbbbb"] and len(reads) == 2
    p = tmp_path / ".orch" / "tickets" / "t_aaaaaa.json"
    t = json.loads(p.read_text())
    t["status"] = "done"
    p.write_text(json.dumps(t))
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    assert data._index_rows(tmp_path)[0]["status"] == "done" and len(reads) == 3


def test_read_ticket_takes_the_parts_from_its_live_row(tmp_path, monkeypatch):
    """A ticket in the live state: its row there already counts every part, so no ticket file scan per page."""
    _write(tmp_path, "t_epic01", "active", 1)
    _write(tmp_path, "t_part01", "dropped", 60, parent="t_epic01")
    live = {"id": "t_epic01", "children": ["t_part01", "t_gone01"], "parts_done": 1, "parts_total": 2}
    monkeypatch.setattr(data, "_index_rows", lambda root: (_ for _ in ()).throw(AssertionError("scanned")))
    t = data.read_ticket(tmp_path, None, "t_epic01", live)
    assert t["children"] == ["t_part01", "t_gone01"] and (t["parts_done"], t["parts_total"]) == (1, 2)
    t["children"].append("x")
    assert live["children"] == ["t_part01", "t_gone01"]  # the stored copy is not changed
    other = data.read_ticket(tmp_path, None, "t_part01", live)  # a row of another ticket is not used
    assert other["id"] == "t_part01" and other.get("parts_total", 0) == 0


def test_one_state_build_looks_at_the_ticket_files_once(tmp_path, monkeypatch):
    """ORCH-1621: the reads of one build (live rows, chat, review, needs ...) share one look at the ticket files
    (ticketindex.reuse); outside a build every read looks again."""
    from orch import ticketindex

    _write(tmp_path, "t_epic01", "active", 1)
    _write(tmp_path, "t_part01", "open", 0, parent="t_epic01")
    looks = []
    real = ticketindex._look
    monkeypatch.setattr(ticketindex, "_look", lambda root: looks.append(1) or real(root))
    data.load_state(tmp_path, with_settings=True)
    assert len(looks) == 1
    ticketindex.rows(tmp_path)
    assert len(looks) == 2


def test_the_ticket_list_warms_after_the_first_state(monkeypatch):
    """ORCH-1621: reading every ticket for the Tickets pages ran beside the first state build and both took
    turns; now it starts once the first state is stored."""
    import threading

    from orch_dashboard import server, ticketpages

    order, done = [], threading.Event()

    class Cache:
        def get(self):
            order.append("state")

    class Srv:
        state_cache, root = Cache(), "/w"

    monkeypatch.setattr(ticketpages, "warm", lambda root: (order.append("tickets"), done.set()))
    server.warm(Srv())
    assert done.wait(5)
    assert order == ["state", "tickets"]
