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


def test_a_live_session_that_ends_with_input_and_no_restart_is_ready_with_the_input_kept(
    proj, run, monkeypatch
):
    """F5 (delta-3): no next run can come: Ready (never Working with nobody), the input stays queued."""
    import sys

    monkeypatch.setattr(runs, "restart_for_input", lambda *a: False)
    tid = _new(run)
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    runs.pending_add(proj, tid, "human:t", "answer", "Answer to your question q1: Blue")
    runs.wrap_live(proj, rec["run"], tid, "claude", [sys.executable, "-c", "pass"], None)
    assert runs.read(proj, tid) is None and _status(proj, tid) == "ready"
    assert [i["text"] for i in runs.undelivered(proj, tid)] == ["Answer to your question q1: Blue"]


def test_two_pulls_at_once_send_one_result(proj, run, monkeypatch):
    """F6 (review #287): phone-views.json is read, changed and written under its lock; a result goes once."""
    import threading

    from orch import relay

    got = []
    monkeypatch.setattr(
        relay, "send_text", lambda root, to, text, tid, kind, **k: got.append(kind) or time.sleep(0.2)
    )
    tid = _new(run)
    monkeypatch.setattr(phone_view, "_tasks_sig", lambda t, root=None: t.get("status"))
    phone_view.update_state(
        proj,
        lambda st: st["tickets"].update({tid: {"to": "phones", "sig": "open", "at": 0, "status": "open"}}),
    )
    tickets.set_status(proj, tid, "review", "human:t")
    ts = [threading.Thread(target=phone_view.sync, args=(proj,)) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert got == ["result"]


def test_a_result_that_could_not_be_sent_is_pushed_on_the_next_pull(proj, run, monkeypatch):
    """F6 (delta review): a failed send undoes the claim, status too, so the retry is a result again."""
    from orch import relay

    tid = _new(run)
    phone_view.update_state(
        proj, lambda st: st["tickets"].update({tid: {"to": "phones", "sig": "x", "at": 0, "status": "open"}})
    )
    tickets.set_status(proj, tid, "review", "human:t")
    calls = []

    def flaky(root, to, text, t, kind, **k):
        calls.append(kind)
        if len(calls) == 1:
            raise Refused("The relay could not be reached.")

    monkeypatch.setattr(relay, "send_text", flaky)
    assert phone_view.sync(proj) == []
    assert phone_view.sync(proj) == [tid] and calls == ["result", "result"]


def test_a_busy_state_file_after_a_send_does_not_fail_the_send(proj, run, monkeypatch):
    tid = _new(run)

    def busy(root, fn):
        raise Refused("The phone view state is busy. Try again in a moment.")

    monkeypatch.setattr(phone_view, "update_state", busy)
    phone_view.remember(proj, tid, "phones")  # no exception: the message already went out


def test_a_stale_state_lock_is_broken_and_a_fresh_one_is_kept(proj):
    lock = phone_view.net.secrets_dir(proj) / "phone-views.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("")
    os.utime(lock, (time.time() - 60, time.time() - 60))
    assert phone_view._break_stale_lock(lock) is True and not lock.exists()
    lock.write_text("")
    assert phone_view._break_stale_lock(lock) is False and lock.exists()


class _Child:
    """A stand-in for the detached `orch run start`: it claims the ticket (a run started) or ends without."""

    def __init__(self, proj, tid, claims: bool):
        self.claimed = claims and runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())

    def poll(self):
        return 0


def _spawns(monkeypatch, proj, claims=True):
    calls = []

    def spawn(root, argv, env):
        calls.append((argv, env))
        tid = argv[argv.index("start") + 1]
        return _Child(proj, tid, claims)

    monkeypatch.setattr(runs, "_spawn_detached", spawn)
    monkeypatch.setattr(runs, "RESTART_WAIT_SECONDS", 1)
    return calls


def test_a_live_session_that_ends_with_input_waiting_starts_the_next_run_once(proj, run, monkeypatch):
    """F5: the next run starts by itself (same path as Continue), once per waiting item."""
    import sys

    started = _spawns(monkeypatch, proj)
    tid = _new(run)
    states = []
    for _ in range(2):  # the second time the same item waits: an agent that quits at once is not restarted
        rec = runs.read(proj, tid) or runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
        if not runs.undelivered(proj, tid):
            runs.pending_add(proj, tid, "human:t", "answer", "Answer to your question q1: Blue")
        runs.wrap_live(proj, rec["run"], tid, "claude", [sys.executable, "-c", "pass"], None)
        states.append(_status(proj, tid))
    assert len(started) == 1
    assert started[0][0][-7:] == ["run", "start", tid, "--agent", "claude", "--by", "human:t"]
    # Working while the next run holds it; Ready once no further run will come (input still queued)
    assert states == ["active", "ready"] and runs.undelivered(proj, tid)


