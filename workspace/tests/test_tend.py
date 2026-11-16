"""The helper watcher (`orch run tend`, ORCH-78): ends sessions on finished or waiting tickets, reminds an
idle helper once, starts it fresh when it does not move, and starts the line
in priority order."""

import json
import subprocess
import time

import pytest

from orch import adapters, brake, runs, runs_live, runwatch, tend, tickets


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    """No tmux and no process table: nothing runs in the helper, nothing is typed into a screen."""
    monkeypatch.setattr(runwatch, "_table", lambda: [])
    monkeypatch.setattr(runs_live, "deliver", lambda root, tid, stop=None: 0)
    monkeypatch.setattr(runs_live, "session_exists", lambda root, tid: False)


@pytest.fixture
def child():
    procs = []

    def make():
        p = subprocess.Popen(["sleep", "120"])
        procs.append(p)
        return p.pid

    yield make
    for p in procs:
        p.kill()
        p.wait()


@pytest.fixture
def starts(monkeypatch):
    """runs.start recorded instead of spawning an agent."""
    calls = []

    def fake(root, tid, by, **kw):
        calls.append((tid, by, kw))
        return {"run": "r_fresh0001", "mode": "live", "resumed": False, "notes": []}

    monkeypatch.setattr(runs, "start", fake)
    return calls


def _since(seconds_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds_ago))


def _live(proj, tid, pid, idle_for, state="idle", run="r_test1234"):
    runs._write(
        proj,
        {
            "schema": "orch.run/1",
            "ticket": tid,
            "run": run,
            "by": "human:tester",
            "agent": "generic",
            "mode": "live",
            "pid": pid,
            "started_at": _since(7200),
            "renewed_at": _since(7200),
            "live": {"state": state, "since": _since(idle_for)},
        },
    )


def _status(proj, tid, status):
    tickets.apply_op(proj, tid, lambda t: t.update(status=status), by="agent:x")


def _history(proj, tid):
    return [h["text"] for h in tickets.load(proj, tid)["history"] if h["by"] == tend.BY]


def _actions(result):
    return [(a["key"], a["action"]) for a in result["actions"] if a["action"] != "forget"]


def test_a_finished_ticket_session_ends_after_ten_quiet_minutes(proj, new_ticket, child):
    tid = new_ticket()
    _status(proj, tid, "review")
    _live(proj, tid, child(), idle_for=11 * 60)
    res = tend.run(proj)
    assert [a["action"] for a in res["actions"]] == ["end"]
    assert runs.read(proj, tid) is None  # the claim is gone; the conversation stays on the ticket
    assert "the ticket is finished" in _history(proj, tid)[0]


def test_a_finished_ticket_session_quiet_for_a_short_time_stays(proj, new_ticket, child):
    tid = new_ticket()
    _status(proj, tid, "review")
    _live(proj, tid, child(), idle_for=3 * 60)
    assert tend.run(proj)["actions"] == []
    assert runs.read(proj, tid) is not None


def test_a_session_waiting_on_a_persons_answer_ends_and_says_it_continues(proj, run, new_ticket, child):
    tid = new_ticket()
    assert run("ask", tid, "Which colour?", "--option", "red", "--option", "blue")[0] == 0
    _live(proj, tid, child(), idle_for=6 * 60)
    res = tend.run(proj)
    assert [a["action"] for a in res["actions"]] == ["end"]
    assert runs.read(proj, tid) is None
    line = _history(proj, tid)[0]
    assert "an answer from the person" in line and "continues when that comes" in line


def test_a_waiting_session_is_left_alone_while_a_command_runs(proj, run, new_ticket, child, monkeypatch):
    tid = new_ticket()
    assert run("ask", tid, "Which colour?", "--option", "red", "--option", "blue")[0] == 0
    _live(proj, tid, child(), idle_for=60 * 60)
    monkeypatch.setattr(
        runwatch, "tool_commands", lambda pid, table=None: [{"label": "pr-green.sh", "seconds": 600}]
    )
    assert tend.run(proj)["actions"] == []


