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


def _status_soon(proj, tid, want, timeout=10.0):
    """The wrapper settles the ticket right after it releases the claim: wait for that moment, not a race."""
    end = time.monotonic() + timeout
    while _status(proj, tid) != want and time.monotonic() < end:
        time.sleep(0.05)
    return _status(proj, tid)


def _texts(proj, tid):
    return [h["text"] for h in tickets.load(proj, tid)["history"]]


# ---------------------------------------------------------------- fb9: Working only while an agent runs


def test_a_run_that_ends_without_finishing_leaves_the_ticket_ready_not_working(proj, run, gen, one_step):
    gen("--silent 0.2")  # works without touching the ticket, then ends
    tid = _new(run)
    assert run("run", "start", tid)[0] == 0
    assert _status(proj, tid) == "active"
    _wait(proj, tid)
    assert _status_soon(proj, tid, "ready") == "ready"  # nobody works on it now: not "Working"
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
    code, _, err = run("run", "stop", tid)
    assert code == 0, err
    _wait(proj, tid)
    assert _status_soon(proj, tid, "ready") == "ready"


def _stop_a_run(proj, run, tid):
    import subprocess
    import sys

    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        runs.claim(proj, tid, "human:t", "fake", "oneshot", pid=p.pid)
        code, _, err = run("run", "stop", tid)
        assert code == 0, err
    finally:
        p.kill()
        p.wait()


def test_run_stop_with_waiting_input_holds_it_from_the_automation(proj, run):
    """A person's stop while their input waits: that input does not restart the ticket (stop_held_ids, read by
    the automation host). New input after the stop is not held; a stop with nothing waiting holds nothing."""
    tid = _new(run)
    first = runs.pending_add(proj, tid, "human:owner", "message", "one more thing")
    _stop_a_run(proj, run, tid)
    st = json.loads(run("run", "status", tid, "--json")[1])
    assert st["human_pending_ids"] == [first["id"]] and st["stop_held_ids"] == [first["id"]]
    later = runs.pending_add(proj, tid, "human:owner", "message", "and this")  # new input: not held
    st = json.loads(run("run", "status", tid, "--json")[1])
    assert st["human_pending_ids"] == [first["id"], later["id"]] and st["stop_held_ids"] == [first["id"]]
    items = runs._pending_read(proj, tid)  # a run read everything that waited
    for i in items:
        i["delivered_at"] = tickets.now()
    runs._pending_write(proj, tid, items)
    _stop_a_run(proj, run, tid)  # a second stop, nothing waiting: no hold
    assert not runs_live._held_path(proj, tid).exists()
    assert json.loads(run("run", "status", tid, "--json")[1])["stop_held_ids"] == []


def _held(run, tid):
    code, out, err = run("run", "status", tid, "--json")
    assert code == 0, err
    return json.loads(out)["stop_held_ids"]


def test_an_explicit_start_after_a_stop_clears_the_hold(proj, run, gen, one_step):
    """H1: a person's (CLI) start ends the hold; the automation's own start (--by agent:automation) keeps
    it."""
    gen("--silent 0.2")
    tid = _new(run)
    first = runs.pending_add(proj, tid, "human:owner", "message", "one more thing")
    _stop_a_run(proj, run, tid)
    path = runs_live._held_path(proj, tid)
    assert path.exists()
    assert run("run", "start", tid, "--by", runs_live.AUTOMATION_BY)[0] == 0
    _wait(proj, tid)
    assert path.exists()
    runs_live._write_held(proj, tid, [first["id"]])
    assert run("run", "start", tid, "--by", "human:t")[0] == 0
    _wait(proj, tid)
    assert not path.exists()


def test_only_a_person_stop_with_a_run_sets_a_hold(proj, run):
    """H2: the default stop (automation, idle cleanup, run end, a close) holds nothing; a CLI stop with no run
    record holds nothing either."""
    import subprocess
    import sys

    tid = _new(run)
    runs.pending_add(proj, tid, "human:owner", "message", "one more thing")
    path = runs_live._held_path(proj, tid)
    assert run("run", "stop", tid)[0] == 0  # nothing runs: no record, no hold
    assert not path.exists() and _held(run, tid) == []
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        runs.claim(proj, tid, "human:t", "fake", "oneshot", pid=p.pid)
        assert runs_live.stop(proj, tid) is True
    finally:
        p.kill()
        p.wait()
    assert not path.exists() and _held(run, tid) == []


