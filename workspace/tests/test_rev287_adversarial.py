"""Opus security review of PR #287 (adversarial). Copy into workspace/tests/ and run:
    uv run pytest -q tests/test_rev287_adversarial.py -p no:cacheprovider
Tests named *_SHOULD_* assert the secure/expected behaviour and FAIL on fc4c446 (findings);
the others pin behaviour that is already right."""

import json
import os
import shlex
import sys
import time

import pytest
import test_lifecycle as L
import test_run_wrap

from orch import config, relay, runs, tickets

gen = test_run_wrap.gen
one_step = L.one_step
_wait = test_run_wrap._wait

pytestmark = pytest.mark.skipif(os.name == "nt", reason="detached wrapper tests use shell stubs")


# ---------------------------------------------- F1: actor spoof starts an agent / answers phones


def test_F1_agent_env_with_by_human_SHOULD_count_as_agent(proj, run, gen, one_step, monkeypatch):
    """An agent process (ORCH_AGENT set, as in every run) answers its own question as --by human:owner.
    _finish_status forces agent: under an agent env; `orch answer` does not, so the answer is recorded as the
    owner's and (new in #287) starts the agent again with nobody having answered."""
    gen()
    tid = L._new(run)
    qid = L._ask(run, tid, "May I delete the old reports?", "Yes", "No")
    monkeypatch.setenv("ORCH_AGENT", "fake")
    code, _, err = run("answer", tid, qid, "Yes", "--by", "human:owner")
    monkeypatch.delenv("ORCH_AGENT")
    q = tickets.load(proj, tid)["questions"][0]
    started = runs.read(proj, tid) is not None
    if started:
        _wait(proj, tid)
    assert q["answered_by"].startswith("agent:") and not started, (q["answered_by"], started)


def test_F1b_agent_env_SHOULD_not_answer_a_phone_question_as_human(proj, run, monkeypatch):
    """Same spoof against the existing guard 'This question was sent to the phones. Only a human answers
    it.'"""
    tid = L._new(run)
    qid = L._ask(run, tid, "Pay the invoice?", "Yes", "No")
    monkeypatch.setattr(relay, "asked_to_phones", lambda root, t, q: True)
    monkeypatch.setenv("ORCH_AGENT", "fake")
    code, _, err = run("answer", tid, qid, "Yes", "--by", "human:owner")
    assert code != 0, "an agent answered a phone question by claiming to be human"


# ---------------------------------------------- F2: resume starts the default agent, not the asker


def test_F2_resume_SHOULD_start_the_agent_that_asked(proj, run, gen, one_step):
    gen()  # 'fake' is the workspace agent
    cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(test_run_wrap.AGENT))} {{prompt}}"
    config.add_agent(proj, "other", cmd, approve=True)
    tid = L._new(run)
    assert run("run", "start", tid, "--agent", "other")[0] == 0
    _wait(proj, tid)
    qid = L._ask(run, tid, "Which colour?", by="agent:other")
    run("answer", tid, qid, "Blue", "--by", "human:t")
    rec = runs.read(proj, tid)
    agent = rec and rec.get("agent")
    if rec:
        _wait(proj, tid)
    assert agent == "other", f"the answer resumed {agent!r}, not the agent that asked (other)"


# ------------------------------------------------------------- F3: a peer workspace labels its answer human


def test_F3_peer_workspace_answer_is_labelled_agent_never_human():
    """_answer_by: a peer (not ph_/sub_) may send answered_by human:<anything>; it is recorded as
    agent:<peer>, so a peer's own label never decides that a person answered (which starts the agent)."""
    by, via = relay._answer_by({"from": "ws_peer", "body": {"answered_by": "human:owner"}})
    assert (by, via) == ("agent:ws_peer", "relay")
    by, _ = relay._answer_by({"from": "ws_peer", "body": {"answered_by": "agent:claude"}})
    assert by == "agent:claude"


# ------------------------------------------------------------- things that hold


def test_agent_answer_starts_nothing(proj, run, gen, one_step):
    gen()
    tid = L._new(run)
    qid = L._ask(run, tid)
    run("answer", tid, qid, "Blue", "--by", "agent:other")
    assert runs.read(proj, tid) is None


