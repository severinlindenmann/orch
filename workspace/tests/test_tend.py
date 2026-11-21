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


def _live(proj, tid, pid, idle_for, state="idle", run="r_test1234", started=7200):
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
            "started_at": _since(started),
            "renewed_at": _since(started),
            "live": {"state": state, "since": _since(idle_for)},
        },
    )


def _status(proj, tid, status):
    tickets.apply_op(proj, tid, lambda t: t.update(status=status), by="agent:x")


def _history(proj, tid):
    return [h["text"] for h in tickets.load(proj, tid)["history"] if h["by"] == tend.BY]


def _actions(result):
    return [(a["key"], a["action"]) for a in result["actions"] if a["action"] != "forget"]


def test_a_done_ticket_session_ends_after_ten_quiet_minutes(proj, new_ticket, child):
    tid = new_ticket()
    _status(proj, tid, "done")
    _live(proj, tid, child(), idle_for=11 * 60)
    res = tend.run(proj)
    assert [a["action"] for a in res["actions"]] == ["end"]
    assert runs.read(proj, tid) is None  # the claim is gone; the conversation stays on the ticket
    assert "the ticket is finished" in res["actions"][0]["text"]  # a Done ticket takes no history line


def test_a_finished_ticket_session_quiet_for_a_short_time_stays(proj, new_ticket, child):
    tid = new_ticket()
    _status(proj, tid, "review")
    _live(proj, tid, child(), idle_for=3 * 60)
    assert tend.run(proj)["actions"] == []
    assert runs.read(proj, tid) is not None


def test_a_review_ticket_session_stays_warm_for_the_hour(proj, new_ticket, child):
    """ORCH-149: Continue on a Review ticket keeps its session and its cache."""
    tid = new_ticket()
    _status(proj, tid, "review")
    _live(proj, tid, child(), idle_for=11 * 60)
    assert tend.run(proj)["actions"] == []
    _live(proj, tid, child(), idle_for=61 * 60)
    assert [a["action"] for a in tend.run(proj)["actions"]] == ["end"]


def test_a_review_ticket_session_makes_room_when_the_sessions_are_full(proj, new_ticket, child, monkeypatch):
    monkeypatch.setattr(runs_live, "_crowded", lambda root: True)
    tid = new_ticket()
    _status(proj, tid, "review")
    _live(proj, tid, child(), idle_for=11 * 60)
    assert [a["action"] for a in tend.run(proj)["actions"]] == ["end"]


def test_a_session_waiting_on_an_answer_stays_warm_for_the_hour(proj, run, new_ticket, child):
    tid = new_ticket()
    assert run("ask", tid, "Which colour?", "--option", "red", "--option", "blue")[0] == 0
    _live(proj, tid, child(), idle_for=30 * 60)
    assert tend.run(proj)["actions"] == []
    assert runs.read(proj, tid) is not None


def test_a_session_waiting_on_a_person_stays_open_when_the_sessions_are_full(
    proj, run, new_ticket, child, monkeypatch
):
    """ORCH-254: the person may still answer; full sessions do not cut the hour short."""
    monkeypatch.setattr(runs_live, "_crowded", lambda root: True)
    tid = new_ticket()
    assert run("ask", tid, "Which colour?", "--option", "red", "--option", "blue")[0] == 0
    _live(proj, tid, child(), idle_for=6 * 60)
    assert tend.run(proj)["actions"] == []
    assert runs.read(proj, tid) is not None


def test_a_session_waiting_on_a_persons_answer_ends_and_says_it_continues(proj, run, new_ticket, child):
    tid = new_ticket()
    assert run("ask", tid, "Which colour?", "--option", "red", "--option", "blue")[0] == 0
    _live(proj, tid, child(), idle_for=61 * 60)
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
    assert "Sent the helper on" in _history(proj, tid)[0]  # it has an open step (ORCH-318)
    for i in sent:  # it went in; the helper is still idle
        runs.mark_delivered(proj, tid, [i["id"]])
    assert tend.run(proj)["actions"] == []  # once


