"""The Factory watcher: wakes the manager when a person answers or a crew task finishes (fake orch)."""

import json
import os
import subprocess
import sys

import pytest
from test_flow import ask_stop, autopilot_order, core, edit, finish_crew, started

from orch_factory import orchcli, runfiles, service, watch
from orch_factory.store import Refused


def runs(ws):
    p = ws / "runs.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def history(ws, order):
    return [h["text"] for h in core(ws, "ticket", "show", order)["history"]]


def test_wakes_once_for_a_person_start(ws, run):
    order, _ = started(ws, run)
    assert watch.once(ws) == [{"order": order, "why": "anna answered start"}]
    assert runs(ws) == [{"ticket": order, "agent": None, "by": "agent:factory"}]
    assert "Factory woke the manager: anna answered start" in history(ws, order)
    assert watch.once(ws) == [] and len(runs(ws)) == 1  # never twice, even if nobody called next
    run("next", order)
    assert watch.once(ws) == [] and len(runs(ws)) == 1


def test_never_for_an_agent_answer(ws, run):
    started(ws, run, by="agent:worker")
    assert watch.once(ws) == [] and runs(ws) == []


def test_wakes_on_crew_done_once(ws, run):
    order, _ = started(ws, run)
    watch.once(ws)
    run("next", order)
    tid = run("crew", "add", order, "booking-form")["ticket"]
    assert watch.once(ws) == [] and len(runs(ws)) == 1  # a new open crew ticket is no news
    edit(ws, tid, lambda t: t.update(status="done"))
    woke = watch.once(ws)
    assert [w["order"] for w in woke] == [order] and "booking-form is done" in woke[0]["why"]
    assert len(runs(ws)) == 2
    assert watch.once(ws) == [] and len(runs(ws)) == 2


def test_wakes_on_crew_failed(ws, run):
    order, _ = started(ws, run)
    watch.once(ws)
    run("next", order)
    tid = run("crew", "add", order, "booking-form")["ticket"]
    watch.once(ws)
    edit(ws, tid, lambda t: t.update(status="failed"))
    assert "is failed" in watch.once(ws)[0]["why"]


def test_no_start_while_a_run_is_live(ws, run):
    order, _ = started(ws, run)
    (ws / "live-runs").write_text(order)
    assert watch.once(ws) == [] and runs(ws) == []
    (ws / "live-runs").unlink()
    assert len(watch.once(ws)) == 1 and len(runs(ws)) == 1  # not lost: it woke when the run ended


def test_crew_done_during_a_live_run_wakes_after_it(ws, run):
    order, _ = started(ws, run)
    watch.once(ws)
    run("next", order)
    finish_crew(ws, run, order, "booking-form")
    (ws / "live-runs").write_text(order)
    assert watch.once(ws) == []
    (ws / "live-runs").unlink()
    assert len(watch.once(ws)) == 1


def test_crash_between_save_and_start_does_not_double_start(ws, run, monkeypatch):
    started(ws, run)
    real = orchcli.call

    def crash(root, *args, **kw):
        if args[:2] == ("run", "start"):
            raise RuntimeError("power cut")
        return real(root, *args, **kw)

    monkeypatch.setattr(watch.orchcli, "call", crash)
    with pytest.raises(RuntimeError):
        watch.once(ws)
    monkeypatch.setattr(watch.orchcli, "call", real)
    assert watch.once(ws) == [] and runs(ws) == []


def test_refused_start_is_retried(ws, run):
    started(ws, run)
    (ws / "fail-run").write_text("x")
    assert watch.once(ws) == [] and runs(ws) == []
    (ws / "fail-run").unlink()
    assert len(watch.once(ws)) == 1


def test_autopilot_stop_wakes_once(ws, run):
    autopilot_order(ws, run)
    order, _ = started(ws, run)
    watch.once(ws)
    run("next", order)
    finish_crew(ws, run, order, "booking-form")
    watch.once(ws)  # the crew news
    n = len(runs(ws))
    ask_stop(ws, run, order, "build", {"title": "Wording", "tag": "routine"})
    woke = watch.once(ws)
    assert woke and woke[0]["why"] == "autopilot may decide a stop"
    assert len(runs(ws)) == n + 1
    assert watch.once(ws) == [] and len(runs(ws)) == n + 1


def test_stop_that_is_not_for_autopilot_does_not_wake(ws, run):
    autopilot_order(ws, run)
    order, _ = started(ws, run)
    watch.once(ws)
    run("next", order)
    finish_crew(ws, run, order, "booking-form")
    watch.once(ws)
    n = len(runs(ws))
    ask_stop(ws, run, order, "build", {"title": "Delete data", "tag": "cant-undo"})
    assert watch.once(ws) == [] and len(runs(ws)) == n


def test_once_command_json(ws, run):
    order, _ = started(ws, run)
    assert run("watch", "--once") == {"woken": [{"order": order, "why": "anna answered start"}]}
    assert run("watch", "--once") == {"woken": []}


def test_start_status_stop_json(ws, run):
    assert run("status", code=1) == {"running": False}
    assert run("stop") == {"stopped": False}
    out = run("start")
    try:
        assert out["running"] is True and out["pid"] > 1
        assert run("start") == out  # no second watcher
        assert run("status") == out
    finally:
        assert run("stop") == {"stopped": True}
    assert run("status", code=1) == {"running": False}


def test_stop_of_an_order_still_works(ws, run):
    refused = run("stop", "t_000001", code=2)
    assert refused["code"] == "invalid"


def test_stop_never_signals_a_foreign_process(ws, run):
    d = runfiles.run_dir(ws, "factory")
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        rec = {"pid": other.pid, "nonce": "a" * 32, "started": runfiles.proc_start(other.pid)}
        runfiles.write_json(d / "factory.json", rec)
        assert service.running_pid(ws, clean=False) is None  # right pid and start, but not our command line
        out = run("stop")
        assert out["stopped"] is False and "nothing was stopped" in out["note"]
        assert other.poll() is None
        assert not (d / "factory.json").exists()
    finally:
        other.kill()
        other.wait()


def test_planted_record_with_a_wrong_start_is_not_signalled(ws, run):
    d = runfiles.run_dir(ws, "factory")
    rec = {"pid": os.getpid(), "nonce": "b" * 32, "started": "Mon Jan  1 00:00:00 2001"}
    runfiles.write_json(d / "factory.json", rec)
    assert service.stop(ws) == "not verified"


def test_view_says_when_the_watcher_is_off(ws, run):
    view = run("view")
    assert (
        view["notice"] == "Factory watcher off — answers wait until it runs" and view["notice_tone"] == "warn"
    )
    run("start")
    try:
        assert "notice" not in run("view")
    finally:
        run("stop")


def test_refused_is_plain(ws):
    with pytest.raises(Refused):
        orchcli.call(ws, "run", "status", "t_nothere")
