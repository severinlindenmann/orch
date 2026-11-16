"""G2: a Working ticket with no news for 6 h carries `quiet_since` (the core's one rule); nothing is stored."""

import json

from orch_dashboard import data


def _write(tmp_path, tid, status, at):
    folder = tmp_path / ".orch" / "tickets"
    folder.mkdir(parents=True, exist_ok=True)
    t = {
        "schema": "orch.ticket/1",
        "id": tid,
        "title": tid,
        "status": status,
        "created_at": at,
        "updated_at": at,
        "history": [{"at": at, "by": "agent:claude", "text": "x"}],
    }
    (folder / f"{tid}.json").write_text(json.dumps(t))


def test_quiet_since_on_a_quiet_working_ticket_only(tmp_path):
    _write(tmp_path, "old-active", "active", "2020-01-01T09:20:00Z")
    _write(tmp_path, "old-waiting", "waiting", "2020-01-01T09:20:00Z")
    _write(tmp_path, "fresh-active", "active", data.datetime.now(data.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    rows, _ = data.load_tickets(tmp_path, None)
    by = {t["id"]: t for t in rows}
    assert by["old-active"]["quiet_since"] == "2020-01-01T09:20:00Z"
    assert "quiet_since" not in by["old-waiting"] and "quiet_since" not in by["fresh-active"]
    stored = json.loads((tmp_path / ".orch" / "tickets" / "old-active.json").read_text())
    assert "quiet_since" not in stored, "computed, never stored"
