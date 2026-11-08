"""Ticket lifecycle against the real agent state (round 8 Nov, B1): Working only while an agent runs,
answering a question resumes the agent, a session on a finished ticket stays warm, no early finish."""

import json
import os
import time

import pytest
import test_run_wrap

from orch import phone_view, runs, runs_live, tickets
from orch.errors import Refused

gen = test_run_wrap.gen  # the generic fake agent as the folder's agent (a fixture)
_wait = test_run_wrap._wait

pytestmark = pytest.mark.skipif(os.name == "nt", reason="detached wrapper tests use shell stubs")


_REAL_RESUME = runs_live.resume_after_answer


@pytest.fixture
def one_step(monkeypatch):
    """No tmux here: every run is one step at a time (the background mode); answers start the fake agent."""
    monkeypatch.setattr(runs_live, "available", lambda adapter: False)
    monkeypatch.setattr(runs_live, "resume_after_answer", _REAL_RESUME)


def _new(run, title="Make the report"):
    return json.loads(run("ticket", "new", title, "--json", "--by", "human:t")[1])["id"]


def _ask(run, tid, text="Which colour?", *opts, by="agent:fake"):
    args = ["ask", tid, text]
    for o in opts:
        args += ["--option", o]
    code, out, err = run(*args, "--by", by, "--json")
    assert code == 0, err
    return json.loads(out)["id"]


def _status(proj, tid):
    return tickets.load(proj, tid)["status"]


def _texts(proj, tid):
    return [h["text"] for h in tickets.load(proj, tid)["history"]]


# ---------------------------------------------------------------- fb9: Working only while an agent runs


def test_a_run_that_ends_without_finishing_leaves_the_ticket_ready_not_working(proj, run, gen, one_step):
    gen("--silent 0.2")  # works without touching the ticket, then ends
    tid = _new(run)
    assert run("run", "start", tid)[0] == 0
    assert _status(proj, tid) == "active"
    _wait(proj, tid)
    assert _status(proj, tid) == "ready"  # nobody works on it now: not "Working"
    assert any("agent stopped" in t for t in _texts(proj, tid))


def test_a_run_that_asked_a_question_stays_waiting(proj, run, gen, one_step):
    gen("--silent 0.2")
    tid = _new(run)
    run("run", "start", tid)
    _ask(run, tid)
    _wait(proj, tid)
    assert _status(proj, tid) == "waiting"


def test_stop_leaves_the_ticket_ready(proj, run, gen, one_step):
    gen("--silent 5")
    tid = _new(run)
    run("run", "start", tid)
    _wait(proj, tid, gone=False)
    assert run("run", "stop", tid)[0] == 0
    _wait(proj, tid)
    assert _status(proj, tid) == "ready"


def test_a_working_ticket_with_no_agent_is_settled_by_the_next_status_check(proj, run):
    tid = _new(run)
    tickets.set_status(proj, tid, "active", "human:t")  # e.g. a phone text moved it, no agent came
    t = tickets.load(proj, tid)
    t["updated_at"] = runs._iso(time.time() - 5 * 60)
    tickets._write(proj, t)
    run("run", "status", tid, "--json")  # the dashboard asks this every few seconds
    assert _status(proj, tid) == "ready"


def test_a_fresh_working_ticket_gets_a_moment_for_its_agent_to_start(proj, run):
    tid = _new(run)
    tickets.set_status(proj, tid, "active", "human:t")
    run("run", "status", tid, "--json")
    assert _status(proj, tid) == "active"


def test_the_phone_view_changes_when_the_agent_stops(proj, run):
    tid = _new(run)
    rec = runs.claim(proj, tid, "human:t", "fake", "oneshot", pid=os.getpid())
    before = phone_view._tasks_sig(tickets.load(proj, tid), proj)
    runs.release(proj, tid, rec["run"])
    assert phone_view._tasks_sig(tickets.load(proj, tid), proj) != before  # the phone gets "not running"


# ---------------------------------------------------------------- fb9: an answer resumes the agent


def test_answering_the_agents_question_starts_the_agent_again(proj, run, gen, one_step):
    log = gen()
    tid = _new(run)
    run("check", "add", tid, "Paint the banner", "--by", "human:t")
    qid = _ask(run, tid, "Which colour?", "Blue", "Red")
    assert _status(proj, tid) == "waiting" and runs.read(proj, tid) is None
    code, _, err = run("answer", tid, qid, "Blue", "--by", "human:t")
    assert code == 0, err
    assert runs.read(proj, tid) is not None  # no click on Continue needed
    _wait(proj, tid)
    prompt = log.read_text(encoding="utf-8")
    assert "Answered q1: Blue" in prompt
    assert tickets.load(proj, tid)["checklist"][0]["done"] is True  # the agent went on with the work