def test_a_hold_that_can_not_be_written_never_breaks_the_stop(proj, run):
    """H3: the stop-held folder is a file (mkdir fails), or the write fails: the stop still stops."""
    tid = _new(run)
    runs.pending_add(proj, tid, "human:owner", "message", "one more thing")
    folder = runs_live._held_path(proj, tid).parent
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.write_text("not a folder")
    _stop_a_run(proj, run, tid)
    assert runs.read(proj, tid) is None and _held(run, tid) == []
    folder.unlink()
    folder.mkdir()
    folder.chmod(0o500)  # the write fails (OSError)
    try:
        _stop_a_run(proj, run, tid)
    finally:
        folder.chmod(0o700)
    assert runs.read(proj, tid) is None and _held(run, tid) == []


@pytest.mark.parametrize(
    "body",
    [
        '{"ids": "PENDING"}',
        '{"ids": [1, 2]}',
        '{"ids": ["PENDING", null]}',
        '{"ids": {"PENDING": 1}}',
        '["PENDING"]',
        '"PENDING"',
        "not json",
        "\udcff",
    ],
)
def test_a_bad_hold_file_is_no_hold_and_status_never_crashes_on_stop(proj, run, body):
    """H4: ids must be a list of strings; anything else is no hold."""
    tid = _new(run)
    first = runs.pending_add(proj, tid, "human:owner", "message", "one more thing")
    path = runs_live._held_path(proj, tid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.replace("PENDING", first["id"]).encode("utf-8", "surrogateescape"))
    assert _held(run, tid) == []


def test_status_filters_a_stale_stop_hold_without_rewriting_it(proj, run):
    """M1: status only reads; an id no longer waiting is filtered out, the file is left as it was."""
    tid = _new(run)
    first = runs.pending_add(proj, tid, "human:owner", "message", "one more thing")
    path = runs_live._held_path(proj, tid)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"ids": ["p_gone000001", first["id"]]}) + "\n"
    path.write_text(body)
    assert _held(run, tid) == [first["id"]]
    assert path.read_text() == body


def test_a_linked_oversized_or_special_stop_hold_is_no_hold(proj, run):
    """M2: a symlinked stop-held folder or file, a folder in the file's place, or a file over 64 KB: no
    hold."""
    tid = _new(run)
    first = runs.pending_add(proj, tid, "human:owner", "message", "one more thing")
    path = runs_live._held_path(proj, tid)
    good = json.dumps({"ids": [first["id"]]})
    elsewhere = proj / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / path.name).write_text(good)
    path.parent.parent.mkdir(parents=True, exist_ok=True)
    path.parent.symlink_to(elsewhere, target_is_directory=True)
    assert _held(run, tid) == []
    path.parent.unlink()
    path.parent.mkdir()
    path.symlink_to(elsewhere / path.name)
    assert _held(run, tid) == []
    path.unlink()
    path.mkdir()
    assert _held(run, tid) == []
    path.rmdir()
    path.write_text(good + " " * runs_live.HELD_MAX)
    assert _held(run, tid) == []
    path.write_text(good)
    assert _held(run, tid) == [first["id"]]


@pytest.mark.parametrize("bad", ["..", "../t_abc123", "t_abc/../x", "/etc/passwd", "a/b", ""])
def test_a_bad_ticket_id_never_reaches_the_stop_hold_path(proj, bad):
    """M3: the id shape is checked before any hold path is built, read, written or removed."""
    for call in (
        lambda: runs_live._held_path(proj, bad),
        lambda: runs_live.stop_held(proj, bad, []),
        lambda: runs_live._write_held(proj, bad, ["p_x"]),
        lambda: runs_live.clear_held(proj, bad),
    ):
        with pytest.raises(Refused):
            call()
    assert not (runs.run_dir(proj) / "stop-held").exists()


