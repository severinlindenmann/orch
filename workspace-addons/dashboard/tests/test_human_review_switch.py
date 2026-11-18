"""ORCH-424: the Human review needed switch, set when a ticket is made and changed on the ticket page."""

import pytest

from orch_dashboard import actions


def test_new_ticket_is_on_unless_unticked():
    assert not any(
        "human-review" in x for x in actions.build_argv("ticket.new", {"title": "Spring campaign"})
    )
    on = actions.build_argv("ticket.new", {"title": "Spring campaign", "human_review": True})
    assert not any("human-review" in x for x in on)
    off = actions.build_argv("ticket.new", {"title": "Spring campaign", "human_review": False})
    assert "--human-review=no" in off


@pytest.mark.parametrize("bad", ["no", None, 0, ""])
def test_new_ticket_takes_only_true_or_false(bad):
    with pytest.raises(actions.BadRequest):
        actions.build_argv("ticket.new", {"title": "Spring campaign", "human_review": bad})
    assert actions.turns_review_off("ticket.new", {"title": "Spring campaign", "human_review": bad})


@pytest.mark.parametrize(("on", "flag"), [(True, "--human-review=yes"), (False, "--human-review=no")])
def test_switch_builds_the_edit(on, flag):
    argv = actions.build_argv("ticket.edit", {"ticket": "t_abcdef", "human_review": on, "if_revision": 3})
    assert flag in argv


def test_switch_takes_only_true_or_false():
    with pytest.raises(actions.BadRequest):
        actions.build_argv("ticket.edit", {"ticket": "t_abcdef", "human_review": "yes"})


def test_tickets_inside_an_epic_follow_its_choice(monkeypatch):
    log = []

    def fake_run_op(root, orch_bin, op, args, session=False):
        log.append(args)
        return 200, "", {"id": "t_epic001" if args.get("epic") else f"t_child{len(log):03d}"}

    monkeypatch.setattr(actions, "run_op", fake_run_op)
    args = {
        "title": "Epic",
        "epic": True,
        "human_review": False,
        "steps": [{"title": "One"}, {"title": "Two", "human_review": True}],
    }
    status, _, _ = actions.epic_new(None, "orch", args, True)
    assert status == 200
    assert [a.get("human_review") for a in log] == [False, False, True]


@pytest.mark.parametrize(
    ("op", "args"),
    [
        ("ticket.new", {"title": "Spring campaign", "human_review": False}),
        ("ticket.edit", {"ticket": "t_abcdef", "human_review": False}),
        ("ticket.new", {"title": "Spring campaign", "human_review": None}),
        ("ticket.new", {"title": "Epic", "epic": True, "steps": [{"title": "One", "human_review": False}]}),
    ],
)
def test_turning_it_off_needs_the_signed_in_person(op, args, monkeypatch):
    ran = []
    monkeypatch.setattr(actions, "_run", lambda *a, **k: ran.append(a))
    with pytest.raises(actions.NeedsPerson):
        actions.run_op(None, actions.SELF, op, args, session=False)
    assert ran == []  # refused before anything runs


def test_turning_it_on_stays_a_free_click():
    assert not actions.turns_review_off("ticket.edit", {"ticket": "t_abcdef", "human_review": True})
    assert not actions.turns_review_off("ticket.new", {"title": "Spring campaign"})
    assert actions.turns_review_off("ticket.edit", {"ticket": "t_abcdef", "human_review": False})
