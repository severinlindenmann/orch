"""The Reviewer answers small, routine questions for the owner (ORCH-176): a plain question with the
helper's recommended option, open 30 minutes, naming no concept, words, look, money or production, is answered
with that option and one line says why. Everything else stays for the owner. Only a person turns it on."""

import time

import pytest

from orch import brake, reviewer, runs, tickets

LATER = time.time() + 3600  # past the 30 minutes


@pytest.fixture(autouse=True)
def no_starts(monkeypatch):
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: {"run": "r_x"})


@pytest.fixture
def on(proj, run):
    assert run("config", "set", "workflow.reviewer_answers", "on", "--by", "human:tester")[0] == 0


def _ask(run, tid, text, options=("Fix it now", "Open an issue"), rec="Fix it now", *extra):
    args = ["ask", tid, text]
    for o in options:
        args += ["--option", o]
    if rec:
        args += ["--recommend", rec]
    code, out, err = run(*args, *extra, "--by", "agent:helper")
    assert code == 0, out + err


def _q(proj, tid, qid="q1"):
    return next(q for q in tickets.load(proj, tid)["questions"] if q["id"] == qid)


def test_a_routine_question_is_answered_with_the_recommendation_and_the_reason(proj, run, new_ticket, on):
    tid = new_ticket("Flaky test in the run tests")
    _ask(run, tid, "The run test fails once in ten on Windows. Fix it now or open an issue?")
    rows = reviewer.answer_routine(proj, now=LATER)
    assert [(r["question"], r["routine"], r["done"]) for r in rows] == [("q1", True, True)]
    q = _q(proj, tid)
    assert (q["answer"], q["answered_by"], q["via"]) == ("Fix it now", "agent:reviewer", "reviewer")
    t = tickets.load(proj, tid)
    assert t["history"][-1]["text"] == (
        "Answered for you by the Reviewer: q1 = Fix it now (routine: a plain question with the helper's "
        "recommendation, no concept, words, look, money or production)"
    )
    assert t["waiting_on"] is None and t["status"] != "waiting"


def test_a_fresh_question_waits_30_minutes_for_the_owner(proj, run, new_ticket, on):
    tid = new_ticket("Flaky test in the run tests")
    _ask(run, tid, "The run test fails once in ten. Fix it now or open an issue?")
    rows = reviewer.answer_routine(proj)
    assert rows[0]["routine"] is False and "30 minutes" in rows[0]["why"]
    assert _q(proj, tid)["answer"] is None


@pytest.mark.parametrize(
    "text,kind",
    [
        ("Rename the button to Start?", "words"),
        ("Keep the new wording on the board?", "words"),
        ("Should the board column show only tickets that need me?", "look"),
        ("Should a person also be able to continue one chosen older session?", "concept"),
        ("Should the Renew window show that code, so they renew in a few clicks?", "look"),
        ("Is it fine to merge once CI is green? I have no screenshots yet.", "look"),
        ("Add a new setting for the timeout?", "concept"),
        ("Fine to merge on green?", "cannot be undone"),
        ("Delete the old run records?", "cannot be undone"),
        ("Deploy the relay now?", "production"),
        ("Use the API credit for this?", "money"),
        ("Look at 1280 and 390 fine?", "look"),
    ],
)
def test_concept_words_look_money_and_production_stay_for_the_owner(proj, run, new_ticket, on, text, kind):
    tid = new_ticket("Small fix")
    _ask(run, tid, text, ("Yes", "No"), "Yes")
    rows = reviewer.answer_routine(proj, now=LATER)
    assert rows[0]["routine"] is False and kind in rows[0]["why"]
    assert _q(proj, tid)["answer"] is None


def test_the_ticket_title_counts_too(proj, run, new_ticket, on):
    tid = new_ticket("New look for the Tickets page")
    _ask(run, tid, "The test fails once in ten. Fix it now or open an issue?")
    assert reviewer.answer_routine(proj, now=LATER)[0]["routine"] is False


def test_no_recommendation_or_one_option_stays(proj, run, new_ticket, on):
    tid = new_ticket("Small fix")
    _ask(run, tid, "Fix it now or open an issue?", rec=None)
    _ask(run, tid, "Go on with the fix?", ("Go on",), "Go on")
    rows = reviewer.answer_routine(proj, now=LATER)
    assert all(not r["routine"] and r["why"] == "no recommended option" for r in rows)


