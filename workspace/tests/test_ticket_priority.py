"""ORCH-813: a priority on every ticket (high, normal, low). Higher priority tickets start first when helpers
wait for a free slot."""

import json

import pytest

from orch import runs_live, tickets
from orch.errors import Refused


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


def _queue(proj, tid, priority="normal"):
    runs_live._queue_for_slot(proj, tid, "human:tester", "Start when a slot is free.", priority)


def test_no_field_means_normal(proj, new_ticket, validate):
    tid = new_ticket("Spring campaign")
    t = read(proj, tid)
    validate(t)
    assert "priority" not in t
    assert tickets.priority(t) == "normal"
    assert tickets.priority({"id": "t_abcdef", "priority": "urgent"}) == "normal"  # unknown value: normal


def test_edit_sets_shows_and_clears_it(proj, run, new_ticket, validate):
    tid = new_ticket("Spring campaign")
    code, out, err = run("ticket", "edit", tid, "--priority", "high", "--by", "human:tester")
    assert code == 0, err
    t = read(proj, tid)
    validate(t)
    assert t["priority"] == "high"
    assert "Priority: high" in [h["text"] for h in t["history"]]
    code, out, _ = run("ticket", "show", tid)
    assert "Priority: high" in out
    code, out, _ = run("ticket", "list")
    assert "high priority" in out
    code, out, err = run("ticket", "edit", tid, "--priority", "normal", "--by", "human:tester")
    assert code == 0, err
    t = read(proj, tid)
    validate(t)
    assert "priority" not in t  # normal is stored as no field
    code, out, _ = run("ticket", "show", tid)
    assert not any(line.startswith("Priority:") for line in out.splitlines())


def test_same_priority_again_writes_nothing(proj, new_ticket):
    tid = new_ticket("Spring campaign")
    tickets.set_priority(proj, tid, "low", "human:tester")
    rev = read(proj, tid)["revision"]
    tickets.set_priority(proj, tid, "low", "human:tester")
    assert read(proj, tid)["revision"] == rev


def test_same_priority_with_a_stale_revision_is_refused(proj, run, new_ticket):
    tid = new_ticket("Spring campaign")
    tickets.set_priority(proj, tid, "high", "human:tester")
    stale = read(proj, tid)["revision"]
    run("ticket", "edit", tid, "--note", "changed meanwhile", "--by", "human:tester")
    with pytest.raises(tickets.Conflict):
        tickets.set_priority(proj, tid, "high", "human:tester", if_revision=stale)
    code, _, _ = run(
        "ticket", "edit", tid, "--priority", "high", "--title", "Overwrite", "--if-revision", str(stale),
        "--by", "human:tester",
    )  # fmt: skip
    assert code != 0
    assert read(proj, tid)["title"] == "Spring campaign"


def test_unknown_priority_is_refused(proj, new_ticket):
    tid = new_ticket("Spring campaign")
    with pytest.raises(Refused):
        tickets.set_priority(proj, tid, "urgent", "human:tester")
    assert "priority" not in read(proj, tid)


def test_the_line_follows_the_ticket_priority(proj, new_ticket):
    a, b, c = (new_ticket(n) for n in "abc")
    _queue(proj, a)
    _queue(proj, b)
    _queue(proj, c)
    tickets.set_priority(proj, c, "high", "human:tester")
    tickets.set_priority(proj, a, "low", "human:tester")
    assert runs_live.waiting_line(proj) == [(c, "high"), (b, "normal"), (a, "low")]


def test_changing_it_while_waiting_moves_the_ticket(proj, new_ticket):
    a, b = new_ticket("a"), new_ticket("b")
    _queue(proj, a)
    _queue(proj, b)
    assert [t for t, _ in runs_live.waiting_line(proj)] == [a, b]
    tickets.set_priority(proj, b, "high", "human:tester")
    assert [t for t, _ in runs_live.waiting_line(proj)] == [b, a]


def test_an_urgent_start_still_jumps_a_low_ticket(proj, new_ticket):
    a, b = new_ticket("a"), new_ticket("b")
    tickets.set_priority(proj, b, "low", "human:tester")
    _queue(proj, a)
    _queue(proj, b, "high")  # e.g. a red develop
    assert runs_live.waiting_line(proj) == [(b, "high"), (a, "normal")]


def test_a_low_start_never_lowers_a_ticket_the_person_raised(proj, new_ticket):
    a, b = new_ticket("a"), new_ticket("b")
    tickets.set_priority(proj, b, "high", "human:tester")
    _queue(proj, a)
    _queue(proj, b, "low")
    assert runs_live.waiting_line(proj) == [(b, "high"), (a, "normal")]


def test_without_a_ticket_priority_the_start_decides_as_before(proj, new_ticket):
    a, b = new_ticket("a"), new_ticket("b")
    _queue(proj, a, "low")  # e.g. the Development expert's low start
    _queue(proj, b)
    assert runs_live.waiting_line(proj) == [(b, "normal"), (a, "low")]


def test_a_repair_keeps_the_ticket_priority(proj, new_ticket):
    """A dropped pull request wakes its ticket at high (ORCH-688): the higher priority repair first."""
    a, b, c = new_ticket("a"), new_ticket("b"), new_ticket("c")
    tickets.set_priority(proj, b, "high", "human:tester")
    tickets.set_priority(proj, c, "low", "human:tester")
    _queue(proj, c, "high")  # repairs, oldest first
    _queue(proj, a, "high")
    _queue(proj, b, "high")
    assert runs_live.waiting_line(proj) == [(b, "high"), (a, "high"), (c, "high")]
