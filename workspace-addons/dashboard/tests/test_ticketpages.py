"""GET /api/tickets (ORCH-523): pages, filters and searches every ticket on the server."""

import json
import os
import urllib.request

from orch_dashboard import ticketpages

from .conftest import _ticket


def _write(root, t):
    p = root / ".orch" / "tickets" / f"{t['id']}.json"
    p.write_text(json.dumps(t))
    return p


def _many(root, n, status="done", **kw):
    for i in range(n):
        t = _ticket(
            f"t_bulk{i:05d}",
            f"Bulk ticket {i}",
            status,
            key=f"PIL-{1000 + i}",
            updated_at=f"2026-10-{1 + i % 28:02d}T10:00:{i % 60:02d}Z",
            waiting_on=None,
            checklist=[],
            questions=[],
            ext={},
            **kw,
        )
        _write(root, t)


def _page(root, **q):
    ticketpages._POOL.clear()
    return ticketpages.page(ticketpages.rows_for(root).rows(), {k: [str(v)] for k, v in q.items()})


def test_pages_through_finished_tickets(ws):
    _many(ws, 120)
    first = _page(ws, status="done", limit=50)
    assert first["total"] >= 120 and len(first["items"]) == 50 and first["next"] == 50
    rest = ticketpages.page(ticketpages.rows_for(ws).rows(), {"status": ["done"], "offset": ["100"]})
    ids = {t["id"] for t in first["items"]} | {t["id"] for t in rest["items"]}
    assert len(ids) == len(first["items"]) + len(rest["items"])  # no row twice
    assert rest["next"] is None
    assert all(t["status"] == "done" and t["slim"] for t in first["items"])


def test_limit_is_capped_and_bad_numbers_fall_back(ws):
    _many(ws, 260)
    assert len(_page(ws, status="done", limit=5000)["items"]) == ticketpages.MAX_PAGE
    assert len(_page(ws, status="done", limit="x", offset="-3")["items"]) == ticketpages.PAGE


def test_search_finds_words_in_note_and_tasks_and_ticket_numbers(ws):
    _many(ws, 30)
    _write(
        ws,
        _ticket(
            "t_needle0001",
            "Plain title",
            "done",
            key="PIL-77",
            note="x" * 900 + " the invoice for Pilatus",
            checklist=[{"id": "c1", "text": "Send the quarterly letter"}],
            questions=[],
            waiting_on=None,
            ext={},
        ),
    )
    hit = _page(ws, q="invoice")
    assert [t["id"] for t in hit["items"]] == ["t_needle0001"]
    assert len(hit["items"][0]["note"]) <= ticketpages.TEXT_CAP  # the row is slim, the search read it all
    assert [t["id"] for t in _page(ws, q="QUARTERLY")["items"]] == ["t_needle0001"]
    assert [t["id"] for t in _page(ws, q="77")["items"]] == ["t_needle0001"]  # exact number, not PIL-1077
    assert [t["id"] for t in _page(ws, q="pil77")["items"]] == ["t_needle0001"]
    assert _page(ws, q="nothing-like-this")["total"] == 0


def test_counts_per_status_and_default_leaves_dropped_out(ws):
    out = _page(ws)
    assert out["counts"].get("dropped") == 1
    assert all(t["status"] != "dropped" for t in out["items"])
    assert _page(ws, status="dropped")["total"] == 1


def test_owner_group_and_since_filters(ws):
    _write(
        ws,
        _ticket(
            "t_parent0001",
            "Parent",
            "active",
            owner="anna",
            waiting_on=None,
            checklist=[],
            questions=[],
            ext={},
        ),
    )
    _write(
        ws,
        _ticket(
            "t_child00001",
            "Child",
            "done",
            parent="t_parent0001",
            owner="ben",
            updated_at="2026-11-10T00:00:00Z",
            waiting_on=None,
            checklist=[],
            questions=[],
            ext={},
        ),
    )
    assert {t["id"] for t in _page(ws, group="t_parent0001")["items"]} == {"t_parent0001", "t_child00001"}
    assert [t["id"] for t in _page(ws, who="ben")["items"]] == ["t_child00001"]
    parent = next(t for t in _page(ws, who="anna")["items"])
    assert parent["children"] == ["t_child00001"] and parent["parts_done"] == 1
    assert "t_child00001" in {t["id"] for t in _page(ws, status="done", since="2026-11-01")["items"]}
    assert "t_child00001" not in {t["id"] for t in _page(ws, status="done", since="2026-11-11")["items"]}


