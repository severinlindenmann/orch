"""ORCH-424: the Human review needed switch on every ticket. On unless a person turns it off."""

import json

from orch import tickets


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


def texts(proj, tid):
    return [h["text"] for h in read(proj, tid)["history"]]


def _id(out):
    return json.loads(out)["id"]


def test_new_ticket_is_on_by_default(proj, run, validate):
    code, out, err = run("ticket", "new", "Spring campaign", "--json", "--by", "human:tester")
    assert code == 0, err
    t = read(proj, _id(out))
    validate(t)
    assert "human_review" not in t  # no field = on
    assert tickets.human_review(t) is True
    code, out, _ = run("ticket", "show", t["id"])
    assert "Human review needed: yes" in out


def test_older_ticket_without_field_counts_as_on():
    assert tickets.human_review({"id": "t_abcdef"}) is True
    assert tickets.human_review({"id": "t_abcdef", "human_review": False}) is False


def test_person_makes_a_ticket_with_it_off(proj, run, validate):
    code, out, err = run(
        "ticket", "new", "Spring campaign", "--human-review", "no", "--json", "--by", "human:tester"
    )
    assert code == 0, err
    t = read(proj, _id(out))
    validate(t)
    assert t["human_review"] is False
    assert texts(proj, t["id"])[-1] == "Human review needed: off"
    assert "Human review needed: no" in run("ticket", "show", t["id"])[1]


def test_person_turns_it_off_and_on_again(proj, run, validate, new_ticket):
    tid = new_ticket("Board lanes")
    code, _, err = run("ticket", "edit", tid, "--human-review", "no", "--by", "human:tester")
    assert code == 0, err
    validate(read(proj, tid))
    assert read(proj, tid)["human_review"] is False
    assert texts(proj, tid)[-1] == "Human review needed: off"
    rev = read(proj, tid)["revision"]
    assert run("ticket", "edit", tid, "--human-review", "no", "--by", "human:tester")[0] == 0
    assert read(proj, tid)["revision"] == rev  # no change: no write, no extra history line
    code, _, err = run("ticket", "edit", tid, "--human-review", "yes", "--by", "human:tester")
    assert code == 0, err
    assert "human_review" not in read(proj, tid)
    assert texts(proj, tid)[-1] == "Human review needed: on"


def test_an_agent_cannot_turn_it_off(proj, run, new_ticket, monkeypatch):
    tid = new_ticket("Board lanes")
    code, _, err = run("ticket", "edit", tid, "--human-review", "no", "--by", "agent:claude")
    assert code == 2 and "Only a person" in err
    assert "human_review" not in read(proj, tid)
    code, _, err = run("ticket", "new", "Sneaky", "--human-review", "no", "--by", "agent:claude")
    assert code == 2 and "Only a person" in err
    monkeypatch.setenv("ORCH_AGENT", "claude")  # an agent in the environment, whatever --by says
    code, _, err = run("ticket", "edit", tid, "--human-review", "no", "--by", "human:tester")
    assert code == 2 and "Only a person" in err


def test_an_agent_may_turn_it_back_on(proj, run, new_ticket):
    tid = new_ticket("Board lanes")
    assert run("ticket", "edit", tid, "--human-review", "no", "--by", "human:tester")[0] == 0
    code, _, err = run("ticket", "edit", tid, "--human-review", "yes", "--by", "agent:claude")
    assert code == 0, err
    assert tickets.human_review(read(proj, tid)) is True


def test_not_a_plain_field(proj, new_ticket):
    import pytest

    tid = new_ticket("Board lanes")
    with pytest.raises(tickets.Refused):
        tickets.edit(proj, tid, None, "human:tester", {"human_review": "no"})


def test_from_input_keeps_the_choice(proj):
    by = "agent:relay from ph_x"
    t = tickets.create_from_input(proj, "Check the spring numbers", by, human_review=False)
    assert t["human_review"] is False
    t = tickets.create_from_input(proj, "Check the autumn numbers", "agent:relay from ph_x")
    assert tickets.human_review(t) is True
