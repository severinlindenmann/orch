import json
from pathlib import Path

import pytest

from orch_dashboard import actions, data


def test_ask_update_uses_copy_command():
    argv = actions.build_argv("copies.ask-update", {"ticket": "t_abcdef"})
    assert argv[:3] == ["copy", "ask-update", "t_abcdef"]
    with pytest.raises(actions.BadRequest):
        actions.build_argv("copies.ask-update", {"ticket": "../bad"})


def test_waiting_state_reaches_ticket_status_line(tmp_path, monkeypatch):
    example = Path(__file__).resolve().parents[3] / "contracts/examples/ticket/valid-bring-back.json"
    ticket = json.loads(example.read_text())
    monkeypatch.setattr(data, "run_orch", lambda *a: [ticket])
    rows, skipped = data.load_tickets(tmp_path, "orch")
    assert skipped == 0
    assert rows[0]["bring_back"] == {
        "state": "waiting",
        "reason": "your folder has changes in the same places",
    }
