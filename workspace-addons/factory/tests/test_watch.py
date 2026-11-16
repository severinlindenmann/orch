"""The Factory watcher: wakes the manager when a person answers or a crew task finishes (fake orch)."""

import json
import os
import subprocess
import sys
import time

import pytest
from test_flow import ask_stop, autopilot_order, core, edit, finish_crew, run_proposal, started, waiting_stop

from orch_factory import flow, orchcli, runfiles, service, watch
from orch_factory.store import Refused, Store


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


def plain_line():
    """build and check have no stop (the plan says the crew's OK is enough), ship has one."""
    return run_proposal(
        line=[
            {"stage": "build", "stop": False, "why": "Layout already approved."},
            {"stage": "check", "stop": False, "why": "Booking flow, phone layout."},
            {"stage": "ship", "stop": True, "why": "You decide whether it goes live."},
        ],
        tasks=[
            {
                "slug": "booking-form",
                "title": "Booking form",
                "role": "builder",
                "stage": "build",
                "proves": [0],
            },
            {"slug": "review", "title": "Review against done means", "role": "reviewer", "stage": "check"},
            {"slug": "release", "title": "Prepare the release", "role": "builder", "stage": "ship"},
        ],
    )


def manager_runs(ws, order):
    return [r for r in runs(ws) if r["ticket"] == order]


def test_last_ok_starts_the_next_stage_at_once(ws, run):
    """#47: the crew's last result is OK -> the next stage's crew starts in the same pass, no manager run, no question."""
    order, _ = started(ws, run, data=plain_line())
    watch.once(ws)  # the person's Start wakes the manager
    run("next", order)
    tid = run("crew", "add", order, "booking-form")["ticket"]
    run("crew", "start", order, "booking-form")
    assert watch.once(ws) == []
    questions = len(core(ws, "ticket", "show", order)["questions"])
    edit(ws, tid, lambda t: t.update(status="done"))  # the owner's Looks good
    t0 = time.monotonic()
    woke = watch.once(ws)
    took = time.monotonic() - t0
    assert (
        len(woke) == 1
        and woke[0]["stage"] == "check"
        and woke[0]["why"] == "started the check stage as planned"
    )
    review = woke[0]["crew"][0]
    assert runs(ws)[-1] == {"ticket": review, "agent": "claude", "by": "agent:factory"}
    assert took < 10, f"the next stage took {took:.1f} s to start"
    assert len(manager_runs(ws, order)) == 1  # only the first wake for Start: the manager was not needed
    assert len(core(ws, "ticket", "show", order)["questions"]) == questions  # no new step for the person
    assert "Factory started the check stage as planned: Review against done means." in history(ws, order)
    assert core(ws, "ticket", "show", review)["ext"]["factory"]["task"] == "review"
    assert watch.once(ws) == [] and len(runs(ws)) == 3  # never twice
    assert (
        run("next", order)["step"] == "start-crew"
    )  # the manager's view is unchanged: crew of check, already started
    edit(ws, review, lambda t: t.update(status="done"))
    woke = watch.once(ws)  # ship has crew too: started the same way; its stop stays the manager's
    assert woke[0]["stage"] == "ship"
    edit(ws, woke[0]["crew"][0], lambda t: t.update(status="done"))
    woke = watch.once(ws)
    assert woke == [{"order": order, "why": "crew task release is done"}]  # the stop needs the manager
    assert len(manager_runs(ws, order)) == 2


def test_continue_at_a_stop_starts_the_next_stage(ws, run):
    order, q = waiting_stop(ws, run)
    watch.once(ws)
    n = len(manager_runs(ws, order))
    core(ws, "answer", order, q, "Continue", "--by", "human:anna")
    woke = watch.once(ws)
    assert len(woke) == 1 and woke[0]["stage"] == "ship"
    assert len(manager_runs(ws, order)) == n
    assert any(
        r["type"] == "stop-answered" for r in Store(ws).journal_read()
    )  # taken in, as the manager's next does


def test_send_back_still_wakes_the_manager(ws, run):
    order, q = waiting_stop(ws, run)
    watch.once(ws)
    core(ws, "answer", order, q, "Send back", "--by", "human:anna")
    assert watch.once(ws) == [{"order": order, "why": "anna answered stop"}]


def test_first_stage_stays_with_the_manager(ws, run):
    order, _ = started(ws, run, data=plain_line())
    assert watch.once(ws) == [{"order": order, "why": "anna answered start"}]
    assert manager_runs(ws, order) and len(runs(ws)) == 1


def test_next_stage_that_cannot_start_wakes_the_manager(ws, run, monkeypatch):
    order, _ = started(ws, run, data=plain_line())
    watch.once(ws)
    run("next", order)
    tid = run("crew", "add", order, "booking-form")["ticket"]
    watch.once(ws)
    edit(ws, tid, lambda t: t.update(status="done"))

    def used_up(root, order, task):
        raise Refused(
            "The time budget is used up. Ask the owner for more time (a change proposal).", "refused"
        )

    monkeypatch.setattr(flow, "crew_start", used_up)
    woke = watch.once(ws)
    assert len(woke) == 1 and "stage" not in woke[0]
    assert woke[0]["why"].startswith(
        "crew task booking-form is done; Factory could not start the check stage itself: "
    )
    assert len(manager_runs(ws, order)) == 2


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


