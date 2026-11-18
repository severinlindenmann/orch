"""Drafts, mockups and designs are picked only by the owner (ORCH-582): every automation is refused on a draft
card and on a ticket that carries one, with one line why; a signed-in person (dashboard grant) or a paired
phone answers it. Bug fixes and follow-up problems (no draft card) are accepted by the Reviewer as before."""

import json
import time

import pytest

from orch import lookreview, ownerpick, review, reviewer, runs, tickets, worktrees
from orch.errors import Refused

PR = "https://github.com/acme/app/pull/12"
ME = "human:pat"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


@pytest.fixture(autouse=True)
def no_starts(monkeypatch):
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: {"run": "r_x"})
    monkeypatch.delenv("ORCH_TICKET", raising=False)


@pytest.fixture
def facts(monkeypatch):
    """One merged, green, small fix (what the Reviewer accepts when no draft is on the ticket)."""
    f = {
        "url": PR, "number": 12, "state": "MERGED", "green": True, "checks": 17, "failed": 0,
        "merged_at": "2999-01-01T00:00:00Z",
        "files": [{"path": "workspace/src/orch/runs.py", "additions": 20, "deletions": 4},
                  {"path": "workspace/tests/test_runs.py", "additions": 80, "deletions": 0}],
        "added": {"workspace/src/orch/runs.py": ["    if not rec:", "        return None"]},
    }  # fmt: skip
    monkeypatch.setattr(reviewer, "pr_facts", lambda url: f if url == PR else None)
    return f


def _on(run, *keys):
    for k in keys:
        assert run("config", "set", f"workflow.{k}", "on", "--by", "human:tester")[0] == 0


def _draft(run, tid, title="Home list"):
    code, out, err = run(
        "ask",
        tid,
        f"Please look: {title}",
        "--draft",
        title,
        "--then",
        "I build it.",
        "--json",
        "--by",
        "agent:x",
    )
    assert code == 0, out + err
    return json.loads(out)


def _choose(proj, run, tid, pictures=True):
    (proj / "a.png").write_bytes(PNG)
    (proj / "b.png").write_bytes(PNG)
    opts = ["A=Quiet list:a.png", "B=Rules per kind:b.png"] if pictures else ["A=Fix now", "B=Open an issue"]
    what = "Which look?" if pictures else "Which way?"
    args = ["ask", tid, what, "--choose", what, "--then", "I build it."]
    for o in opts:
        args += ["--option", o]
    code, out, err = run(*args, "--json", "--by", "agent:x")
    assert code == 0, out + err
    return json.loads(out)


def _finished(proj, run, new_ticket, title="Auto Reviewer page"):
    tid = new_ticket(title)
    assert run("ticket", "tidy", tid, title, "--description", "d", "--done-when", "the page is built",
               "--by", "human:tester")[0] == 0  # fmt: skip
    assert (
        run("check", "add", tid, "Build the page", "--covers", "the page is built", "--by", "human:tester")[0]
        == 0
    )
    assert run("check", "done", tid, "c1", "--pr", PR, "--by", "human:tester")[0] == 0
    return tid


def _picked(proj, tid, qid):
    """The owner picked it on the dashboard (signed in): the card is answered, the ticket still carries it."""
    review.decide(proj, tid, qid, "ok", by=ME, via="dashboard", person=True)


def _q(proj, tid, qid):
    return next(q for q in tickets.load(proj, tid)["questions"] if q["id"] == qid)


# ------------------------------------------------------------------ which cards are drafts


def test_a_draft_card_and_a_choice_of_pictures_are_drafts_a_plain_choice_is_not(proj, run, new_ticket):
    tid = new_ticket()
    assert ownerpick.is_draft_card(_draft(run, tid))
    assert ownerpick.is_draft_card(_choose(proj, run, tid))
    assert not ownerpick.is_draft_card(_choose(proj, run, tid, pictures=False))
    assert not ownerpick.is_draft_card({"id": "q9", "text": "Ship it?", "options": ["Yes", "No"]})


# ------------------------------------------------------------------ orch answer / orch review answer