def test_a_run_lock_is_never_empty(proj, monkeypatch):
    """A stop could hit the wrapper between creating its run lock and writing its name into it; that empty
    lock looked like a live writer for 30 s and the stop gave up ("busy"). The lock is now linked into place
    with the name already in it."""
    from orch import procs

    lock = proj / ".orch/run/tickets/t_lockaa.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    runs._create_lock(lock)
    assert lock.read_text() == procs.own_token()
    lock.unlink()

    def stopped_half_way(*a, **k):
        raise KeyboardInterrupt  # the process is stopped after the temp file, before the link

    monkeypatch.setattr(runs.os, "link", stopped_half_way)
    with pytest.raises(KeyboardInterrupt):
        runs._create_lock(lock)
    assert not lock.exists() and not list(lock.parent.glob(".*.new"))


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
    """F6 (delta review): a failed send keeps the result entry, so the retry is a result again."""
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
    # an unclear failure keeps the entry; once its lease is over the same result goes again (same id)
    phone_view.update_state(proj, lambda st: st["results"][tid].update(at=0))
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


def _ended_live(proj, tid, text="Answer to your question q1: Blue", stop=False):
    import sys

    rec = runs.claim(proj, tid, "human:t", "claude", "live", pid=os.getpid())
    if text:
        runs.pending_add(proj, tid, "human:t", "answer", text)
    if stop:
        rec = runs.read(proj, tid)
        rec["stop_requested"] = tickets.now()
        runs._write(proj, rec)
    runs.wrap_live(proj, rec["run"], tid, "claude", [sys.executable, "-c", "pass"], None)


@pytest.mark.parametrize("stop", [False, True])
def test_a_live_session_that_ends_with_queued_input_is_ready_and_keeps_the_input(
    proj, run, monkeypatch, stop
):
    """Only the automation host starts runs for queued input: the wrapper starts nothing, the ticket is Ready
    (never Working with nobody) and the answer stays queued for the next start."""
    tid = _new(run)
    tickets.set_status(proj, tid, "active", "human:t")
    _ended_live(proj, tid, stop=stop)
    assert runs.read(proj, tid) is None and _status(proj, tid) == "ready"
    assert [i["text"] for i in runs.undelivered(proj, tid)] == ["Answer to your question q1: Blue"]
    code, out, _ = run("run", "status", tid, "--json")
    assert json.loads(out)["human_pending_ids"] == [runs.undelivered(proj, tid)[0]["id"]]  # for automation


def test_the_run_wrapper_never_starts_runs(proj):
    """INVARIANT 1: only the automation host starts runs for queued input. Nothing in core that runs inside
    or after an agent (the run wrapper, the CLI) starts `orch run start`; no flag or variable asks for it.
    (INVARIANT 2 is test_only_human_pending_input_is_offered_to_start_a_run.)"""
    import pathlib
    import re

    src = pathlib.Path(runs.__file__).parent
    for f in src.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r'orch_python_argv\(\s*"run",\s*"start"', text), f.name
        assert "restart_for_input" not in text and '"restarted"' not in text, f.name
        assert not re.search(r"ORCH_RESTART|--restart\b", text), f.name