def test_malformed_ticket_does_not_stop_the_loop(ws, run, monkeypatch, capsys):
    order, _ = started(ws, run)
    edit(ws, order, lambda t: t.update(questions="broken"))
    passes = []

    def sleep(_):
        passes.append(1)
        if len(passes) == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        watch.loop(ws, sleep=sleep)
    assert len(passes) == 2
    err = capsys.readouterr().err
    assert "order skipped" in err or "pass failed" in err


def test_a_pass_that_raises_is_survived(ws, monkeypatch, capsys):
    calls = []

    def boom(root):
        calls.append(1)
        raise ValueError("bad")

    monkeypatch.setattr(watch, "once", boom)

    def sleep(_):
        if len(calls) == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        watch.loop(ws, sleep=sleep)
    assert len(calls) == 2 and capsys.readouterr().err.count("pass failed: ValueError") == 2


def test_non_dict_error_body_is_a_refusal(ws, monkeypatch):
    script = ws.parent / "bad-orch"
    script.write_text(f"#!{sys.executable}\nprint('[1, 2]')\nraise SystemExit(3)\n")
    script.chmod(0o755)
    monkeypatch.setenv("ORCH_BIN", str(script))
    with pytest.raises(Refused):
        orchcli.call(ws, "ticket", "list")


def test_first_sight_wakes_for_a_crew_task_already_done(ws, run):
    order, _ = started(ws, run)
    run("next", order)
    finish_crew(ws, run, order, "booking-form")
    assert not (ws / ".orch/addons/factory/watch.json").exists()  # the watcher never saw this order
    woke = watch.once(ws)
    assert woke == [{"order": order, "why": "crew task booking-form is done"}]
    assert watch.once(ws) == [] and len(runs(ws)) == 1  # recorded: never again


def test_first_sight_with_an_open_stop_does_not_wake(ws, run):
    order, _ = started(ws, run)
    run("next", order)
    finish_crew(ws, run, order, "booking-form")
    ask_stop(ws, run, order, "build", {"title": "Look", "tag": "taste"})
    assert watch.once(ws) == [] and runs(ws) == []


def test_second_start_while_the_lock_is_held_refuses_cleanly(ws):
    d = runfiles.run_dir(ws, "factory")
    with service._start_lock(d, 1), pytest.raises(RuntimeError, match="in progress"):
        service.start(ws, wait=0.3)
    assert service.running_pid(ws, clean=False) is None  # nothing was spawned


def test_start_lock_refuses_a_link(ws, tmp_path):
    d = runfiles.run_dir(ws, "factory")
    target = tmp_path / "elsewhere"
    target.write_text("x")
    (d / "start.lock").symlink_to(target)
    with pytest.raises(RuntimeError, match="symbolic link"):
        service.start(ws, wait=0.3)
    assert target.read_text() == "x"


def test_concurrent_starts_share_one_watcher(ws):
    import threading

    pids = []
    threads = [threading.Thread(target=lambda: pids.append(service.start(ws))) for _ in range(2)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        assert len(pids) == 2 and pids[0] == pids[1]
    finally:
        service.stop(ws)


def test_announce_never_overwrites_a_live_watchers_record(ws, monkeypatch):
    pid = service.start(ws)
    try:
        path = runfiles.run_dir(ws, "factory") / "factory.json"
        before = path.read_bytes()
        monkeypatch.setenv(service.NONCE_ENV, "c" * 32)
        with pytest.raises(RuntimeError, match="already running"):
            service.announce(ws)
        assert path.read_bytes() == before and service.running_pid(ws) == pid
    finally:
        service.stop(ws)


def test_stop_waits_until_the_watcher_is_gone(ws):
    service.start(ws)
    assert service.stop(ws) == "stopped"
    assert service.running_pid(ws, clean=False) is None
    assert not (runfiles.run_dir(ws, "factory") / "factory.json").exists()


def test_the_watcher_keeps_the_shown_active_time_current_while_the_manager_is_idle(ws, run, monkeypatch):
    order, _ = started(ws, run)
    run("next", order)
    tid = run("crew", "add", order, "booking-form")["ticket"]
    times = ["2026-11-15T10:00:00Z", "2026-11-15T10:04:00Z", "2026-11-15T10:08:00Z"]
    (ws / "record.json").write_text(json.dumps({tid: [{"run": "r1", "at": t} for t in times]}))
    watch.once(ws)
    used = core(ws, "ticket", "show", order)["ext"]["factory"]["budget"]["active_min_used"]
    assert used == 8
    # measured at most once a minute: a longer record is not read again at once
    (ws / "record.json").write_text(
        json.dumps({tid: [{"run": "r1", "at": t} for t in [*times, "2026-11-15T10:12:00Z"]]})
    )
    watch.once(ws)
    assert core(ws, "ticket", "show", order)["ext"]["factory"]["budget"]["active_min_used"] == 8
    monkeypatch.setattr(watch.time, "time", lambda: 9e12)
    watch.once(ws)
    assert core(ws, "ticket", "show", order)["ext"]["factory"]["budget"]["active_min_used"] == 12
