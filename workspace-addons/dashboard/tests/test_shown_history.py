"""The dashboard shows person fields through the core's one rule (orch.history.shown_ticket); without the core it
fails closed (every person field is the sync role)."""

import json
import sys

from orch_dashboard import data, mobile

LINE = {"at": "2026-11-09T09:00:00Z", "by": "human:alice", "via": "dashboard", "text": "Looks good"}


def _ticket(tid="t_synced01"):
    return {
        "schema": "orch.ticket/1", "id": tid, "title": "Synced", "status": "active",
        "created_at": "2026-11-09T08:00:00Z", "updated_at": "2026-11-09T09:00:00Z",
        "checklist": [{"id": "c1", "text": "s", "done": True,
                       "evidence": [{"type": "note", "ref": "x", "by": "human:alice"}]}],
        "refs": [], "questions": [], "history": [dict(LINE)],
    }


def _workspace(tmp_path, synced: bool):
    (tmp_path / ".orch" / "tickets").mkdir(parents=True)
    if synced:
        (tmp_path / ".orch" / ".git").mkdir()
    t = _ticket()
    (tmp_path / ".orch" / "tickets" / f"{t['id']}.json").write_text(json.dumps(t))
    return tmp_path


def test_without_the_core_every_person_field_is_demoted(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "orch.history", None)  # import raises ImportError
    shown = data.shown(tmp_path, _ticket())
    assert shown["history"][0]["by"] == data.SYNC_BY
    assert shown["history"][0]["text"].startswith(data.SYNCED_UNVERIFIED)
    assert shown["checklist"][0]["evidence"][0]["by"] == data.SYNC_BY
    assert not mobile._person("human:alice")


def test_a_synced_workspace_read_from_files_shows_the_sync_role(tmp_path):
    root = _workspace(tmp_path, synced=True)
    tickets, _ = data.load_tickets(root, None)
    t = tickets[0]
    assert t["history"][0]["by"] == data.SYNC_BY
    assert t["checklist"][0]["evidence"][0]["by"] == data.SYNC_BY
    raw = json.loads((root / ".orch" / "tickets" / "t_synced01.json").read_text())
    assert raw["history"][0]["by"] == "human:alice"  # never rewritten


def test_a_sync_free_workspace_is_shown_as_written(tmp_path):
    root = _workspace(tmp_path, synced=False)
    tickets, _ = data.load_tickets(root, None)
    assert tickets[0]["history"][0]["by"] == "human:alice"
    assert tickets[0]["checklist"][0]["evidence"][0]["by"] == "human:alice"