def test_no_agent_starts_while_other_questions_are_open(proj, run, gen, one_step):
    gen()
    tid = _new(run)
    q1 = _ask(run, tid, "Which colour?")
    q2 = _ask(run, tid, "Which size?")
    run("answer", tid, q2, "Big", "--by", "human:t")
    assert runs.read(proj, tid) is None
    t = tickets.load(proj, tid)
    assert t["status"] == "waiting" and t["waiting_on"] == {"kind": "question", "ref": q1}
    run("answer", tid, q1, "Blue", "--by", "human:t")
    assert runs.read(proj, tid) is not None
    _wait(proj, tid)


def test_an_answer_to_a_persons_own_question_starts_nothing_and_is_not_working(proj, run, gen, one_step):
    gen()
    tid = _new(run)
    qid = _ask(run, tid, "Who pays?", by="human:boss")
    run("answer", tid, qid, "We do", "--by", "human:t")
    assert runs.read(proj, tid) is None and _status(proj, tid) == "ready"


def test_an_add_on_question_is_left_to_its_add_on(proj, run, gen, one_step):
    gen()
    tid = _new(run)
    code, out, _ = run(
        "ask", tid, "Try again?", "--kind", "automation:failure", "--by", "agent:fake", "--json"
    )
    run("answer", tid, json.loads(out)["id"], "Try again", "--by", "human:t")
    assert runs.read(proj, tid) is None


def test_an_answer_while_the_agent_runs_goes_in_as_input_no_second_agent(proj, run, gen, one_step):
    log = gen("--silent 1.5")
    tid = _new(run)
    qid = _ask(run, tid)
    run("run", "start", tid)
    _wait(proj, tid, gone=False)
    first = runs.read(proj, tid)["run"]
    run("answer", tid, qid, "Blue", "--by", "human:t")
    assert runs.read(proj, tid)["run"] == first
    _wait(proj, tid)
    assert sum("Answer to your question q1" in ln for ln in log.read_text().splitlines()) == 1


# ---------------------------------------------------------------- fb4: Continue on a finished ticket


def test_continue_on_a_review_ticket_keeps_the_live_session_for_the_hour(proj, run, monkeypatch):
    monkeypatch.setattr(runs_live, "_close", lambda root, rec, interrupt: None)
    monkeypatch.setattr(runs_live, "start_waiting", lambda root: None)
    monkeypatch.delenv("ORCH_RUN_IDLE_SECONDS", raising=False)
    tid = _new(run)
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    rec["live"] = {"state": "idle", "since": runs._iso(time.time() - 30 * 60)}
    runs._write(proj, rec)
    tickets.set_status(proj, tid, "review", "human:t")
    assert runs_live.cleanup(proj) == []  # 30 min idle on a Review ticket: still open
    rec["live"]["since"] = runs._iso(time.time() - 61 * 60)
    runs._write(proj, rec)
    assert runs_live.cleanup(proj) == [tid]


# ---------------------------------------------------------------- never finish too early


def test_an_agent_cannot_finish_while_its_question_is_open(proj, run):
    tid = _new(run)
    _ask(run, tid)
    with pytest.raises(Refused, match="q1 is not answered"):
        tickets.set_status(proj, tid, "done", "agent:fake")
    assert _status(proj, tid) == "waiting"


def test_an_agent_cannot_finish_while_new_input_waits_for_it(proj, run):
    tid = _new(run)
    runs.pending_add(proj, tid, "human:t", "message", "Also add October")
    with pytest.raises(Refused, match="new input"):
        tickets.set_status(proj, tid, "review", "agent:fake")
    tickets.set_status(proj, tid, "done", "human:t")  # a person still can
    assert _status(proj, tid) == "done"


def test_an_answer_given_in_the_dashboard_resumes_the_agent(proj, run, gen, one_step):
    """testnet: the dashboard answers through `orch answer ... --via dashboard --by human:<who> --json`."""
    log = gen()
    tid = _new(run)
    qid = _ask(run, tid, "Which day?", "Monday", "Friday")
    argv = ["answer", tid, qid, "Friday", "--via", "dashboard", "--by", "human:dashboard", "--json"]
    code, _, err = run(*argv)
    assert code == 0, err
    assert runs.read(proj, tid) is not None
    _wait(proj, tid)
    assert "Answered q1: Friday" in log.read_text(encoding="utf-8")