def test_answer_on_dropped_ticket_starts_nothing(proj, run, gen, one_step):
    gen()
    tid = L._new(run)
    qid = L._ask(run, tid)
    tickets.set_status(proj, tid, "dropped", "human:t")
    run("answer", tid, qid, "Blue", "--by", "human:t")
    assert runs.read(proj, tid) is None


def test_forged_history_line_by_a_person_does_not_count_as_agent_question(proj, run, gen, one_step):
    gen()
    tid = L._new(run)
    qid = L._ask(run, tid, by="human:boss")
    tickets.log(proj, tid, f"Asked {qid}, waiting", "human:x")  # a log line that looks like an ask
    run("answer", tid, qid, "Blue", "--by", "human:t")
    assert runs.read(proj, tid) is None


def test_SHOULD_agent_log_line_not_make_a_persons_question_resume(proj, run, gen, one_step):
    """_asked_by_agent matches any agent-authored history line starting 'Asked q1' - an agent's `orch log`
    text is enough; the question record itself (who asked) is not stored. Low."""
    gen()
    tid = L._new(run)
    qid = L._ask(run, tid, by="human:boss")
    tickets.log(proj, tid, f"Asked {qid} the boss about the budget", "agent:fake")
    run("answer", tid, qid, "Blue", "--by", "human:t")
    started = runs.read(proj, tid) is not None
    if started:
        _wait(proj, tid)
    assert not started


def test_settle_orphan_never_flips_a_ticket_whose_run_is_claimed(proj, run):
    tid = L._new(run)
    runs.claim(proj, tid, "human:t", "fake", "oneshot", pid=os.getpid())
    t = tickets.load(proj, tid)
    t["updated_at"] = runs._iso(time.time() - 10 * 60)
    tickets._write(proj, t)
    assert runs.settle_orphan(proj, tid) is False
    assert tickets.load(proj, tid)["status"] == "active"


def test_settle_orphan_makes_a_runless_ticket_ready_and_keeps_its_queued_input(proj, run):
    """Changed by the delta-6 decision: a run-less Working ticket is Ready after the grace whatever waits;
    the input stays queued (the automation host starts the next run for it)."""
    tid = L._new(run)
    tickets.set_status(proj, tid, "active", "human:t")
    runs.pending_add(proj, tid, "human:t", "message", "Also add October")
    t = tickets.load(proj, tid)
    t["updated_at"] = runs._iso(time.time() - 10 * 60)
    tickets._write(proj, t)
    assert runs.settle_orphan(proj, tid) is True
    assert tickets.load(proj, tid)["status"] == "ready" and runs.undelivered(proj, tid)


def test_settle_under_lock_sees_a_run_that_claimed_meanwhile(proj, run, monkeypatch):
    """agent_stopped asks still_running() inside the ticket lock: a claim that lands first wins.
    (mark_working needs the ticket lock we are inside, so it is skipped here; claim's record write is what
    counts.)"""
    monkeypatch.setattr(tickets, "mark_working", lambda *a, **k: None)
    tid = L._new(run)
    tickets.set_status(proj, tid, "active", "human:t")
    calls = []

    def still():
        calls.append(1)
        runs.claim(proj, tid, "human:t", "fake", "oneshot", pid=os.getpid()) if len(calls) == 1 else None
        return runs.running(proj, tid)

    assert tickets.agent_stopped(proj, tid, "orch", still) is False
    assert tickets.load(proj, tid)["status"] == "active"


def test_agent_finish_via_patch_is_also_refused_with_open_question(proj, run):
    tid = L._new(run)
    L._ask(run, tid)
    from orch.errors import Refused

    with pytest.raises(Refused, match="not answered"):
        rev = tickets.load(proj, tid)["revision"]
        tickets.patch(proj, tid, rev, json.dumps({"status": "review"}), "agent:fake")


def test_agent_env_cannot_finish_with_open_question_even_with_by_human(proj, run, monkeypatch):
    tid = L._new(run)
    L._ask(run, tid)
    monkeypatch.setenv("ORCH_AGENT", "fake")
    code, _, err = run("ticket", "status", tid, "done", "--by", "human:owner")
    assert code != 0 and L._status(proj, tid) == "waiting", err
