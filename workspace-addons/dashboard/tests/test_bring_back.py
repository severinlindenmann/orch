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


def test_approve_binds_ticket_tip_and_control_count():
    from orch_dashboard import actions

    args = {"ticket": "t_abcdef", "tip": "a" * 40, "control_paths": 2}
    argv = actions.build_argv("copies.approve", args)
    assert argv[:3] == ["copy", "approve", "t_abcdef"]
    op, target = actions.PROOF_OPS["copies.approve"]
    assert op == "copy.retry"
    assert target(args) == f"approve:t_abcdef:{'a' * 40}:2"


def test_review_metadata_comes_from_core_command(tmp_path, monkeypatch):
    example = Path(__file__).resolve().parents[3] / "contracts/examples/ticket/valid-bring-back.json"
    ticket = json.loads(example.read_text())
    seen = []

    def core(binary, args, root):
        seen.append(args)
        return [ticket] if args[0] == "ticket" else {"tip": "a" * 40, "control_paths": 2}

    monkeypatch.setattr(data, "run_orch", core)
    rows, _ = data.load_tickets(tmp_path, "orch")
    assert rows[0]["bring_back"]["tip"] == "a" * 40
    assert rows[0]["bring_back"]["control_paths"] == 2
    assert seen[-1] == ["copy", "review", ticket["id"], "--json"]