def test_a_question_on_the_screen_or_input_on_the_way_is_never_touched(proj, new_ticket, child):
    a, b = new_ticket("a"), new_ticket("b")
    _live(proj, a, child(), idle_for=60 * 60, state="attention")
    _live(proj, b, child(), idle_for=60 * 60)
    runs.pending_add(proj, b, "human:tester", "message", "Please also fix the title.")
    assert tend.run(proj)["actions"] == []


def test_an_idle_helper_is_reminded_once_with_what_changed(proj, run, new_ticket, child):
    tid = new_ticket()
    assert run("check", "add", tid, "Write the page")[0] == 0
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=21 * 60)
    tickets.log(proj, tid, "Release 28 is out.", "human:tester")
    res = tend.run(proj)
    assert [a["action"] for a in res["actions"]] == ["nudge"]
    sent = [i for i in runs.undelivered(proj, tid) if i["by"] == tend.BY]
    assert len(sent) == 1
    assert "Release 28 is out." in sent[0]["text"] and "Write the page" in sent[0]["text"]
    assert "Reminded the helper" in _history(proj, tid)[0]
    for i in sent:  # it went in; the helper is still idle
        runs.mark_delivered(proj, tid, [i["id"]])
    assert tend.run(proj)["actions"] == []  # once


def test_waiting_on_something_outside_is_reminded_not_ended(proj, run, new_ticket, child):
    tid = new_ticket()
    assert run("wait", tid, "--on", "external:release 28")[0] == 0
    _live(proj, tid, child(), idle_for=21 * 60)
    assert [a["action"] for a in tend.run(proj)["actions"]] == ["nudge"]
    assert runs.read(proj, tid) is not None


def test_a_ticket_waiting_on_a_finished_ticket_is_started_again_once(proj, run, new_ticket, starts):
    other, tid = new_ticket("crew"), new_ticket("lead")
    assert run("wait", tid, "--on", f"ticket:{other}")[0] == 0
    assert tend.run(proj)["actions"] == []  # the other one is not finished yet
    _status(proj, other, "review")
    res = tend.run(proj)
    assert [a["action"] for a in res["actions"]] == ["wake"]
    assert starts == [(tid, runs_live.AUTOMATION_BY, {})]
    assert any("is in Review now" in i["text"] for i in runs.undelivered(proj, tid))
    assert tickets.load(proj, tid)["status"] == "active"
    assert "Started the helper again" in _history(proj, tid)[-1]
    assert tend.run(proj)["actions"] == []  # never twice


def test_an_idle_helper_under_twenty_minutes_is_not_reminded(proj, new_ticket, child):
    tid = new_ticket()
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=15 * 60)
    assert tend.run(proj)["actions"] == []


def _nudged(proj, tid, run="r_test1234", **more):
    """Reminded right after everything on the ticket so far (the pass then runs with a later `now`)."""
    state = tend._read_state(proj)
    state[tid] = {"run": run, "nudged_at": _since(-1), **more}
    tend._write_state(proj, state)


def _later(minutes):
    return time.time() + minutes * 60 + 1


def test_still_idle_ten_minutes_after_the_reminder_starts_fresh(proj, new_ticket, child, starts):
    tid = new_ticket()
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=31 * 60)
    _nudged(proj, tid)
    res = tend.run(proj, now=_later(11))
    assert [a["action"] for a in res["actions"]] == ["restart"]
    assert starts == [(tid, runs_live.AUTOMATION_BY, {"fresh": True})]
    assert any("started you fresh" in i["text"] for i in runs.undelivered(proj, tid))
    assert "Started the helper fresh" in _history(proj, tid)[0]
    assert "restarted_at" in tend._read_state(proj)[tid]


def test_no_fresh_start_before_ten_minutes(proj, new_ticket, child, starts):
    tid = new_ticket()
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=30 * 60)
    _nudged(proj, tid)
    assert tend.run(proj, now=_later(5))["actions"] == []
    assert starts == []


def test_no_fresh_start_when_the_helper_moved_after_the_reminder(proj, new_ticket, child, starts):
    tid = new_ticket()
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=30 * 60)
    _nudged(proj, tid)
    time.sleep(2.1)
    tickets.log(proj, tid, "Checked the CI run.", "agent:generic")
    res = tend.run(proj, now=_later(11))
    assert _actions(res) == [] and starts == []
    assert tid not in tend._read_state(proj)  # a new chance: reminded again after the next quiet stretch


