"""ORCH-37 (owner picked B): a release is a ticket of its own; the epics and tickets that ship together sit
under it as sub-tickets. The mark is set at creation or later, never through a plain patch."""

import json

import pytest

from orch import tickets
from orch.errors import Refused


def read(proj, tid):
    return json.loads((proj / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))


def test_new_release_is_valid_and_shown(proj, run, validate):
    code, out, _ = run("ticket", "new", "Release 26", "--release", "--json")
    assert code == 0
    tid = json.loads(out)["id"]
    t = read(proj, tid)
    validate(t)
    assert t["release"] is True
    assert "Release: the epics and tickets under it ship together" in run("ticket", "show", tid)[1]


def test_epic_and_ticket_sit_under_a_release(proj, run, validate, new_ticket):
    rel = json.loads(run("ticket", "new", "Release 26", "--release", "--json")[1])["id"]
    epic = json.loads(run("ticket", "new", "Ticket flow", "--epic", "--json")[1])["id"]
    task = new_ticket("Board lanes")
    assert run("ticket", "edit", epic, "--parent", rel)[0] == 0
    assert run("ticket", "edit", task, "--parent", epic)[0] == 0
    assert read(proj, epic)["parent"] == rel and read(proj, task)["parent"] == epic
    for tid in (rel, epic, task):
        validate(read(proj, tid))


def test_edit_marks_and_unmarks_an_existing_ticket(proj, run, new_ticket):
    tid = new_ticket("Release 27")
    assert run("ticket", "edit", tid, "--release", "yes")[0] == 0
    t = read(proj, tid)
    assert t["release"] is True and t["history"][-1]["text"] == "Marked as a release"
    rev = t["revision"]
    assert run("ticket", "edit", tid, "--release", "yes")[0] == 0
    assert read(proj, tid)["revision"] == rev, "marking it twice writes nothing"
    assert run("ticket", "edit", tid, "--release", "no")[0] == 0
    t = read(proj, tid)
    assert "release" not in t and t["history"][-1]["text"] == "No longer a release"


def test_edit_release_and_parent_together(proj, run, new_ticket):
    holder, tid = new_ticket("Q4"), new_ticket("Release 28")
    assert run("ticket", "edit", tid, "--release", "yes", "--parent", holder)[0] == 0
    t = read(proj, tid)
    assert t["release"] is True and t["parent"] == holder


def test_plain_patch_cannot_set_the_mark(proj, new_ticket):
    tid = new_ticket()
    with pytest.raises(Refused):
        tickets.clean_field("release", True)
    with pytest.raises(Refused):
        tickets.patch(proj, tid, read(proj, tid)["revision"], json.dumps({"release": True}), "human:test")


def test_list_and_show_name_the_kind(run, new_ticket):
    """ORCH-906: `ticket list` names an epic and a release; `ticket show` has an epic line too."""
    rel = json.loads(run("ticket", "new", "Release 30", "--release", "--json")[1])["id"]
    epic = json.loads(run("ticket", "new", "Ticket flow", "--epic", "--json")[1])["id"]
    plain = new_ticket("Board lanes")
    out = run("ticket", "list")[1]
    line = {tid: next(x for x in out.splitlines() if f"[{tid}]" in x) for tid in (rel, epic, plain)}
    assert "(Release, " in line[rel] and "(Epic, " in line[epic]
    assert "(Release" not in line[plain] and "(Epic" not in line[plain]
    assert "Epic: its sub-tickets are the work" in run("ticket", "show", epic)[1]
    assert "Epic:" not in run("ticket", "show", plain)[1]