def test_only_human_pending_input_is_offered_to_start_a_run(proj, run, monkeypatch):
    """INVARIANT 2: only human-authored pending input (owner, phone, dashboard; never agent:*) starts a run,
    once per item. Core lists only those (human_pending_ids); the automation host acts only on them."""
    tid = _new(run)
    runs.pending_add(proj, tid, "agent:claude", "message", "continue")  # an agent queues for itself
    monkeypatch.setattr(tickets, "agent_tool", lambda: "claude")
    runs.pending_add(proj, tid, "human:owner", "message", "pretending")  # written from inside an agent
    monkeypatch.setattr(tickets, "agent_tool", lambda: None)
    assert runs.human_waiting(proj, tid) == []
    code, out, _ = run("run", "status", tid, "--json")
    assert json.loads(out)["human_pending_ids"] == []
    system = (("orch", "message"), ("agent:automation", "event"), ("human:t", "event"), ("watch", "text"))
    for by, kind in system:
        assert runs.pending_add(proj, tid, by, kind, "system note")["human"] is False  # system writers
    # the word "phone" alone never makes it a person's: only the relay's phone id does
    names = ("orch", "automation:loop", "agent:relay", "watch", "", "automation", "Pilatus", "iPhone")
    for by in names:
        assert runs.pending_add(proj, tid, by, "message", "relayed", via="phone")["human"] is False
    assert runs.pending_add(proj, tid, "human:", "message", "empty name")["human"] is False
    forged = runs.pending_add(proj, tid, "agent:claude", "message", "x")
    items = runs._pending_read(proj, tid)
    next(i for i in items if i["id"] == forged["id"])["human"] = True  # a flag set by hand is not trusted
    runs._pending_write(proj, tid, items)
    assert runs.human_waiting(proj, tid) == []
    human = runs.pending_add(proj, tid, "human:owner", "answer", "Blue")
    phone = runs.pending_add(proj, tid, "iPhone", "message", "and dessert", via="phone", phone="ph_abc123")
    assert [i["id"] for i in runs.human_waiting(proj, tid)] == [human["id"], phone["id"]]
    code, out, _ = run("run", "status", tid, "--json")
    assert json.loads(out)["human_pending_ids"] == [human["id"], phone["id"]]


def test_a_working_ticket_with_queued_input_and_no_run_is_ready_after_the_grace(proj, run):
    tid = _new(run)
    tickets.set_status(proj, tid, "active", "human:t")
    runs.pending_add(proj, tid, "human:t", "message", "One more thing")
    assert runs.settle_orphan(proj, tid, at=time.time() + 600) is True
    assert _status(proj, tid) == "ready" and runs.undelivered(proj, tid)


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


def test_a_run_lock_falls_back_without_hard_links_and_is_private(proj, monkeypatch):
    """#318 review: link() says EPERM/ENOTSUP/EXDEV/EINVAL/ENOSYS (or Windows error 1/50) where hard links are
    missing: plain create, mode 0600. Any other error (EACCES: Windows delete pending) still means busy."""
    import errno
    import stat as st

    from orch import procs

    lock = proj / ".orch/run/tickets/t_lockbb.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    windows = OSError(errno.EIO, "not supported")
    windows.winerror = 50  # ERROR_NOT_SUPPORTED (FAT/exFAT/SMB)
    for code in (errno.EPERM, errno.ENOTSUP, errno.EXDEV, errno.EINVAL, errno.ENOSYS, windows):

        def no_links(*a, code=code, **k):
            raise code if isinstance(code, OSError) else OSError(code, "no hard links")

        monkeypatch.setattr(runs.os, "link", no_links)
        runs._create_lock(lock)
        assert lock.read_text() == procs.own_token()
        assert st.S_IMODE(lock.stat().st_mode) == 0o600
        lock.unlink()


def test_an_nfs_eexist_on_our_own_lock_counts_as_taken(proj, monkeypatch):
    """#318 review: NFS may report EEXIST for a link that did succeed; the lock holding our token is ours."""
    real = runs.os.link

    def link_then_eexist(src, dst, *a, **k):
        real(src, dst)
        raise FileExistsError(17, "File exists")

    monkeypatch.setattr(runs.os, "link", link_then_eexist)
    lock = proj / ".orch/run/tickets/t_lockcc.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    runs._create_lock(lock)  # no error: it is ours
    lock.write_text("someone else")
    with pytest.raises(FileExistsError):
        runs._create_lock(lock)


def test_a_link_error_that_means_busy_is_not_a_fallback(proj, monkeypatch):
    import errno

    def busy(*a, **k):
        raise PermissionError(errno.EACCES, "delete pending")

    monkeypatch.setattr(runs.os, "link", busy)
    lock = proj / ".orch/run/tickets/t_lockdd.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with pytest.raises(PermissionError):
        runs._create_lock(lock)
    assert not lock.exists()
