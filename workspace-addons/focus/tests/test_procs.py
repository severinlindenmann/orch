"""Running now: only runs Focus itself started are listed and stoppable, verified by pid + start time."""

import json
import subprocess
import sys

from orch_focus import runfiles

from .conftest import TID, calls
from .test_server import req


def _status(fake, run="r_start001", by="focus", **claim):
    (fake.parent / "status.json").write_text(
        json.dumps(
            {
                "running": True,
                "claim": {
                    "run": run,
                    "by": by,
                    "agent": "x",
                    "mode": "oneshot",
                    "started_at": "2026-11-09T08:00:00Z",
                    **claim,
                },
            }
        )
    )


def _start(server):
    req(server, "POST", "/api/act", {"op": "run.start", "args": {"ticket": TID}})


def _tr(server):
    return server.RequestHandlerClass.keywords["tracker"]


def _stops(fake):
    return [c for c in calls(fake) if c[:2] == ["run", "stop"]]


def _pinned(server, fake):
    """A run Focus started whose process is alive and pinned at start; returns the child to kill."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    _status(fake, pid=child.pid)
    _tr(server).status_cache.clear()
    assert _tr(server).pin_started(TID, "r_start001")
    return child


def _procs(server):
    _tr(server).status_cache.clear()  # the page's own 1 s cache
    return json.loads(req(server, "GET", "/api/procs")[1])["procs"]


def test_lists_only_runs_focus_started(server, fake_orch):
    assert _procs(server) == []
    _start(server)
    child = _pinned(server, fake_orch)
    try:
        rows = _procs(server)
        assert [(r["ticket"], r["run"], r["state"]) for r in rows] == [(TID, "r_start001", "working")]
        _status(fake_orch, by="human:anna", pid=child.pid)  # same run id, but someone else holds it
        assert _procs(server) == []
        _status(fake_orch, run="r_other002", pid=child.pid)  # another run on the ticket
        assert _procs(server) == []
    finally:
        child.kill()
        child.wait()


def test_a_run_without_a_start_pin_is_not_listed_or_stoppable_and_get_writes_nothing(server, ws, fake_orch):
    _start(server)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _status(fake_orch, pid=child.pid)
        assert _procs(server) == [] and _tr(server).pins == {}
        assert not list(ws.rglob("pins.json"))
        st, _, _ = req(
            server, "POST", "/api/act", {"op": "proc.stop", "args": {"ticket": TID, "run": "r_start001"}}
        )
        assert st == 409 and _stops(fake_orch) == []
    finally:
        child.kill()
        child.wait()


def test_a_pinned_run_whose_claim_lost_its_pid_is_refused(server, fake_orch):
    _start(server)
    child = _pinned(server, fake_orch)
    try:
        assert len(_procs(server)) == 1
        _status(fake_orch)  # the claim no longer names a pid
        assert _procs(server) == []
        st, _, _ = req(
            server, "POST", "/api/act", {"op": "proc.stop", "args": {"ticket": TID, "run": "r_start001"}}
        )
        assert st == 409 and _stops(fake_orch) == []
    finally:
        child.kill()
        child.wait()


def test_stop_one_goes_through_orch_and_forgets(server, fake_orch):
    _start(server)
    child = _pinned(server, fake_orch)
    st, body, _ = req(
        server, "POST", "/api/act", {"op": "proc.stop", "args": {"ticket": TID, "run": "r_start001"}}
    )
    assert st == 200 and json.loads(body)["stopped"] == 1
    assert [c[:3] for c in _stops(fake_orch)] == [["run", "stop", TID]] and "focus" in _stops(fake_orch)[0]
    assert _tr(server).started == {}
    child.kill()
    child.wait()


def test_stop_refuses_a_run_focus_did_not_start(server, fake_orch):
    _start(server)
    _tr(server).status_cache.clear()
    _status(fake_orch, run="r_other002")
    st, _, _ = req(
        server, "POST", "/api/act", {"op": "proc.stop", "args": {"ticket": TID, "run": "r_other002"}}
    )
    assert st == 409
    st, _, _ = req(
        server, "POST", "/api/act", {"op": "proc.stop", "args": {"ticket": TID, "run": "r_start001"}}
    )
    assert st == 409
    _status(fake_orch, by="human:anna")
    _tr(server).status_cache.clear()
    st, _, _ = req(
        server, "POST", "/api/act", {"op": "proc.stop", "args": {"ticket": TID, "run": "r_start001"}}
    )
    assert st == 409 and _stops(fake_orch) == []


def test_stop_refuses_bad_arguments(server, fake_orch):
    for args in (
        {},
        {"ticket": TID},
        {"ticket": TID, "run": "r_start001", "x": 1},
        {"ticket": "../x", "run": "r_start001"},
        {"ticket": TID, "run": "nope"},
        {"ticket": TID, "run": 5},
    ):
        assert req(server, "POST", "/api/act", {"op": "proc.stop", "args": args})[0] in (400, 409), args
    assert req(server, "POST", "/api/act", {"op": "proc.stop_all", "args": {"ticket": TID}})[0] == 400
    assert _stops(fake_orch) == []


def test_pid_and_start_time_must_match_the_pin(server, fake_orch):
    _start(server)
    child = _pinned(server, fake_orch)
    try:
        assert len(_procs(server)) == 1
        pin = _tr(server).pins[TID]
        assert pin["pid"] == child.pid and pin["start"] == runfiles.proc_start(child.pid)
        # the pid now belongs to a process with another start time (pid reuse): not ours any more
        _tr(server).pins[TID]["start"] = "Thu Jan  1 00:00:00 1970"
        assert _procs(server) == []
        st, _, _ = req(
            server, "POST", "/api/act", {"op": "proc.stop", "args": {"ticket": TID, "run": "r_start001"}}
        )
        assert st == 409 and _stops(fake_orch) == []
    finally:
        child.kill()
        child.wait()


def test_stop_all_stops_each_verified_run(server, fake_orch):
    _start(server)
    child = _pinned(server, fake_orch)
    try:
        st, body, _ = req(server, "POST", "/api/act", {"op": "proc.stop_all", "args": {}})
        assert st == 200 and json.loads(body)["stopped"] == 1 and len(_stops(fake_orch)) == 1
    finally:
        child.kill()
        child.wait()


def test_pins_survive_a_restart(server, ws, fake_orch):
    from orch_focus.server import Tracker

    _start(server)
    child = _pinned(server, fake_orch)
    try:
        assert Tracker(ws, str(fake_orch)).pins[TID]["pid"] == child.pid
    finally:
        child.kill()
        child.wait()


def test_done_tickets_carry_when_they_closed(server, ws):
    p = ws / ".orch" / "tickets" / f"{TID}.json"
    t = json.loads(p.read_text())
    t["status"] = "done"
    p.write_text(json.dumps(t))
    rows = json.loads(req(server, "GET", "/api/tickets")[1])["tickets"]
    assert [r["closed_at"] for r in rows if r["id"] == TID] == ["2026-11-06T08:00:00Z"]


def test_starting_a_run_pins_its_process(server, fake_orch):
    import time

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _status(fake_orch, pid=child.pid)
        _start(server)
        for _ in range(40):
            if TID in _tr(server).pins:
                break
            time.sleep(0.25)
        assert _tr(server).pins[TID]["pid"] == child.pid
    finally:
        child.kill()
        child.wait()


def test_pins_of_runs_that_are_not_started_are_dropped_on_load(server, ws, fake_orch):
    from orch_focus.server import Tracker

    _start(server)
    child = _pinned(server, fake_orch)
    try:
        assert Tracker(ws, str(fake_orch)).pins[TID]["run"] == "r_start001"
        _tr(server).started.clear()
        _tr(server)._save_started()
        assert Tracker(ws, str(fake_orch)).pins == {}
    finally:
        child.kill()
        child.wait()


def test_pin_started_waits_up_to_30_s_and_logs_when_it_never_gets_a_pid(
    server, fake_orch, monkeypatch, capsys
):
    sleeps = []

    class Clock:  # the wait between two looks at the claim; no real sleeping, and nothing global is patched
        def is_set(self):
            return False

        def set(self):
            pass

        def wait(self, s):
            sleeps.append(s)
            return False

    monkeypatch.setattr(_tr(server), "stop", Clock())
    _start(server)
    _status(fake_orch)  # no pid
    assert _tr(server).pin_started(TID, "r_start001") is False
    assert sum(sleeps) >= 30 and "no process id" in capsys.readouterr().err