def test_a_stopped_live_session_does_not_start_again(proj, run, monkeypatch):
    import sys

    started = _spawns(monkeypatch, proj)
    tid = _new(run)
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    runs.pending_add(proj, tid, "human:t", "message", "One more thing")
    rec = runs.read(proj, tid)
    rec["stop_requested"] = tickets.now()
    runs._write(proj, rec)
    runs.wrap_live(proj, rec["run"], tid, "claude", [sys.executable, "-c", "pass"], None)
    assert started == []


def _ended_live(proj, tid, text="Answer to your question q1: Blue"):
    import sys

    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    if text:
        runs.pending_add(proj, tid, "human:t", "answer", text)
    runs.wrap_live(proj, rec["run"], tid, "claude", [sys.executable, "-c", "pass"], None)


def test_a_failed_restart_can_be_tried_again(proj, run, monkeypatch):
    """A spawn that did not start clears the mark, so the waiting answer can start the agent."""
    tries = []
    monkeypatch.setattr(runs, "_spawn_detached", lambda root, argv, env: tries.append(argv) and None)
    tid = _new(run)
    _ended_live(proj, tid)
    assert len(tries) == 1 and not any(i.get("restarted") for i in runs.undelivered(proj, tid))
    assert _status(proj, tid) == "ready"  # nobody will read it now: Ready, the input stays queued


def test_a_start_that_was_refused_clears_its_own_marks_in_the_wrapper(proj, run, monkeypatch):
    """INVARIANT: the ending run's wrapper sees no claim come (the child was refused or died) and clears its
    own marks and settles, right there; no CLI path is involved."""
    _spawns(monkeypatch, proj, claims=False)
    tid = _new(run)
    _ended_live(proj, tid)
    assert _status(proj, tid) == "ready" and runs.read(proj, tid) is None
    assert not any(i.get("restarted") for i in runs.undelivered(proj, tid))


def test_a_broken_adapter_list_leaves_the_ticket_settled_and_no_marks(proj, run, monkeypatch):
    """Delta-3 (1): an error while preparing the restart never escapes and never leaves marks behind."""
    from orch import adapters

    monkeypatch.setattr(adapters, "human_environ", lambda environ: (_ for _ in ()).throw(RuntimeError("bad")))
    tid = _new(run)
    _ended_live(proj, tid)
    assert _status(proj, tid) == "ready" and runs.read(proj, tid) is None
    assert not any(i.get("restarted") for i in runs.undelivered(proj, tid))


def test_a_spawn_that_raises_clears_the_marks(proj, run, monkeypatch):
    monkeypatch.setattr(runs, "_spawn_detached", lambda root, argv, env: (_ for _ in ()).throw(OSError("x")))
    monkeypatch.setattr(runs, "RESTART_WAIT_SECONDS", 1)
    tid = _new(run)
    _ended_live(proj, tid)
    assert _status(proj, tid) == "ready"
    assert not any(i.get("restarted") for i in runs.undelivered(proj, tid))


def test_no_cli_flag_or_variable_touches_restart_marks(proj, run):
    """INVARIANT: only runs.restart_for_input / clear_restarted / settle_orphan name the mark;
    `orch run start` has no restart flag, and no orch module reads a restart variable."""
    import argparse
    import pathlib
    import re

    from orch import cli

    src = pathlib.Path(runs.__file__).parent
    for f in src.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        if f.name != "runs.py":
            assert '"restarted"' not in text and "clear_restarted" not in text, f.name
        assert not re.search(r"environ[^\n]*restart|ORCH_RESTART", text), f.name
    parser = cli.build_parser() if hasattr(cli, "build_parser") else None
    if parser is not None:
        sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        run_sub = next(a for a in sub.choices["run"]._actions if isinstance(a, argparse._SubParsersAction))
        assert not any("--restart" in o for a in run_sub.choices["start"]._actions for o in a.option_strings)
    with pytest.raises(SystemExit):  # an unknown option
        run("run", "start", "t_abcdefg", "--restart")


def test_a_lock_timeout_in_the_restart_still_settles(proj, run, monkeypatch):
    """Delta-4 (1): any error inside the restart (here the run lock) never leaves the ticket Working."""
    from orch.errors import Refused as R

    def busy(*a, **k):
        raise R("Ticket is busy (retried for 10 s). Try again.")

    import sys

    tid = _new(run)
    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    runs.pending_add(proj, tid, "human:t", "answer", "Answer to your question q1: Blue")
    monkeypatch.setattr(runs, "_pending_write", busy)
    runs.wrap_live(proj, rec["run"], tid, "claude", [sys.executable, "-c", "pass"], None)
    assert _status(proj, tid) == "ready"


def test_a_restart_that_never_came_is_settled_by_the_next_status_check(proj, run):
    """Delta-4 (1): the spawned start died before it began: after the grace the ticket is Ready again."""
    tid = _new(run)
    tickets.set_status(proj, tid, "active", "human:t")
    runs.pending_add(proj, tid, "human:t", "answer", "Answer to your question q1: Blue")
    items = runs._pending_read(proj, tid)
    items[0]["restarted"] = runs._iso(time.time() - 600)
    runs._pending_write(proj, tid, items)
    assert runs.settle_orphan(proj, tid, at=time.time() + 600) is True
    assert _status(proj, tid) == "ready" and not runs.undelivered(proj, tid)[0].get("restarted")