def test_a_card_stays_for_the_owner(proj, run, new_ticket, on, tmp_path):
    tid = new_ticket("Small fix")
    args = ["--choose", "Pick", "--option", "A=First", "--option", "B=Second", "--suggest", "B"]
    code, out, err = run("ask", tid, "Which one?", *args, "--then", "I build it.", "--by", "agent:helper")
    assert code == 0, out + err
    rows = reviewer.answer_routine(proj, now=LATER)
    assert rows and not rows[0]["routine"]
    assert _q(proj, tid)["answer"] is None


def test_off_by_default_and_paused_does_nothing(proj, run, new_ticket):
    tid = new_ticket("Small fix")
    _ask(run, tid, "The test fails once in ten. Fix it now or open an issue?")
    assert reviewer.run(proj)["off"] is True
    with pytest.raises(tickets.Refused, match="does not answer"):
        tickets.answer_for_owner(proj, tid, "q1", tickets.question_digest(_q(proj, tid)), "x")
    run("config", "set", "workflow.reviewer_answers", "on", "--by", "human:tester")
    brake.pause(proj, "human:tester")
    assert reviewer.run(proj)["paused"] is True
    assert _q(proj, tid)["answer"] is None


def test_only_a_person_turns_it_on(proj, run):
    code, out, err = run("config", "set", "workflow.reviewer_answers", "on", "--by", "agent:helper")
    assert code == 2 and "Only the owner" in out + err
    assert run("config", "set", "workflow.reviewer_answers", "off", "--by", "agent:helper")[0] == 0
    assert run("config", "set", "workflow.reviewer_answers", "on", "--by", "human:tester")[0] == 0
    code, out, _ = run("config", "get", "workflow.reviewer_answers")
    assert code == 0 and "true" in out.lower()


def test_tend_answers_without_the_review_switch_and_dry_run_only_says(proj, run, new_ticket, on, monkeypatch):
    monkeypatch.setattr(reviewer, "ROUTINE_WAIT", 0)
    tid = new_ticket("Flaky test in the run tests")
    _ask(run, tid, "The run test fails once in ten. Fix it now or open an issue?")
    code, out, _ = run("review", "tend", "--dry-run")
    assert code == 0 and "q1: would be answered for you: Fix it now" in out
    assert _q(proj, tid)["answer"] is None
    code, out, _ = run("review", "tend")
    assert code == 0 and "q1: answered for you: Fix it now" in out
    assert _q(proj, tid)["answer"] == "Fix it now"
    code, out, _ = run("review", "accepted")
    assert code == 0 and "Answered for you today: 1 question" in out and 'answered "Fix it now"' in out
    assert "routine:" not in out and "q1 = " not in out  # plain words, not the history line (issue 1919)


def test_a_changed_question_is_refused(proj, run, new_ticket, on):
    tid = new_ticket("Small fix")
    _ask(run, tid, "The test fails once in ten. Fix it now or open an issue?")
    with pytest.raises(tickets.Refused, match="changed"):
        tickets.answer_for_owner(proj, tid, "q1", "0" * 64, "x")


@pytest.mark.parametrize(
    "text", ["Fix the d\u0435ploy now?", "Fix it now or open an iss\u200bue?", "Fix it now or de\x08lete?"]
)
def test_look_alike_letters_and_hidden_marks_stay_for_the_owner(proj, run, new_ticket, on, text):
    tid = new_ticket("Small fix")
    _ask(run, tid, text)
    assert reviewer.answer_routine(proj, now=LATER)[0]["routine"] is False


def test_the_wait_counts_from_the_question_not_from_history(proj, run, new_ticket, on):
    tid = new_ticket("Small fix")
    tickets.log(proj, tid, "Asked q1, waiting", "agent:helper")  # a line written before asking counts not
    _ask(run, tid, "The test fails once in ten. Fix it now or open an issue?")
    assert _q(proj, tid)["asked_at"]
    rows = reviewer.answer_routine(proj)
    assert rows[0]["routine"] is False and "30 minutes" in rows[0]["why"]


def test_a_question_from_an_older_version_stays_for_the_owner(proj, run, new_ticket, on):
    tid = new_ticket("Small fix")
    _ask(run, tid, "The test fails once in ten. Fix it now or open an issue?")
    t = tickets.load(proj, tid)
    t["questions"][0].pop("asked_at")
    tickets.save(proj, t)
    assert reviewer.answer_routine(proj, now=LATER)[0]["routine"] is False


def test_a_routine_answer_reads_as_plain_words():
    raw = "q3 = Morning (routine: a plain question with the helper's recommendation, no concept)"
    assert reviewer._answered_words(raw) == 'answered "Morning"'
    assert reviewer._answered_words("something else") == "answered something else"
