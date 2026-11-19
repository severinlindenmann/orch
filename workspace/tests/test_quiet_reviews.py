"""ORCH-826: review tickets orch makes itself (a security review of a pull request, the Reviewer's second
look) reach the owner only when they found a problem. Owner: "they should rather highlight if something is
not good for me to check and not what is good". An ok is accepted for the owner by the Reviewer; a problem
stays on the owner's list and its card leads with it."""

import json

import pytest

from orch import lookreview, review, reviewer, runs, secreview, tickets

SHA = "a1b2c3d4" + "0" * 32


@pytest.fixture(autouse=True)
def no_starts(monkeypatch):
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: {"run": "r_x"})


@pytest.fixture
def on(proj, run):
    assert run("config", "set", "workflow.reviewer", "on", "--by", "human:tester")[0] == 0


def _review_ticket(proj, run, new_ticket, title="Security review: pull request #7 feat: relay limits"):
    tid = new_ticket(title)
    assert (
        run("check", "add", tid, "Review the change and record the verdict", "--by", "human:tester")[0] == 0
    )
    assert run("check", "done", tid, "c1", "--note", "read the diff", "--by", "human:tester")[0] == 0
    tickets.set_status(proj, tid, "review", "human:tester")
    return tid


def _keeper(proj, tid, n=7, sha=SHA):
    d = runs.run_dir(proj)
    d.mkdir(parents=True, exist_ok=True)
    st = {"security": {"prs": {str(n): {"sha": sha, "tid": tid, "key": "SEC-7"}}}}
    (d / "release-keeper.json").write_text(json.dumps(st))


def _verdict(proj, word, line, n=7, sha=SHA):
    data = secreview.read_verdicts(proj)
    data[str(n)] = {"sha": sha, "verdict": word, "line": line, "by": "agent:claude", "at": tickets.now()}
    secreview._write_verdicts(proj, data)


def _lines(proj, tid):
    return [h["text"] for h in tickets.load(proj, tid)["history"]]


def test_an_ok_security_review_is_accepted_for_the_owner(proj, run, new_ticket, on):
    tid = _review_ticket(proj, run, new_ticket)
    _keeper(proj, tid)
    _verdict(proj, "ok", "No High or Medium. Low: a log line names the port.")
    res = reviewer.run(proj)
    assert [a["verdict"] for a in res["actions"]] == ["accept"]
    assert tickets.load(proj, tid)["status"] == "done"
    assert _lines(proj, tid)[-1] == (
        "Accepted for you by the Reviewer: The security review of pull request #7 found nothing for you: "
        "No High or Medium. Low: a log line names the port."
    )


def test_a_security_problem_stays_with_the_owner_and_the_card_leads_with_it(proj, run, new_ticket, on):
    tid = _review_ticket(proj, run, new_ticket)
    _keeper(proj, tid)
    _verdict(proj, "problems", "High: the inbox accepts a message without sign-in")
    reviewer.run(proj)
    t = tickets.load(proj, tid)
    assert t["status"] == "review"
    assert _lines(proj, tid)[-1] == (
        "Left for you by the Reviewer: the security review of pull request #7 found a problem: "
        "High: the inbox accepts a message without sign-in"
    )
    card = review.check_card(t, proj)
    assert card["why"] == "Check this: High: the inbox accepts a message without sign-in"
    assert card["preview"]["headline"] == "Problem found: High: the inbox accepts a message without sign-in"
    assert card["preview"]["chips"][0] == {"text": "Problem found", "tone": "bad"}


def test_a_card_of_any_other_ticket_is_unchanged(proj, run, new_ticket):
    tid = _review_ticket(proj, run, new_ticket, title="Fix the stale run record")
    card = review.check_card(tickets.load(proj, tid), proj)
    assert card["why"] == "The helper says this is ready for your check."
    assert not any(c.get("text") == "Problem found" for c in card["preview"].get("chips") or [])


def test_no_verdict_yet_is_left_as_before(proj, run, new_ticket, on):
    tid = _review_ticket(proj, run, new_ticket)
    _keeper(proj, tid)
    reviewer.run(proj)
    assert tickets.load(proj, tid)["status"] == "review"
    assert _lines(proj, tid)[-1].endswith("no pull request to check, so you look at it yourself.")


def test_an_ok_recorded_after_the_reviewer_left_it_is_accepted_next_pass(proj, run, new_ticket, on):
    tid = _review_ticket(proj, run, new_ticket)
    _keeper(proj, tid)
    reviewer.run(proj)  # no verdict yet: left, and remembered as decided
    _verdict(proj, "ok", "nothing High or Medium")  # the ticket itself does not change
    reviewer.run(proj)
    assert tickets.load(proj, tid)["status"] == "done"