def test_owner_filter_is_one_person_however_spelled(ws):
    """ORCH-1716: Severin, severin, the computer's login and "owner" are one person on the Person filter."""
    for i, owner in enumerate(["Severin", "severin", "lume", "owner", "Anna"]):
        _write(ws, _ticket(f"t_own{i:07d}", f"T{i}", "open", owner=owner, waiting_on=None, checklist=[], questions=[], ext={}))
    ticketpages._POOL.clear()
    rows = ticketpages.rows_for(ws).rows()
    mine = ticketpages.page(rows, {"who": ["severin"]}, "Severin", "lume")["items"]
    assert sorted(t["owner"] for t in mine) == ["Severin", "lume", "owner", "severin"]
    assert [t["owner"] for t in ticketpages.page(rows, {"who": ["anna"]}, "Severin", "lume")["items"]] == ["Anna"]
    # nobody picked a name: only the spelling counts
    assert sorted(t["owner"] for t in ticketpages.page(rows, {"who": ["Severin"]})["items"]) == ["Severin", "severin"]
    assert ticketpages.owner_key("human:lume", "Severin", "lume") == "severin"


def test_history_is_cut_and_done_time_kept(ws):
    hist = [{"at": "2026-11-01T10:00:00Z", "by": "agent:claude", "text": "Status: active -> done"}]
    hist += [
        {"at": f"2026-11-02T10:00:{i:02d}Z", "by": "agent:claude", "text": f"note {i}"} for i in range(20)
    ]
    _write(
        ws,
        _ticket(
            "t_longhist01",
            "Long history",
            "done",
            history=hist,
            waiting_on=None,
            checklist=[],
            questions=[],
            ext={},
        ),
    )
    row = next(t for t in _page(ws, q="long history")["items"])
    assert len(row["history"]) == ticketpages.HISTORY_KEEP and row["history_more"] == 16
    assert row["done_at"] == "2026-11-01T10:00:00Z"


def test_only_changed_files_are_read_again(ws, monkeypatch):
    _many(ws, 20)
    rows = ticketpages.TicketRows(ws)
    rows.rows()
    reads = []
    real = rows._read
    monkeypatch.setattr(rows, "_read", lambda p, s: reads.append(s) or real(p, s))
    p = _write(ws, {**json.loads((ws / ".orch/tickets/t_bulk00003.json").read_text()), "title": "Renamed"})
    os.utime(p, ns=(1, 1_000_000_000_000))
    rows.at = 0
    out = rows.rows()
    assert reads == ["t_bulk00003"]
    assert any(r["title"] == "Renamed" for r, _ in out)


def test_hidden_and_broken_files_are_left_out(ws):
    _write(
        ws,
        _ticket(
            "t_general001",
            "General",
            "active",
            general=True,
            waiting_on=None,
            checklist=[],
            questions=[],
            ext={},
        ),
    )
    ids = {t["id"] for t in _page(ws, limit=200)["items"]}
    assert "t_general001" not in ids and "t_broken0001" not in ids


def test_endpoint_answers_same_origin_only(server):
    req = urllib.request.Request(
        server + "/api/tickets?q=open&status=open,done", headers={"Sec-Fetch-Site": "same-origin"}
    )
    with urllib.request.urlopen(req) as r:
        out = json.loads(r.read())
    assert [t["title"] for t in out["items"]] == ["Open one"]
    bad = urllib.request.Request(server + "/api/tickets", headers={"Sec-Fetch-Site": "cross-site"})
    try:
        urllib.request.urlopen(bad)
        raise AssertionError("cross-site read answered")
    except urllib.error.HTTPError as e:
        assert e.code == 403
