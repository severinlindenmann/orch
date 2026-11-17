"""ORCH-185: an epic and its tickets are made by ONE request, checked whole before anything is made."""

import pytest

from orch_dashboard import actions


@pytest.fixture
def made(monkeypatch):
    log = []

    def fake_run_op(root, orch_bin, op, args, session=False):
        log.append(args)
        if args.get("parent") == "t_epic001" and args.get("title") == "Breaks":
            return 422, "That ticket is not allowed", None
        return 200, "", {"id": "t_epic001" if args.get("epic") else f"t_child{len(log):03d}"}

    monkeypatch.setattr(actions, "run_op", fake_run_op)
    return log


def epic(**more):
    return {"title": "Epic", "epic": True, "steps": [{"title": "One"}, {"title": "Two"}], **more}


def test_epic_and_its_tickets_in_one_answer(made):
    status, text, out = actions.epic_new(None, "orch", epic(), True)
    assert status == 200 and text == ""
    assert [a.get("parent") for a in made] == [None, "t_epic001", "t_epic001"]
    assert "steps" not in made[0]  # the epic itself is made without the list
    assert [m["index"] for m in out["steps"]["made"]] == [0, 1] and out["steps"]["failed"] == []


def test_a_bad_ticket_stops_everything_before_anything_is_made(made):
    args = epic(steps=[{"title": "Fine"}, {"title": "x", "files": [{"name": "a.exe", "text": "x"}]}])
    with pytest.raises(actions.BadRequest, match="Ticket 2"):
        actions.epic_new(None, "orch", args, True)
    assert made == []


def test_a_ticket_that_fails_is_named_and_the_others_are_kept(made):
    status, _, out = actions.epic_new(
        None, "orch", epic(steps=[{"title": "Breaks"}, {"title": "Fine"}]), True
    )
    assert status == 200
    assert out["steps"]["failed"] == [{"index": 0, "message": "That ticket is not allowed"}]
    assert [m["index"] for m in out["steps"]["made"]] == [1]


@pytest.mark.parametrize(
    "bad",
    [
        {"steps": []},
        {"steps": [{"title": "T", "parent": "t_other1"}]},
        {"steps": [{"title": "T"}] * 51},
        {"steps": ["not a ticket"]},
        {"epic": False},
    ],
)
def test_the_list_is_checked(made, bad):
    with pytest.raises(actions.BadRequest):
        actions.epic_new(None, "orch", epic(**bad), True)
    assert made == []
