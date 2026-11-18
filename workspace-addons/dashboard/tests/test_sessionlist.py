"""ORCH-363: the earlier sessions of a ticket for Focus's History tab (GET /api/sessions/<ticket>)."""

from orch_dashboard import sessionlist

GOOD = {
    "id": "0364ced3-ceac-463a-a68d-53a565d7e9df",
    "agent": "claude",
    "label": "Helper One",
    "host": "mac",
    "last_used": "2026-11-17T14:05:00Z",
    "title": "Fix   the\nlogin",
    "turns": 4,
    "readable": True,
    "current": False,
    "reopenable": True,
}


def test_keeps_only_the_shown_fields_and_drops_bad_rows(monkeypatch, tmp_path):
    rows = [
        GOOD,
        {**GOOD, "id": "../etc"},
        {**GOOD, "id": 5},
        "x",
        {**GOOD, "id": "s-2", "turns": True, "reopenable": "yes", "current": 1, "title": None},
    ]
    seen = {}

    def fake(orch_bin, args, root, timeout=5.0):
        seen["args"] = args
        return {"sessions": rows}

    monkeypatch.setattr(sessionlist, "run_orch", fake)
    d = sessionlist.listing(tmp_path, "orch", "t_abcdef")
    assert seen["args"] == ["run", "history", "t_abcdef", "--json"]
    assert d["available"] is True
    assert [r["id"] for r in d["sessions"]] == [GOOD["id"], "s-2"]
    first, second = d["sessions"]
    assert set(first) == {"id", "label", "last_used", "title", "turns", "current", "reopenable"}
    assert first["reopenable"] is True and first["turns"] == 4 and first["title"] == "Fix the login"
    assert second == {**second, "turns": 0, "reopenable": False, "current": False, "title": ""}


def test_unavailable_when_orch_cannot_list(monkeypatch, tmp_path):
    monkeypatch.setattr(sessionlist, "run_orch", lambda *a, **k: None)
    assert sessionlist.listing(tmp_path, "orch", "t_abcdef") == {"available": False, "sessions": []}