def test_a_second_fresh_start_within_six_hours_is_left_for_a_person(proj, new_ticket, child, starts):
    tid = new_ticket()
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=31 * 60, run="r_second001")
    _nudged(proj, tid, run="r_second001", restarted_at=_since(3600))
    assert [a["action"] for a in tend.run(proj, now=_later(11))["actions"]] == ["leave"]
    assert starts == []
    assert "left for a person" in _history(proj, tid)[0]
    assert tend.run(proj, now=_later(12))["actions"] == []  # said once


def test_nothing_happens_while_automation_is_paused(proj, new_ticket, child, starts):
    tid = new_ticket()
    _status(proj, tid, "review")
    _live(proj, tid, child(), idle_for=60 * 60)
    brake.pause(proj, "human:tester")
    res = tend.run(proj)
    assert res["paused"] is True and res["actions"] == []
    assert runs.read(proj, tid) is not None


def test_dry_run_only_says_what_it_would_do(proj, run, new_ticket, child):
    tid = new_ticket()
    _status(proj, tid, "review")
    _live(proj, tid, child(), idle_for=60 * 60)
    code, out, err = run("run", "tend", "--dry-run", "--json")
    assert code == 0, err
    data = json.loads(out)
    assert [(a["action"], a["done"]) for a in data["actions"]] == [("end", False)]
    assert runs.read(proj, tid) is not None
    assert "would be ended" in tend.text(data, dry_run=True)


def test_all_fine_says_so(proj, run):
    code, out, err = run("run", "tend")
    assert code == 0, err
    assert "nothing to do" in out


# ---------------------------------------------------------------- the line, in priority order


def _queue(proj, tid, priority="normal"):
    runs_live._queue_for_slot(proj, tid, "human:tester", "Start when a slot is free.", priority)


def test_the_line_goes_by_priority_then_oldest(proj, new_ticket):
    a, b, c, d = (new_ticket(n) for n in "abcd")
    _queue(proj, a, "low")
    _queue(proj, b)
    _queue(proj, c, "high")
    _queue(proj, d)
    assert runs_live.waiting_line(proj) == [(c, "high"), (b, "normal"), (d, "normal"), (a, "low")]


def test_queued_again_keeps_one_place_with_the_higher_priority(proj, new_ticket):
    a, b = new_ticket("a"), new_ticket("b")
    _queue(proj, a)
    _queue(proj, b)
    _queue(proj, b, "high")
    _queue(proj, a, "low")  # never lowers
    assert runs_live.waiting_line(proj) == [(b, "high"), (a, "normal")]
    assert len([i for i in runs.undelivered(proj, b) if i.get("via") == "slots"]) == 1


def test_free_slots_start_the_line_in_order_until_full(proj, new_ticket, monkeypatch):
    a, b, c = (new_ticket(n) for n in "abc")
    _queue(proj, a, "low")
    _queue(proj, b, "high")
    _queue(proj, c)
    started = []
    monkeypatch.setattr(runs_live, "_full", lambda root: 4 if len(started) >= 2 else None)
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: started.append(tid))
    assert runs_live.start_waiting(proj) == [b, c]
    assert started == [b, c]


def test_start_priority_queues_when_every_slot_is_taken(proj, run, new_ticket, monkeypatch):
    tid = new_ticket()
    monkeypatch.setattr(runs_live, "_full", lambda root: 2)
    monkeypatch.setattr(runs_live, "available", lambda adapter: True)
    monkeypatch.setattr(adapters, "chosen", lambda root: "generic")
    code, out, err = run("run", "start", tid, "--priority", "high", "--mode", "live")
    assert code == 2 and "waits in line" in out + err, out + err
    assert runs_live.waiting_line(proj) == [(tid, "high")]
    code, out, err = run("run", "tend", "--json")
    assert code == 0, err
    assert json.loads(out)["queue"] == [{"ticket": tid, "key": runs_live.ref(proj, tid), "priority": "high"}]
