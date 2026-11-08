"""Done criteria follow the optional note field through writes and agent prompts."""

import json

import pytest

from orch import runs, tickets
from orch.errors import Refused

TEXT = "  The export opens.\n\n  Every invoice is included.  "


def test_new_edit_patch_and_clear(proj, run, validate):
    code, out, err = run("ticket", "new", "Export", "--done-when", TEXT, "--json")
    assert code == 0, err
    tid = json.loads(out)["id"]
    assert tickets.load(proj, tid)["done_when"] == TEXT
    assert f"Done when: {TEXT}" in run("ticket", "show", tid)[1]
    for operation in ("edit", "patch"):
        for value in ("x" * 2000, TEXT, ""):
            if operation == "edit":
                args = ("--done-when", value)
            else:
                args = (
                    json.dumps({"done_when": value}),
                    "--if-revision",
                    str(tickets.load(proj, tid)["revision"]),
                )
            code, _, err = run("ticket", operation, tid, *args)
            assert code == 0, err
            ticket = tickets.load(proj, tid)
            validate(ticket)
            assert ticket.get("done_when") == (value or None)


@pytest.mark.parametrize("operation", ["new", "edit", "patch"])
def test_too_long_is_rejected(proj, run, new_ticket, operation):
    tid = new_ticket()
    before = tickets.load(proj, tid)
    if operation == "new":
        args = ("Export", "--done-when", "x" * 2001)
    elif operation == "edit":
        args = (tid, "--done-when", "x" * 2001)
    else:
        args = (tid, json.dumps({"done_when": "x" * 2001}), "--if-revision", str(before["revision"]))
    code, _, err = run("ticket", operation, *args)
    assert code == 2
    assert "The done criteria are at most 2000 characters." in err
    assert tickets.load(proj, tid) == before


@pytest.mark.parametrize("value", [1, [], {}])
def test_done_when_requires_text(value):
    with pytest.raises(Refused, match="done_when must be text"):
        tickets.clean_field("done_when", value)


@pytest.mark.parametrize("field", ["note", "done_when"])
def test_multiline_whitespace_and_clear(field):
    assert tickets.clean_field(field, TEXT) == TEXT
    assert tickets.clean_field(field, " \n ") is None
    assert tickets.clean_field(field, None) is None


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize(
    "checks",
    [[], [{"id": "c1", "text": "Export", "done": False}], [{"id": "c1", "text": "Export", "done": True}]],
)
def test_prompt_plans_criteria_only_without_checks(resume, checks):
    ticket = {"id": "t_abcdef", "title": "Export", "done_when": TEXT, "checklist": checks}
    prompt = runs.resume_prompt(ticket, [], None, "codex") if resume else runs.fresh_prompt(ticket, [])
    expected = (
        "The person described what should be true when it is done: "
        "The export opens. Every invoice is included.. Turn this into checks with "
        "`orch check add` (one check per thing that must be true), then start."
    )
    assert (expected in prompt) == (not checks)
    if checks:
        assert "The person described" not in prompt


def test_plan_missing_and_clipped():
    assert runs._done_when_plan({}) == []
    assert runs._done_when_plan({"done_when": ""}) == []
    plan = runs._done_when_plan({"done_when": "x" * 2100})[0]
    assert "x" * 1999 + "…" in plan
    assert "x" * 2000 not in plan