def test_review_answer_from_a_script_is_refused_on_a_draft_whatever_via_says(proj, run, new_ticket):
    tid = new_ticket()
    q = _draft(run, tid)
    for via in ("cli", "dashboard", "phone", "page"):
        code, out, _ = run(
            "review", "answer", tid, q["id"], "--verdict", "ok", "--via", via, "--by", ME, "--json"
        )
        assert code == 2 and "Only a person picks a draft" in out, (via, out)
    assert _q(proj, tid, q["id"])["answer"] is None


def test_plain_answer_from_a_script_is_refused_on_a_draft(proj, run, new_ticket):
    tid = new_ticket()
    q = _choose(proj, run, tid)
    code, out, err = run("answer", tid, q["id"], "A", "--via", "dashboard", "--by", ME)
    assert code == 2 and "Only a person picks a draft" in out + err, out + err
    assert _q(proj, tid, q["id"])["answer"] is None


def test_a_helper_shell_is_refused_even_with_a_grant(proj, run, new_ticket, person_grant, monkeypatch):
    tid = new_ticket()
    q = _draft(run, tid)
    monkeypatch.setenv("CLAUDECODE", "1")  # a helper's shell
    person_grant(proj)
    code, out, _ = run("review", "answer", tid, q["id"], "--verdict", "ok", "--by", ME, "--json")
    assert code == 2 and _q(proj, tid, q["id"])["answer"] is None
    monkeypatch.delenv("CLAUDECODE")
    person_grant(proj)
    monkeypatch.setenv("ORCH_RUN", "r_1")  # inside a helper run
    code, out, err = run("answer", tid, q["id"], "ok", "--by", ME)
    assert code == 2 and _q(proj, tid, q["id"])["answer"] is None


def test_the_signed_in_dashboard_answers_a_draft_once_per_grant(proj, run, new_ticket, person_grant):
    tid = new_ticket()
    q1, q2 = _draft(run, tid, "One"), _draft(run, tid, "Two")
    person_grant(proj)
    code, out, err = run(
        "review", "answer", tid, q1["id"], "--verdict", "ok", "--via", "dashboard", "--by", ME
    )
    assert code == 0, out + err
    assert _q(proj, tid, q1["id"])["via"] == "dashboard"
    code, out, err = run(
        "review", "answer", tid, q2["id"], "--verdict", "ok", "--via", "dashboard", "--by", ME
    )
    assert (
        code == 2 and "Only a person picks a draft" in out + err
    )  # the grant was used up by the first answer
    person_grant(proj)
    code, out, err = run("answer", tid, q2["id"], "ok", "--via", "dashboard", "--by", ME)
    assert code == 0, out + err


def test_a_forged_grant_is_refused(proj, run, new_ticket, monkeypatch):
    from orch import renew

    tid = new_ticket()
    q = _draft(run, tid)
    monkeypatch.setenv(renew.GRANT_ENV, "x" * 32)
    code, out, _ = run("review", "answer", tid, q["id"], "--verdict", "ok", "--by", ME, "--json")
    assert code == 2 and _q(proj, tid, q["id"])["answer"] is None


def test_plain_cards_and_questions_answer_from_the_terminal_as_before(proj, run, new_ticket):
    tid = new_ticket()
    q = _choose(proj, run, tid, pictures=False)
    code, out, err = run("review", "answer", tid, q["id"], "--verdict", "ok", "--picked", "A", "--by", ME)
    assert code == 0, out + err
    run("ask", tid, "Ship it?", "--option", "Yes", "--option", "No", "--by", "agent:x")
    code, out, err = run("answer", tid, "q2", "Yes", "--by", ME)
    assert code == 0, out + err


def test_change_of_a_draft_answer_needs_a_person_too(proj, run, new_ticket):
    tid = new_ticket()
    q = _choose(proj, run, tid)
    review.decide(proj, tid, q["id"], "ok", "A", by=ME, via="phone", person=True)
    with pytest.raises(Refused, match="Only a person picks a draft"):
        review.change(proj, tid, q["id"], "ok", "B", by=ME, via="dashboard")
    review.change(proj, tid, q["id"], "ok", "B", by=ME, via="dashboard", person=True)


