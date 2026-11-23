"""orch ask --because (ORCH-1643, Focus draft D): the helper's one-line reason for the answer it suggests.
The dashboard highlights a suggested answer only when it has one. It goes with --recommend, is part of what
the person is shown (the question's digest), and a question without it keeps its old digest."""

from orch import tickets


def _ask(run, tid, *extra):
    return run(
        "ask",
        tid,
        "Keep the old file name?",
        "--option",
        "Keep",
        "--option",
        "Rename",
        *extra,
        "--by",
        "agent:helper",
    )


def test_because_is_kept_with_the_suggestion_and_in_the_digest(proj, run, new_ticket):
    tid = new_ticket("Files")
    code, out, err = _ask(
        run, tid, "--recommend", "Keep", "--because", "  links people  shared keep working. "
    )
    assert code == 0, out + err
    q = tickets.load(proj, tid)["questions"][0]
    assert q["recommended"] == "Keep"
    assert q["because"] == "links people shared keep working."
    plain = {k: v for k, v in q.items() if k != "because"}
    assert tickets.question_digest(q) != tickets.question_digest(plain)


def test_a_question_without_because_has_no_field_and_keeps_its_digest(proj, run, new_ticket):
    tid = new_ticket("Files")
    assert _ask(run, tid, "--recommend", "Keep")[0] == 0
    q = tickets.load(proj, tid)["questions"][0]
    assert "because" not in q


def test_because_needs_a_suggestion_and_stays_one_short_line(proj, run, new_ticket):
    tid = new_ticket("Files")
    code, out, err = _ask(run, tid, "--because", "a reason")
    assert code == 2 and "--recommend" in out + err
    code, out, err = _ask(run, tid, "--recommend", "Keep", "--because", "x" * 201)
    assert code == 2 and "at most 200" in out + err
    assert tickets.load(proj, tid)["questions"] == []
