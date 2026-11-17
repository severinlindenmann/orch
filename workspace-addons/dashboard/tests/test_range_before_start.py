"""ORCH-297: tickets nobody worked on yet get the range before Start; started ones never do."""

from pathlib import Path

from orch_dashboard import data


def test_range_only_on_tickets_not_started(monkeypatch, tmp_path):
    from orch import usage

    monkeypatch.setattr(
        usage, "estimate_range", lambda root: {"minutes": [20, 40], "cost": [2.0, 4.0], "n": 5}
    )
    items = [
        {"id": "a", "status": "open"},
        {"id": "b", "status": "ready", "range": "stale"},
        {"id": "c", "status": "active", "sessions": [{"id": "x"}]},
        {"id": "d", "status": "ready", "spend": {"seconds": 60, "cost": 0.1}},
        {"id": "e", "status": "done"},
    ]
    data.add_range(Path(tmp_path), items)
    words = "about 20-40 min · $2.00-$4.00"
    assert [i.get("range") for i in items] == [words, words, None, None, None]


def test_no_range_without_history(monkeypatch, tmp_path):
    from orch import usage

    monkeypatch.setattr(usage, "estimate_range", lambda root: None)
    items = [{"id": "a", "status": "open", "range": "old"}]
    data.add_range(Path(tmp_path), items)
    assert "range" not in items[0]