def test_the_phone_answers_a_draft(proj, run, new_ticket):
    """relay.py passes person=True only after it checked the paired phone; core then takes it."""
    tid = new_ticket()
    q = _draft(run, tid)
    with pytest.raises(Refused, match="Only a person picks a draft"):
        review.decide(proj, tid, q["id"], "ok", by=ME, via="phone")
    out = review.decide(proj, tid, q["id"], "ok", by=ME, via="phone", person=True)
    assert out["via"] == "phone" and out["decision"]["action"] == "approve"


# ------------------------------------------------------------------ the Check of a ticket with a draft


def test_the_check_of_a_ticket_with_a_draft_needs_a_person(proj, run, new_ticket, person_grant):
    tid = _finished(proj, run, new_ticket)
    q = _draft(run, tid)
    _picked(proj, tid, q["id"])
    tickets.set_status(proj, tid, "review", "human:tester")
    code, out, _ = run(
        "review", "answer", tid, "review", "--verdict", "ok", "--via", "dashboard", "--by", ME, "--json"
    )
    assert code == 2 and "This ticket carries a draft" in out
    assert tickets.load(proj, tid)["status"] == "review"
    person_grant(proj)
    code, out, err = run(
        "review", "answer", tid, "review", "--verdict", "ok", "--via", "dashboard", "--by", ME
    )
    assert code == 0, out + err
    assert tickets.load(proj, tid)["status"] == "done"


# ------------------------------------------------------------------ the Reviewer and its second look


def test_the_reviewer_leaves_a_ticket_with_a_draft_and_never_moves_it_to_done(proj, run, new_ticket, facts):
    _on(run, "reviewer")
    tid = _finished(proj, run, new_ticket)
    q = _draft(run, tid)
    _picked(proj, tid, q["id"])
    tickets.set_status(proj, tid, "review", "human:tester")
    res = reviewer.run(proj)
    (row,) = [a for a in res["actions"] if a["ticket"] == tid]
    assert row["verdict"] == "leave" and row["why"] == ownerpick.LEFT_WHY
    t = tickets.load(proj, tid)
    assert t["status"] == "review"
    assert t["history"][-1]["text"] == "Left for you by the Reviewer: " + ownerpick.LEFT_WHY
    with pytest.raises(Refused, match="This ticket carries a draft"):
        tickets.accept_for_owner(proj, tid, "looks fine")


def test_bug_fixes_are_still_accepted_by_the_reviewer(proj, run, new_ticket, facts):
    _on(run, "reviewer")
    tid = _finished(proj, run, new_ticket, "Fix the stale run record")
    tickets.set_status(proj, tid, "review", "human:tester")
    res = reviewer.run(proj)
    assert [a["verdict"] for a in res["actions"]] == ["accept"]
    assert tickets.load(proj, tid)["status"] == "done"


def test_the_second_look_never_queues_or_accepts_a_ticket_with_a_draft(
    proj, run, new_ticket, facts, monkeypatch
):
    _on(run, "reviewer", "reviewer_look")
    facts["files"] = [{"path": "workspace/src/orch_ui/static/orch.css", "additions": 4, "deletions": 1}]
    tid = _finished(proj, run, new_ticket)
    q = _draft(run, tid)
    _picked(proj, tid, q["id"])
    tickets.set_status(proj, tid, "review", "human:tester")
    res = reviewer.run(proj)
    assert [a["verdict"] for a in res["actions"]] == ["leave"]
    assert tid not in lookreview.read_state(proj)["line"]
    t = tickets.load(proj, tid)
    assert lookreview.triage(t, [facts], {"verdict": "leave", "why": "look"}, 0) is None
    # even when it was put in line before the draft came: the helper's accept and back are refused
    st = lookreview.read_state(proj)
    st["line"][tid] = {"why": "look", "at": "2026-11-18T00:00:00Z"}
    st["open"] = {"ticket": "t_helper", "items": [tid]}
    lookreview._write_state(proj, st)
    monkeypatch.setattr(worktrees, "_agent_ticket", lambda root: "t_helper")
    for word in ("accept", "back"):
        with pytest.raises(Refused, match="This ticket carries a draft"):
            lookreview.verdict(proj, tid, word, "fits", ["the page is built: shown"])
    assert tickets.load(proj, tid)["status"] == "review"
    assert lookreview.verdict(proj, tid, "leave", "a draft: the owner's")["verdict"] == "leave"


