"""ORCH-522: the live page's state holds open and recently finished tickets as short rows, plus counts of every
ticket; a whole ticket (a finished one too) loads alone from GET /api/ticket/<id>."""

import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

from orch_dashboard import data

NOW = datetime.now(UTC)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    assert s["counts"] == {"total": 5, "by_status": {"active": 1, "open": 1, "dropped": 3}}
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
    assert _get(server + "/api/ticket/t_nothere1")[0] == 404
    assert _get(server + "/api/ticket/..%2F..%2Fetc")[0] in (403, 404)


def test_review_answered_is_capped_newest_first(monkeypatch):
    rows = [{"id": f"q{i}", "at": f"2026-11-{i:02d}"} for i in range(1, 400)]

    def fake(orch_bin, args, root, timeout=5.0):
        return rows if "--answered" in args else None

    monkeypatch.setattr(data, "run_orch", fake)
    got = data.load_review(None, "x")["answered"]
    assert len(got) == data.ANSWERED_MAX and got[0]["id"] == "q1"