def test_an_ok_for_an_older_commit_does_not_count(proj, run, new_ticket, on):
    tid = _review_ticket(proj, run, new_ticket)
    _keeper(proj, tid, sha="f" * 40)  # the pull request moved on since the verdict
    _verdict(proj, "ok", "nothing High or Medium")
    reviewer.run(proj)
    assert tickets.load(proj, tid)["status"] == "review"


def test_a_newer_review_owns_the_pull_request_so_the_old_ticket_stays(proj, run, new_ticket, on):
    tid = _review_ticket(proj, run, new_ticket)
    _keeper(proj, "t_newer")
    _verdict(proj, "ok", "nothing High or Medium")
    assert secreview.ticket_result(proj, tickets.load(proj, tid)) is None


def test_a_person_titled_security_review_is_not_orchs_own(proj, run, new_ticket, on):
    tid = _review_ticket(proj, run, new_ticket, title="Security review of the browser terminal")
    _keeper(proj, tid)
    _verdict(proj, "ok", "fine")
    assert reviewer.review_result(proj, tickets.load(proj, tid)) is None


def test_the_owners_release_anyway_counts_as_ok(proj, run, new_ticket, on):
    tid = _review_ticket(proj, run, new_ticket)
    d = runs.run_dir(proj)
    d.mkdir(parents=True, exist_ok=True)
    st = {"security": {"prs": {"7": {"sha": SHA, "tid": tid, "owner_ok": SHA}}}}
    (d / "release-keeper.json").write_text(json.dumps(st))
    _verdict(proj, "problems", "Medium: a token in a log")
    got = secreview.ticket_result(proj, tickets.load(proj, tid))
    assert got == {
        "ok": True,
        "line": "you said release anyway",
        "what": "the security review of pull request #7",
    }


def _second_look(proj, run, new_ticket, waiting=()):
    tid = _review_ticket(proj, run, new_ticket, title=f"{lookreview.TITLE} 2026-11-19 (2)")
    st = lookreview.read_state(proj)
    st["mine"] = [tid]
    st["open"] = {"ticket": tid, "items": ["t_a", "t_b"]}
    st["line"] = {w: {"why": "too big", "at": tickets.now()} for w in waiting}
    lookreview._write_state(proj, st)
    return tid


def test_a_finished_second_look_is_accepted_for_the_owner(proj, run, new_ticket, on):
    tid = _second_look(proj, run, new_ticket)
    reviewer.run(proj)
    assert tickets.load(proj, tid)["status"] == "done"
    assert "The Reviewer's second look found nothing for you" in _lines(proj, tid)[-1]


def test_a_second_look_with_a_ticket_still_waiting_is_not_finished(proj, run, new_ticket):
    tid = _second_look(proj, run, new_ticket, waiting=["t_b"])
    assert lookreview.ticket_result(proj, tickets.load(proj, tid)) is None


def test_off_reviewer_accepts_nothing(proj, run, new_ticket):
    tid = _review_ticket(proj, run, new_ticket)
    _keeper(proj, tid)
    _verdict(proj, "ok", "nothing High or Medium")
    reviewer.run(proj)
    assert tickets.load(proj, tid)["status"] == "review"


def test_a_security_problem_never_goes_to_the_second_look(proj, run, new_ticket, on):
    assert run("config", "set", "workflow.reviewer_look", "on", "--by", "human:tester")[0] == 0
    tid = _review_ticket(proj, run, new_ticket)
    _keeper(proj, tid)
    _verdict(proj, "problems", "High: a check can be skipped")
    reviewer.run(proj)
    assert tid not in lookreview.read_state(proj)["line"]
    assert tickets.load(proj, tid)["status"] == "review"


def test_an_ok_held_by_an_open_question_is_written_once(proj, run, new_ticket, on):
    tid = _review_ticket(proj, run, new_ticket)
    _keeper(proj, tid)
    _verdict(proj, "ok", "nothing High or Medium")
    assert run("ask", tid, "Ship it?", "--option", "yes", "--option", "no", "--by", "agent:claude")[0] == 0
    tickets.set_status(proj, tid, "review", "human:tester")  # asking moved it to Waiting
    reviewer.run(proj)
    reviewer.run(proj)
    left = [x for x in _lines(proj, tid) if x.startswith("Left for you by the Reviewer: ")]
    assert left == ["Left for you by the Reviewer: a question on this ticket waits for your answer."]