# ------------------------------------------------------------------ routine answers (and Away mode on top)


def test_routine_answers_never_answer_a_draft(proj, run, new_ticket, monkeypatch):
    _on(run, "reviewer_answers")
    tid = new_ticket("Flaky test in the run tests")
    q = _choose(proj, run, tid)
    later = time.time() + 3600
    ok, why = reviewer.routine(proj, tickets.load(proj, tid), _q(proj, tid, q["id"]), later)
    assert not ok and why == "a draft for you to pick"
    rows = reviewer.answer_routine(proj, now=later)
    assert [r["routine"] for r in rows] == [False] and _q(proj, tid, q["id"])["answer"] is None
    with pytest.raises(Refused, match="Only a person picks a draft"):
        tickets.answer_for_owner(
            proj, tid, q["id"], tickets.question_digest(_q(proj, tid, q["id"])), "routine"
        )


def test_a_direct_answer_without_proof_is_refused_for_any_actor(proj, run, new_ticket):
    """Away mode / the Auto Reviewer (ORCH-425) build on these calls: no person's proof, no answer."""
    tid = new_ticket()
    q = _draft(run, tid)
    for by in (ME, "human:owner"):
        with pytest.raises(Refused, match="Only a person picks a draft"):
            tickets.answer(proj, tid, q["id"], "ok", by, "dashboard")
    with pytest.raises(Refused):  # an agent never answers a card, proof or not
        tickets.answer(proj, tid, q["id"], "ok", "agent:reviewer", "dashboard", person=True)


# ------------------------------------------------------------------ the morning list


def test_the_morning_list_shows_waiting_for_your_pick_on_its_own(proj, run, new_ticket, facts):
    _on(run, "reviewer")
    fix = _finished(proj, run, new_ticket, "Fix the stale run record")
    tickets.set_status(proj, fix, "review", "human:tester")
    reviewer.run(proj)
    tid = new_ticket("Auto Reviewer page")
    _draft(run, tid, "Three looks for the Auto Reviewer")
    code, out, _ = run("review", "accepted", "--json")
    data = json.loads(out)
    assert [r["ticket"] for r in data["accepted"]] == [fix]
    assert [(r["ticket"], r["card"]) for r in data["waiting_pick"]] == [
        (tid, "Three looks for the Auto Reviewer")
    ]
    code, out, _ = run("review", "accepted")
    assert "Accepted for you today: 1 ticket" in out
    assert "Waiting for your pick: 1 draft" in out
    assert out.index("Waiting for your pick") > out.index("Accepted for you")
    part = out[out.index("Waiting for your pick") :]
    assert "Three looks for the Auto Reviewer" in part and "Fix the stale run record" not in part


def test_the_morning_list_with_only_a_draft_waiting(proj, run, new_ticket):
    tid = new_ticket("Auto Reviewer page")
    _draft(run, tid)
    code, out, _ = run("review", "accepted")
    assert (
        code == 0 and "Nothing was accepted for you today." in out and "Waiting for your pick: 1 draft" in out
    )
    code, out, _ = run("review", "accepted", "--phone", "--json")
    data = json.loads(out)
    assert data["sent"] is False and data.get(
        "not_sent"
    )  # a draft waiting is worth a message (no relay here)


def test_accepting_a_review_checks_the_draft_under_the_lock(proj, run, new_ticket):
    """The Check's snapshot may be older than the ticket: the write itself refuses a ticket with a draft."""
    tid = _finished(proj, run, new_ticket)
    q = _draft(run, tid)
    _picked(proj, tid, q["id"])
    tickets.set_status(proj, tid, "review", "human:tester")
    with pytest.raises(Refused, match="This ticket carries a draft"):
        tickets.accept_review(proj, tid, ME, "dashboard")
    assert tickets.load(proj, tid)["status"] == "review"
    tickets.accept_review(proj, tid, ME, "phone", person=True)
    assert tickets.load(proj, tid)["status"] == "done"