def test_waiting_on_something_outside_is_reminded_not_ended(proj, run, new_ticket, child):
    tid = new_ticket()
    assert run("wait", tid, "--on", "external:release 28")[0] == 0
    _live(proj, tid, child(), idle_for=21 * 60)
    assert [a["action"] for a in tend.run(proj)["actions"]] == ["nudge"]
    assert runs.read(proj, tid) is not None


def test_waiting_on_a_pull_request_in_the_merge_queue_is_not_nudged(proj, run, new_ticket, child):
    url = "https://github.com/o/r/pull/7"
    qfile = proj / ".orch" / "addons" / "pull-requests" / "queue.json"

    def queue(state):
        qfile.parent.mkdir(parents=True, exist_ok=True)
        qfile.write_text(json.dumps({"entries": [{"url": url, "state": state, "ticket": tid}]}))

    tid = new_ticket()
    run("check", "add", tid, "Open the pull request")
    assert run("wait", tid, "--on", f"external:{url}")[0] == 0
    _live(proj, tid, child(), idle_for=21 * 60)
    queue("waiting")
    assert tend.run(proj)["actions"] == []
    queue("out")  # the queue is done with it: the usual reminder
    assert [a["action"] for a in tend.run(proj)["actions"]] == ["nudge"]


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


def test_still_idle_after_the_reminder_for_the_hour_starts_fresh(proj, new_ticket, child, starts):
    tid = new_ticket()
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=61 * 60)
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
    _live(proj, tid, child(), idle_for=61 * 60)
    _nudged(proj, tid)
    assert tend.run(proj, now=_later(5))["actions"] == []
    assert starts == []


def test_no_fresh_start_before_the_hour_keeps_the_cache(proj, new_ticket, child, starts):
    """ORCH-149: a reminded helper idle 31 minutes keeps its session (its cache is still warm)."""
    tid = new_ticket()
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=31 * 60)
    _nudged(proj, tid)
    assert tend.run(proj, now=_later(11))["actions"] == []
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
    _live(proj, tid, child(), idle_for=61 * 60, run="r_second001")
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
    monkeypatch.setattr(runs_live, "_held", lambda root, by="agent:tend": None)  # busy CI runner
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: started.append(tid))
    assert runs_live.start_waiting(proj) == [b, c]
    assert started == [b, c]


def test_a_done_ticket_is_never_started_from_the_line(proj, new_ticket, monkeypatch):
    a, b = new_ticket("a"), new_ticket("b")
    _queue(proj, a)
    _queue(proj, b)
    tickets.set_status(proj, a, "done", "test")
    started = []
    monkeypatch.setattr(runs_live, "_full", lambda root: None)
    monkeypatch.setattr(runs_live, "_held", lambda root, by="agent:tend": None)  # busy CI runner
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: started.append(tid))
    assert runs_live.start_waiting(proj) == [b]
    assert started == [b]


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


def test_a_time_wait_names_the_time(proj, run, new_ticket):
    tid = new_ticket()
    assert run("wait", tid, "--until", "2030-01-02T08:00:00Z")[0] == 0
    waits = runwatch.waiting_on(proj, None, tickets.load(proj, tid))
    assert waits[0]["kind"] == "time" and waits[0]["ref"] == "2030-01-02T08:00:00Z"
    assert waits[0]["what"] != "until "


# ---------------------------------------------------------------- a ceiling even with no limit set


def test_no_limit_twenty_waiting_start_in_steps(proj, new_ticket, monkeypatch):
    ids = [new_ticket(f"t{n}") for n in range(20)]
    for t in ids:
        _queue(proj, t)
    started = []
    monkeypatch.setattr(runs_live, "max_live", lambda root: None)  # "no limit" in Settings
    monkeypatch.setattr(runs_live, "_pressure", lambda root: None)
    monkeypatch.setattr(
        runs_live, "live_all", lambda root: [{"live": {"since": tickets.now()}}] if started else []
    )
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: started.append(tid))
    assert len(runs_live.start_waiting(proj)) == 1  # one new helper per pass
    assert runs_live.start_waiting(proj) == []  # the next waits until it is up
    assert len(started) == 1


