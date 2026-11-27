"""R2.4/R2.5: a helper's `orch ask` carries at least two options and a recommended answer; a bare question
is refused with the one-line fix. A person asking, and add-on kinds that word their own answers, are not
held to it."""

import pytest

from orch import tickets

FIX = "--option <A> --option <B> --recommend <A>"


@pytest.mark.parametrize(
    "extra",
    [
        (),
        ("--option", "Keep"),
        ("--option", "Keep", "--recommend", "Keep"),
        ("--option", "Keep", "--option", "Rename"),
        ("--option", " ", "--option", "Keep", "--recommend", "Keep"),
    ],
)
def test_a_helper_question_without_two_options_and_a_suggestion_is_refused(proj, run, new_ticket, extra):
    tid = new_ticket("Files")
    code, out, err = run("ask", tid, "Keep the old file name?", *extra, "--by", "agent:helper")
    assert code == 2
    said = (out + err).strip()
    assert FIX in said and said.count(". ") == 0  # one sentence that says what to type
    t = tickets.load(proj, tid)
    assert t["questions"] == [] and t["status"] != "waiting"


def test_a_helper_question_with_options_and_a_suggestion_is_asked(proj, run, new_ticket):
    tid = new_ticket("Files")
    code, out, err = run(
        "ask", tid, "Keep the old file name?", "--option", "Keep", "--option", "Rename",
        "--recommend", "Keep", "--by", "agent:helper",
    )  # fmt: skip
    assert code == 0, out + err
    q = tickets.load(proj, tid)["questions"][0]
    assert q["options"] == ["Keep", "Rename"] and q["recommended"] == "Keep"


def test_an_agent_tool_in_the_environment_is_held_to_it_whatever_by_says(proj, run, new_ticket, monkeypatch):
    tid = new_ticket("Files")
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, err = run("ask", tid, "Which year?", "--by", "human:tester")
    assert code == 2 and FIX in out + err


def test_a_person_and_an_add_on_kind_may_ask_without_a_suggestion(proj, run, new_ticket):
    tid = new_ticket("Files")
    assert run("ask", tid, "What would you change?", "--by", "human:tester")[0] == 0
    other = new_ticket("Run")
    code, out, err = run(
        "ask", other, "Try again?", "--kind", "automation:failure", "--option", "Try again",
        "--option", "Leave it", "--by", "agent:fake",
    )  # fmt: skip
    assert code == 0, out + err
