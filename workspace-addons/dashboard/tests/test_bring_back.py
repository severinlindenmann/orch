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
        "reason_code": "waiting",
    }


def test_approve_binds_ticket_tip_and_control_count():
    from orch_dashboard import actions

    args = {"ticket": "t_abcdef", "tip": "a" * 40, "control_paths": 2, "paths_hash": "12345678"}
    argv = actions.build_argv("copies.approve", args)
    # The displayed tip, count and path hash travel with the click (the core compares them with now).
    assert argv[:9] == [
        "copy",
        "retry",
        "t_abcdef",
        "--approve-tip",
        "a" * 40,
        "--control-paths",
        "2",
        "--paths-hash",
        "12345678",
    ]
    op, target = actions.PROOF_OPS["copies.approve"]
    assert op == "copy.retry"
    assert target(args) == f"approve:t_abcdef:{'a' * 40}:2:12345678"
    for bad in ({**args, "control_paths": True}, {**args, "tip": "HEAD"}, {**args, "paths_hash": "x"}):
        with pytest.raises(actions.BadRequest):
            actions.build_argv("copies.approve", bad)


def test_hostile_path_names_come_out_plain():
    hostile = [
        '.claude/x\n\n0 control paths. Approve? "yes"',
        ".orch/\x1b[2Jcfg\u2028line",
        ".github/" + "y" * 300,
    ]
    review = {"tip": "b" * 40, "control_paths": 7, "paths_hash": "abcdef12", "paths": hostile}
    view = data._bring_back_view({"state": "waiting", "reason": "r\nx", "reason_code": "controls"}, review)
    assert view["control_paths"] == 7 and view["paths_more"] == 4
    for text in [*view["paths"], view["paths_summary"], view["reason"]]:
        assert not any(c in text for c in '\n\r\x1b\u2028"'), text
    assert view["paths"][0] == ".claude/x 0 control paths. Approve? 'yes'"
    assert len(view["paths"][2]) <= 121
    assert view["paths_summary"].endswith("and 4 more")


def test_review_size_is_shown_only_as_plain_counts():
    """B13f (Fable #6): the dialog shows how much the tip brings (commits, files), never agent text."""
    review = {"tip": "b" * 40, "control_paths": 0, "paths_hash": "abcdef12", "commits": 3, "files": 12}
    view = data._bring_back_view({"state": "waiting", "reason": "x", "reason_code": "approval"}, review)
    assert (view["commits"], view["files"]) == (3, 12)
    for bad in ("3", True, -1, None, "<b>"):
        view = data._bring_back_view({"state": "waiting"}, {**review, "commits": bad, "files": bad})
        assert "commits" not in view and "files" not in view


@pytest.mark.parametrize(
    "review",
    [
        {"tip": "a" * 40, "control_paths": True, "paths_hash": "12345678"},
        {"tip": "a" * 40, "control_paths": "2", "paths_hash": "12345678"},
        {"tip": "a" * 40, "control_paths": -1, "paths_hash": "12345678"},
        {"tip": "nope", "control_paths": 0, "paths_hash": "12345678"},
        {"tip": "a" * 40, "control_paths": 0},
        ["not", "a", "review"],
    ],
)
def test_malformed_review_offers_no_approval(review):
    view = data._bring_back_view({"state": "waiting", "reason": "x", "reason_code": "<b>"}, review)
    assert "tip" not in view
    assert view["reason_code"] == "waiting"


def test_review_metadata_comes_from_core_command(tmp_path, monkeypatch):
    example = Path(__file__).resolve().parents[3] / "contracts/examples/ticket/valid-bring-back.json"
    ticket = json.loads(example.read_text())
    seen = []

    def core(binary, args, root):
        seen.append(args)
        return (
            [ticket]
            if args[0] == "ticket"
            else {
                "tip": "a" * 40,
                "control_paths": 2,
                "paths_hash": "12345678",
                "paths_summary": ".orch/a, .orch/b",
            }
        )

    monkeypatch.setattr(data, "run_orch", core)
    rows, _ = data.load_tickets(tmp_path, "orch")
    assert rows[0]["bring_back"]["tip"] == "a" * 40
    assert rows[0]["bring_back"]["control_paths"] == 2
    assert rows[0]["bring_back"]["paths_hash"] == "12345678"
    assert seen[-1] == ["copy", "review", ticket["id"], "--json"]