def test_a_new_message_restarts_even_after_an_earlier_one_did(proj, run, monkeypatch):
    """The once-only mark is per item, not for every later message."""
    started = _spawns(monkeypatch, proj, claims=False)  # nobody claims: each restart is cleared again...
    tid = _new(run)
    _ended_live(proj, tid)
    _ended_live(proj, tid, text="One more thing")
    assert len(started) == 2  # ...so both ends try once more for what still waits


def test_the_restart_is_not_the_ended_runs_own_call(proj, run, monkeypatch):
    """The detached start gets no agent or run variables and no restart trigger at all."""
    calls = _spawns(monkeypatch, proj)
    for k, v in {
        "ORCH_RUN": "r_abcdefgh",
        "ORCH_TICKET": "t_abcdef",
        "ORCH_AGENT": "claude",
        "CLAUDECODE": "1",
        "ORCH_VIA": "dashboard",
    }.items():
        monkeypatch.setenv(k, v)
    tid = _new(run)
    _ended_live(proj, tid)
    ((argv, env),) = calls
    assert not {"ORCH_RUN", "ORCH_TICKET", "ORCH_AGENT", "CLAUDECODE", "ORCH_VIA"} & set(env)
    assert not any("restart" in a for a in argv)


def test_no_ready_flicker_while_the_restart_is_on_its_way(proj, run, monkeypatch):
    """Delta F5-2: settle is skipped when the next run was started."""
    _spawns(monkeypatch, proj)
    called = []
    monkeypatch.setattr(runs, "settle", lambda *a, **k: called.append(a))
    tid = _new(run)
    _ended_live(proj, tid)
    assert called == []


@pytest.mark.skipif(not hasattr(os, "waitid"), reason="os.waitid is not available here")
def test_kill_tree_keeps_the_exit_status_of_our_child():
    """R1: kill_tree looks at its ended child without reaping it (a reaped Popen reports 0)."""
    import subprocess

    p = subprocess.Popen(["sleep", "30"], start_new_session=True)
    time.sleep(0.1)
    runs.kill_tree(p.pid)
    assert p.wait(timeout=5) < 0


def test_the_state_lock_leaves_a_later_holders_lock_alone(proj):
    """Delta F6-1: a holder whose lock was taken away never deletes the lock someone else made since."""
    lock = phone_view.net.secrets_dir(proj) / "phone-views.lock"
    with phone_view._state_locked(proj):
        lock.unlink()
        lock.write_text("someone-else")
    assert lock.read_text() == "someone-else"


def test_a_failed_send_does_not_undo_a_newer_claim(proj, run, monkeypatch):
    """Delta F6-2: the undo is compare and set on the claimed signature."""
    from orch import relay

    tid = _new(run)
    phone_view.update_state(
        proj, lambda st: st["tickets"].update({tid: {"to": "phones", "sig": "x", "at": 0, "status": "open"}})
    )
    tickets.set_status(proj, tid, "review", "human:t")

    def newer_then_fail(root, to, text, t, kind, **k):
        phone_view.update_state(root, lambda st: st["tickets"][t].update(sig="newer", status="review"))
        raise Refused("The relay could not be reached.")

    monkeypatch.setattr(relay, "send_text", newer_then_fail)
    phone_view.sync(proj)
    rec = phone_view.load_state(proj)["tickets"][tid]
    assert rec["sig"] == "newer" and rec["status"] == "review"


def test_an_undo_never_leaves_a_status_of_none(proj, run, monkeypatch):
    """Delta F6-3: a ticket first seen with no status before: the key is removed, not set to None."""
    from orch import relay

    tid = _new(run)
    phone_view.update_state(
        proj, lambda st: st["tickets"].update({tid: {"to": "phones", "sig": "x", "at": 0}})
    )
    monkeypatch.setattr(relay, "send_text", lambda *a, **k: (_ for _ in ()).throw(Refused("away")))
    phone_view.sync(proj)
    assert "status" not in phone_view.load_state(proj)["tickets"][tid]


def test_an_undo_in_the_status_branch_only_undoes_its_own_claim(proj, run, monkeypatch):
    """Delta-3 (4): a later pass that claimed the same status keeps its claim when an older send fails."""
    from orch import mobile_mode, relay

    monkeypatch.setattr(mobile_mode, "routes_to_phone", lambda root: True)
    tid = _new(run)
    phone_view.sync(proj)  # first look
    tickets.set_status(proj, tid, "review", "human:t")

    def later_claim_then_fail(root, to, text, t, kind, **k):
        phone_view.update_state(root, lambda st: st.setdefault("claims", {}).update({t: "someone-else"}))
        raise Refused("The relay could not be reached.")

    monkeypatch.setattr(relay, "send_text", later_claim_then_fail)
    phone_view.sync(proj)
    st = phone_view.load_state(proj)
    assert st["status"][tid] == "review" and st["claims"][tid] == "someone-else"
