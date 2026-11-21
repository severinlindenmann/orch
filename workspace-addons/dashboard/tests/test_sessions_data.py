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
    assert set(shaped[0]) == {"id", "kind", "title", "open", "model"}  # ORCH-710: the model it starts on
    assert shaped[0]["model"] in ("sonnet", "opus") and all("model" not in r for r in shaped[1:])


def test_the_empty_helper_names_the_persons_model(ws):
    _ticket(ws, "t_empty001", session="empty", model={"name": "haiku", "by": "human:t"})
    assert load_sessions(ws)[0]["model"] == "haiku"


def test_no_sessions_without_tickets(ws):
    assert load_sessions(ws) == []


def test_the_page_guesses_the_same_model_as_orch_for_a_new_empty_helper():
    """ORCH-710: before the first Empty helper exists the New menu shows livebar.js LIVEBAR_EMPTY_MODEL."""
    import re
    from pathlib import Path

    from orch import modelpick

    js = Path(__file__).parents[1] / "src" / "orch_dashboard" / "web" / "pages" / "livebar.js"
    m = re.search(r"const LIVEBAR_EMPTY_MODEL = '(\w+)';", js.read_text(encoding="utf-8"))
    assert m and m.group(1) == modelpick.EMPTY_HELPER == modelpick.pick({"session": "empty"})[0]
