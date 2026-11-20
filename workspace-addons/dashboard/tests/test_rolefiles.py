"""ORCH-827: a repeating ticket's runs for the role page (GET /api/role/<ticket>) and the file viewer's first opens."""

import json

from orch_dashboard import rolefiles

RUN = {
    "run": 7,
    "at": "2026-11-20T11:01:00Z",
    "took": 420,
    "outcome": "not-finished",
    "words": "not finished",
    "tone": "warn",
    "text": "Tests   stopped\nearly",
    "checked": ["Tests: 41 passed", 5],
    "cost": 1.11,
    "files": [
        {"name": "log.txt", "state": "unopened"},
        {"name": "../x", "state": "opened"},
        {"name": "a.png", "state": "?"},
    ],
    "findings": [{"title": "Usage page", "ticket": "t_abcdef"}, {"title": "bad", "ticket": "../t"}],
}


def test_keeps_only_checked_fields(monkeypatch, tmp_path):
    seen = {}

    def fake(orch_bin, args, root, timeout=5.0):
        seen["args"] = args
        return {
            "runs": [RUN, {**RUN, "run": "8"}, {**RUN, "outcome": "boom"}, "x"],
            "totals": {
                "runs": 7,
                "findings": "3",
                "files": {"unopened": 1, "unknown": True},
                "by_outcome": {"skipped": 2, "zzz": 1},
                "cost": -1,
            },
            "schedule": {
                "repeats": "Every 6 hours",
                "next": ["2026-11-20T17:00:00Z", 5],
                "quick": "maybe",
                "time_limit": 75,
                "paused": "no",
            },
        }

    monkeypatch.setattr(rolefiles, "run_orch", fake)
    d = rolefiles.listing(tmp_path, "orch", "t_role01")
    assert seen["args"] == ["automation", "role", "t_role01", "--json"]
    assert d["available"] is True and len(d["runs"]) == 1
    r = d["runs"][0]
    assert r["text"] == "Tests stopped early" and r["checked"] == ["Tests: 41 passed"]
    assert r["files"] == [{"name": "log.txt", "state": "unopened"}, {"name": "a.png", "state": "unknown"}]
    assert r["findings"] == [{"title": "Usage page", "ticket": "t_abcdef"}]
    t = d["totals"]
    assert t["runs"] == 7 and t["findings"] == 0 and t["by_outcome"] == {"skipped": 2}
    assert t["files"] == {"opened": 0, "unopened": 1, "unknown": 0} and t["cost"] is None
    sc = d["schedule"]
    assert (
        sc["next"] == ["2026-11-20T17:00:00Z"]
        and sc["quick"] == "none"
        and sc["time_limit"] == 75
        and sc["paused"] is False
    )


def test_unavailable_when_orch_cannot_answer(monkeypatch, tmp_path):
    monkeypatch.setattr(rolefiles, "run_orch", lambda *a, **k: None)
    assert rolefiles.listing(tmp_path, "orch", "t_role01")["available"] is False


def test_first_open_is_kept_and_only_for_real_ticket_files(tmp_path):
    art = tmp_path / ".orch" / "tickets" / "t_role01" / "artifacts"
    art.mkdir(parents=True)
    (art / "log.txt").write_text("x")
    assert rolefiles.note_open(tmp_path, "t_role01", "artifacts", "log.txt") is True
    p = tmp_path / ".orch" / "addons" / "dashboard" / "file-opens.json"
    first = json.loads(p.read_text())
    assert first["since"] and first["files"]["t_role01"]["log.txt"] == first["since"]
    assert rolefiles.note_open(tmp_path, "t_role01", "artifacts", "log.txt") is True
    assert json.loads(p.read_text()) == first  # the first open stays
    for args in (
        ("t_role01", "artifacts", "nope.txt"),
        ("t_role01", "secrets", "log.txt"),
        ("../x", "artifacts", "log.txt"),
        ("t_role01", "artifacts", "../log.txt"),
    ):
        assert rolefiles.note_open(tmp_path, *args) is False
