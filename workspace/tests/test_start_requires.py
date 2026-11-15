"""start_requires (#681): a ticket made with a start gate starts (or is claimed) only once a PERSON gave that
answer to that question. Generic in core; Factory sets it on crew tickets so an agent cannot `orch run start`
a crew task before the person's Start."""

import pytest

from orch import runs, tickets
from orch.errors import Refused


def _order_with_start(proj):
    order = tickets.create(proj, "Booking page", "agent:factory")
    _, q = tickets.ask(proj, order["id"], "Start this run?", ["Start", "Not now"], None, "agent:factory")
    return order, q


def _set_answer(proj, tid, qid, answer, by):
    t = tickets.load(proj, tid)
    for q in t["questions"]:
        if q["id"] == qid:
            q.update(answer=answer, answered_by=by)
    tickets.save(proj, t)


def test_gate_is_set_at_creation_and_checked(proj):
    order, q = _order_with_start(proj)
    crew = tickets.create(
        proj,
        "Booking form",
        "agent:factory",
        parent=order["id"],
        start_requires=f"{order['id']}:{q['id']}=Start",
    )
    assert crew["start_requires"] == {"ticket": order["id"], "question": q["id"], "answer": "Start"}
    assert "starts only after a person answers" in tickets.start_blocked(proj, crew)
    _set_answer(proj, order["id"], q["id"], "Start", "agent:helper")  # an agent's answer never opens it
    assert tickets.start_blocked(proj, tickets.load(proj, crew["id"]))
    _set_answer(proj, order["id"], q["id"], "Not now", "human:anna")  # another answer neither
    assert tickets.start_blocked(proj, tickets.load(proj, crew["id"]))
    _set_answer(proj, order["id"], q["id"], "Start", "human:anna")
    assert tickets.start_blocked(proj, tickets.load(proj, crew["id"])) is None
    assert tickets.start_blocked(proj, order) is None  # no gate: nothing changes


def test_claim_and_start_refuse_while_the_gate_is_closed(proj):
    order, q = _order_with_start(proj)
    crew = tickets.create(
        proj, "Booking form", "agent:factory", start_requires=f"{order['id']}:{q['id']}=Start"
    )
    with pytest.raises(Refused, match="starts only after a person answers"):
        runs.claim(proj, crew["id"], "agent:helper", "generic")
    with pytest.raises(Refused, match="starts only after a person answers"):
        runs.start(proj, crew["id"], "agent:helper")
    assert runs.read(proj, crew["id"]) is None  # nothing was claimed


@pytest.mark.parametrize(
    "bad", ["t_x:q1=Start", "nope", "t_abcdef:q1=", "t_abcdef:1=Start", "t_abcdef:q1=a\nb"]
)
def test_gate_text_is_checked(proj, bad):
    with pytest.raises(Refused):
        tickets.create(proj, "X", "agent:factory", start_requires=bad)


def test_gate_must_name_an_existing_question(proj):
    order, _ = _order_with_start(proj)
    with pytest.raises(Refused, match="has no question q9"):
        tickets.create(proj, "X", "agent:factory", start_requires=f"{order['id']}:q9=Start")


def test_gate_cannot_be_patched_away(proj):
    order, q = _order_with_start(proj)
    crew = tickets.create(
        proj, "Booking form", "agent:factory", start_requires=f"{order['id']}:{q['id']}=Start"
    )
    assert "start_requires" not in tickets.PATCH_FIELDS
    with pytest.raises(Refused):
        tickets.patch(proj, crew["id"], crew["revision"], '{"start_requires": null}', "agent:helper")
    assert tickets.load(proj, crew["id"])["start_requires"]
