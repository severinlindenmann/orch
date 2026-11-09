"""Running now: only runs Focus itself started are listed and stoppable, verified by pid + start time."""

import json
import os
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


def _procs(server):
    _tr(server).status_cache.clear()  # the page's own 1 s cache
    return json.loads(req(server, "GET", "/api/procs")[1])["procs"]


def test_lists_only_runs_focus_started(server, fake_orch):
    assert _procs(server) == []
    _start(server)
    _status(fake_orch)
    rows = _procs(server)
    assert [(r["ticket"], r["run"], r["state"]) for r in rows] == [(TID, "r_start001", "working")]
    _tr(server).status_cache.clear()
    _status(fake_orch, by="human:anna")  # same run id, but someone else holds it
    assert _procs(server) == []
    _tr(server).status_cache.clear()
    _status(fake_orch, run="r_other002")  # another run on the ticket
    assert _procs(server) == []


def test_stop_one_goes_through_orch_and_forgets(server, fake_orch):
    _start(server)
    _status(fake_orch)
    st, body, _ = req(
        server, "POST", "/api/act", {"op": "proc.stop", "args": {"ticket": TID, "run": "r_start001"}}
    )
    assert st == 200 and json.loads(body)["stopped"] == 1
    assert [c[:3] for c in _stops(fake_orch)] == [["run", "stop", TID]] and "focus" in _stops(fake_orch)[0]
    assert _tr(server).started == {}


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


def test_pid_and_start_time_must_match_the_first_sighting(server, fake_orch):
    _start(server)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _status(fake_orch, pid=child.pid)
        assert len(_procs(server)) == 1  # pinned: pid + start time
        pin = _tr(server).pins[TID]
        assert pin["pid"] == child.pid and pin["start"] == runfiles.proc_start(child.pid)
        # the pid now belongs to a process with another start time (pid reuse): not ours any more
        _tr(server).pins[TID]["start"] = "Thu Jan  1 00:00:00 1970"
        _tr(server).status_cache.clear()
        assert _procs(server) == []
        st, _, _ = req(
            server, "POST", "/api/act", {"op": "proc.stop", "args": {"ticket": TID, "run": "r_start001"}}
        )
        assert st == 409 and _stops(fake_orch) == []
        # a dead pid is not listed either
    finally:
        child.kill()
        child.wait()
    _tr(server).pins.clear()
    _tr(server).status_cache.clear()
    assert _procs(server) == []


def test_stop_all_stops_each_verified_run(server, fake_orch):
    _start(server)
    _status(fake_orch)
    st, body, _ = req(server, "POST", "/api/act", {"op": "proc.stop_all", "args": {}})
    assert st == 200 and json.loads(body)["stopped"] == 1 and len(_stops(fake_orch)) == 1


def test_pins_survive_a_restart(server, ws, fake_orch):
    from orch_focus.server import Tracker

    _start(server)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _status(fake_orch, pid=child.pid)
        _procs(server)
        assert Tracker(ws, str(fake_orch)).pins[TID]["pid"] == child.pid
        assert os.name  # keep flake quiet
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