def test_no_new_helper_while_load_or_disk_says_stop(proj, new_ticket, monkeypatch):
    a = new_ticket("a")
    _queue(proj, a)
    started = []
    monkeypatch.setattr(runs, "start", lambda root, tid, by, **kw: started.append(tid))
    monkeypatch.setattr(runs_live.os, "getloadavg", lambda: (45.0, 40.0, 30.0), raising=False)
    monkeypatch.setattr(runs_live.os, "cpu_count", lambda: 12)
    monkeypatch.setattr(runs_live, "_processes", lambda: [(1200.0, "real work")])
    assert runs_live.start_waiting(proj) == []
    monkeypatch.setattr(runs_live.os, "getloadavg", lambda: (1.0, 1.0, 1.0), raising=False)
    monkeypatch.setattr(runs_live.shutil, "disk_usage", lambda p: type("U", (), {"free": 2 * 2**30})())
    assert runs_live.start_waiting(proj) == []
    assert started == []


def test_a_start_handed_over_by_a_script_queues_under_load(proj, new_ticket, monkeypatch):
    tid = new_ticket()
    monkeypatch.setattr(runs_live.os, "getloadavg", lambda: (45.0, 40.0, 30.0), raising=False)
    monkeypatch.setattr(runs_live.os, "cpu_count", lambda: 12)
    monkeypatch.setattr(runs_live, "_processes", lambda: None)  # CPU use unknown: the load alone counts
    with pytest.raises(runs.Busy) as e:
        runs_live.start_live(proj, tid, "agent:x", "claude", fresh=False, take_over=False, busy_text="wait")
    assert e.value.extra["pending"] and "very busy" in str(e.value)
    assert runs_live.waiting_line(proj) == [(tid, "normal")]


# ---------------------------------------------------------------- ORCH-190: stopped right after the start


def test_a_helper_that_stopped_right_after_its_start_is_reminded_within_minutes(proj, new_ticket, child):
    """It went idle 20 s after its start (asked for a go-ahead in its own window): reminded after 3 minutes,
    not 20, with words that say nobody reads that window."""
    tid = new_ticket()
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=4 * 60, started=4 * 60 + 20)
    res = tend.run(proj)
    assert [a["action"] for a in res["actions"]] == ["nudge"]
    sent = [i for i in runs.undelivered(proj, tid) if i["by"] == tend.BY]
    assert len(sent) == 1 and "stopped right after the start" in sent[0]["text"]
    assert "right after its start" in _history(proj, tid)[0]
    assert tend._read_state(proj)[tid]["early"] is True


def test_a_helper_idle_early_but_under_three_minutes_is_left(proj, new_ticket, child):
    tid = new_ticket()
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=2 * 60, started=2 * 60 + 20)
    assert tend.run(proj)["actions"] == []


def test_a_helper_that_worked_first_waits_the_usual_twenty_minutes(proj, new_ticket, child):
    tid = new_ticket()
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=4 * 60, started=30 * 60)  # it worked 26 minutes, then went quiet
    assert tend.run(proj)["actions"] == []


def test_still_idle_after_the_early_reminder_starts_fresh_without_a_person(proj, new_ticket, child, starts):
    """No wait for the idle limit: five minutes after the reminder with nothing changed, it starts fresh."""
    tid = new_ticket()
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=9 * 60, started=9 * 60 + 20)
    _nudged(proj, tid, early=True)
    assert tend.run(proj, now=_later(4))["actions"] == []
    assert starts == []
    res = tend.run(proj, now=_later(5))
    assert [a["action"] for a in res["actions"]] == ["restart"]
    assert starts == [(tid, runs_live.AUTOMATION_BY, {"fresh": True})]
    assert "Started the helper fresh" in _history(proj, tid)[0]