def test_an_unneeded_grant_is_used_up_and_never_reaches_a_child(proj, run, new_ticket, person_grant):
    import os

    from orch import renew

    tid = new_ticket()
    run("ask", tid, "Ship it?", "--option", "Yes", "--option", "No", "--by", "agent:x")
    person_grant(proj)
    code, out, err = run("answer", tid, "q1", "Yes", "--by", ME)
    assert code == 0, out + err
    assert renew.GRANT_ENV not in os.environ and renew.GRANT_ENV + "_FD" not in os.environ
    assert list(renew._grants(proj).iterdir()) == []  # the grant file is gone too


def test_human_review_needed_blocks_only_the_auto_reviewer_and_away_mode(proj, run, new_ticket, facts):
    """Owner 18 Nov (q2): the switch stays on by default; it blocks the Auto Reviewer and Away mode only."""
    _on(run, "reviewer")
    tid = _finished(proj, run, new_ticket, "Fix the stale run record")
    t = tickets.load(proj, tid)
    assert tickets.human_review(t)  # on by default
    with pytest.raises(Refused, match="Human review needed is on"):
        ownerpick.refuse_auto(t)
    tickets.set_human_review(proj, tid, False, "human:tester")
    ownerpick.refuse_auto(tickets.load(proj, tid))  # switch off, no draft: the Auto Reviewer may look
    q = _draft(run, tid)
    with pytest.raises(Refused, match="This ticket carries a draft"):
        ownerpick.refuse_auto(tickets.load(proj, tid))  # a draft wins over the switch
    # the plain Reviewer ignores the switch: a bug fix with Human review needed on is accepted
    fix = _finished(proj, run, new_ticket, "Fix the second stale record")
    assert tickets.human_review(tickets.load(proj, fix))
    tickets.set_status(proj, fix, "review", "human:tester")
    rows = {a["ticket"]: a["verdict"] for a in reviewer.run(proj)["actions"]}
    assert rows[fix] == "accept" and tickets.load(proj, fix)["status"] == "done"
    assert q["id"]


# ------------------------------------------------------------------ Done through the status commands


def test_a_script_cannot_finish_a_ticket_with_a_draft_through_status(proj, run, new_ticket, person_grant):
    tid = _finished(proj, run, new_ticket)
    q = _draft(run, tid)
    _picked(proj, tid, q["id"])
    tickets.set_status(proj, tid, "review", "human:tester")
    code, out, err = run("ticket", "status", tid, "done", "--by", ME)
    assert code == 2 and "This ticket carries a draft" in out + err
    rev = tickets.load(proj, tid)["revision"]
    code, out, err = run(
        "ticket", "patch", tid, json.dumps({"status": "done"}), f"--if-revision={rev}", "--by", ME
    )
    assert code == 2 and "This ticket carries a draft" in out + err
    assert tickets.load(proj, tid)["status"] == "review"
    person_grant(proj)  # the signed-in dashboard's Done
    code, out, err = run(
        "ticket", "patch", tid, json.dumps({"status": "done"}), f"--if-revision={rev}", "--by", ME
    )
    assert code == 0, out + err
    assert tickets.load(proj, tid)["status"] == "done"


def test_an_agent_done_on_a_ticket_with_a_draft_goes_to_check_even_when_agents_may_finish(
    proj, run, new_ticket, monkeypatch
):
    _on(run, "agents_may_finish")
    tid = _finished(proj, run, new_ticket)
    q = _draft(run, tid)
    _picked(proj, tid, q["id"])
    t = tickets.set_status(proj, tid, "done", "agent:claude")
    assert t["status"] == "review"
    assert tickets.DRAFT_TO_CHECK in t["history"][-1]["text"]
    plain = _finished(proj, run, new_ticket, "Fix the stale run record")
    assert tickets.set_status(proj, plain, "done", "agent:claude")["status"] == "done"  # no draft: as before


def test_a_person_finishes_a_plain_ticket_from_the_terminal_as_before(proj, run, new_ticket):
    tid = _finished(proj, run, new_ticket, "Fix the stale run record")
    code, out, err = run("ticket", "status", tid, "done", "--by", ME)
    assert code == 0, out + err
    assert tickets.load(proj, tid)["status"] == "done"
