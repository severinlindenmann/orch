"""Sessions without a ticket in the dashboard's state (ORCH-364): read from the hidden ticket files, open by their run."""

import json

from orch_dashboard.data import load_sessions, shape_sessions


def _ticket(ws, tid, **flags):
    d = ws / ".orch" / "tickets"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{tid}.json").write_text(json.dumps({"id": tid, "title": "x", "status": "open", **flags}))


def test_sessions_are_read_from_the_hidden_tickets_in_menu_order(ws):
    _ticket(ws, "t_manager1", manager=True)
    _ticket(ws, "t_general1", general=True)
    _ticket(ws, "t_term0001", session="terminal", closed_at="2026-11-17T10:00:00Z")
    _ticket(ws, "t_empty001", session="empty")
    _ticket(ws, "t_plain001")
    _ticket(ws, "t_oddkind1", session="ticket")
    rows = load_sessions(ws)
    assert [(r["kind"], r["id"], r["title"]) for r in rows] == [
        ("empty", "t_empty001", "Empty helper"),
        ("chat", "t_general1", "Chat helper"),
        ("terminal", "t_term0001", "Plain terminal"),
        ("manager", "t_manager1", "Manager"),
    ]
    shaped = shape_sessions(rows, {"t_empty001": {"running": True}, "t_general1": {"running": False}})
    assert {r["kind"]: r["open"] for r in shaped} == {
        "empty": True,
        "chat": False,
        "terminal": False,
        "manager": False,
    }
    assert set(shaped[0]) == {"id", "kind", "title", "open"}


def test_no_sessions_without_tickets(ws):
    assert load_sessions(ws) == []