def test_an_early_helper_that_moved_after_the_reminder_is_not_restarted(proj, new_ticket, child, starts):
    tid = new_ticket()
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=9 * 60, started=9 * 60 + 20)
    _nudged(proj, tid, early=True)
    time.sleep(2.1)
    tickets.log(proj, tid, "Started on the first task.", "agent:generic")
    assert _actions(tend.run(proj, now=_later(6))) == []
    assert starts == []


# ---------------------------------------------------------------- ORCH-266: Home says why nothing starts


def test_line_status_says_why_tickets_wait(proj, new_ticket, monkeypatch):
    assert runs_live.line_status(proj) is None  # nothing waits: Home shows nothing
    a = new_ticket("a")
    _queue(proj, a)
    monkeypatch.setattr(
        runs_live, "_pressure", lambda root: "the computer is very busy (54 'orch record tail' at once)"
    )
    st = runs_live.line_status(proj)
    assert st == {
        "waiting": [a],
        "why": "the computer is very busy (54 'orch record tail' at once)",
        "limit": None,
    }
    monkeypatch.setattr(runs_live, "_pressure", lambda root: None)
    monkeypatch.setattr(runs_live, "_full", lambda root: 3)
    assert runs_live.line_status(proj) == {
        "waiting": [a], "why": "3 helpers are working at once, the most you allowed", "limit": 3,
    }  # fmt: skip
    monkeypatch.setattr(runs_live, "_full", lambda root: None)
    assert runs_live.line_status(proj)["why"] is None  # only the short pause between starts: no reason shown


# ---------------------------------------------------------------- ORCH-318: stopped with open steps


def _stopped_with_open_step(proj, run, new_ticket, child, idle_for):
    tid = new_ticket()
    assert run("check", "add", tid, "Write the page")[0] == 0
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=idle_for, started=3 * 3600)
    return tid


def test_a_helper_that_stops_with_open_steps_is_sent_on_within_a_minute(proj, run, new_ticket, child):
    tid = _stopped_with_open_step(proj, run, new_ticket, child, idle_for=50)
    assert [a["action"] for a in tend.run(proj)["actions"]] == ["nudge"]
    assert "Sent the helper on" in _history(proj, tid)[0]
    assert tickets.load(proj, tid).get("model", {}).get("name") != "opus"  # first time: no move


def test_a_helper_idle_under_the_open_steps_limit_is_left(proj, run, new_ticket, child):
    _stopped_with_open_step(proj, run, new_ticket, child, idle_for=20)
    assert tend.run(proj)["actions"] == []


def test_without_open_steps_the_twenty_minute_reminder_still_rules(proj, new_ticket, child):
    tid = new_ticket()
    _status(proj, tid, "active")
    _live(proj, tid, child(), idle_for=50, started=3 * 3600)
    assert tend.run(proj)["actions"] == []


def test_a_waiting_helper_with_open_steps_is_not_sent_on(proj, run, new_ticket, child):
    tid = _stopped_with_open_step(proj, run, new_ticket, child, idle_for=50)
    assert run("ask", tid, "Which one?", "--option", "A", "--option", "B")[0] == 0
    assert "nudge" not in [a["action"] for a in tend.run(proj)["actions"]]


def test_the_second_stop_moves_the_ticket_up_to_opus(proj, run, new_ticket, child):
    tid = _stopped_with_open_step(proj, run, new_ticket, child, idle_for=50)
    tend.run(proj)
    for i in runs.undelivered(proj, tid):
        runs.mark_delivered(proj, tid, [i["id"]])
    st = tend._read_state(proj)
    st.pop(tid)  # the helper moved after the first reminder: a new chance
    tend._write_state(proj, st)
    _live(proj, tid, child(), idle_for=50, started=3 * 3600)
    assert [a["action"] for a in tend.run(proj)["actions"]] == ["nudge"]
    t = tickets.load(proj, tid)
    assert t["model"]["name"] == "opus"
    assert "moved up to Opus" in " ".join(_history(proj, tid))
