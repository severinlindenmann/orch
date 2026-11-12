import json
import os
import subprocess
import sys
import threading
import time

import pytest
from orch import procs, services

from orch_sync import cli, loop, orchcli, pause, service, step


class Stop(Exception):
    pass


@pytest.fixture
def on(root, monkeypatch):
    monkeypatch.setattr(orchcli, "is_active", lambda r: True)
    return root


@pytest.fixture
def core_unknown(monkeypatch):
    """For real loop processes: the loop asks the core whether the add-on is on here. With no orch home allowed
    (ORCH_HOME_STRICT, no ORCH_HOME) the core cannot answer: unknown, so the loop keeps running, like automation.
    A planted ORCH_BIN is never used."""
    monkeypatch.delenv("ORCH_HOME", raising=False)
    monkeypatch.setenv("ORCH_HOME_STRICT", "1")
    monkeypatch.setenv("ORCH_BIN", "/nonexistent/planted-orch")


@pytest.fixture
def spawned(monkeypatch):
    """Every loop process service.start spawns (the real spawn); none outlives the test."""
    children, real = [], orchcli.spawn

    def spawn(*args, **kwargs):
        children.append(real(*args, **kwargs))
        return children[-1]

    monkeypatch.setattr(orchcli, "spawn", spawn)
    yield children
    for child in children:
        if child.poll() is None:
            child.kill()
        child.wait(10)


def until(check, secs=10):
    end = time.monotonic() + secs
    while not (value := check()) and time.monotonic() < end:
        time.sleep(0.05)
    return value


def record(root, **rec):
    d = root / ".orch/run/sync"
    d.mkdir(parents=True, exist_ok=True)
    (d / "process.json").write_text(json.dumps(rec))
    return rec


def slow_pass(monkeypatch):
    """step.run_once that waits for `release` (a long fetch or push); returns (entered, release, done)."""
    entered, release, done = threading.Event(), threading.Event(), []

    def run_once(root, reason):
        entered.set()
        release.wait(10)
        done.append(reason)
        return {"last_error": None}

    monkeypatch.setattr(step, "run_once", run_once)
    return entered, release, done


def settings(root, **values):
    d = root / ".orch/run/sync"
    d.mkdir(parents=True, exist_ok=True)
    (d / "settings.json").write_text(json.dumps({"kind": "private", **values}))


def info(root):
    return json.loads((root / ".orch/run/sync/loop.json").read_text())


def drive(lp, passes):
    """Run the loop with a fake wait: returns the waits (seconds) of `passes` passes."""
    waits = []

    def wait(secs):
        waits.append(secs)
        if len(waits) >= passes:
            raise Stop

    with pytest.raises(Stop):
        lp.run_forever(wait=wait)
    return waits


def results(monkeypatch, *items):
    """step.run_once answers `items` in turn (an exception is raised); returns the calls."""
    calls, todo = [], list(items)

    def run_once(root, reason):
        calls.append(reason)
        item = todo.pop(0) if todo else {"last_error": None}
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(step, "run_once", run_once)
    return calls


def test_interval_selection():
    assert loop.minutes({"mode": "local", "interval": 60}) == 5  # local: every 5 minutes at most
    for n in (5, 15, 60):
        assert loop.minutes({"mode": "remote", "interval": n}) == n
    for bad in (0, 7, 30, -15, "5", 5.0, True, None):
        assert loop.minutes({"mode": "remote", "interval": bad}) == 15


def test_backoff_sequence_capped_and_reset(root):
    lp, offline = loop.Loop(root), {"last_error": "offline"}
    five = {"mode": "remote", "interval": 5}
    assert [lp.delay(offline, five) for _ in range(5)] == [60, 120, 240, 300, 300]
    assert lp.delay({"last_error": None}, five) == 300  # success resets
    assert lp.delay(offline, five) == 60
    lp = loop.Loop(root)
    hour = {"mode": "remote", "interval": 60}
    assert [lp.delay(offline, hour) for _ in range(8)][-1] == 3600  # never longer than the interval
    assert lp.delay({"last_error": "Sync stopped: KeyError"}, hour) == 3600  # other errors: no retry storm


def test_loop_backs_off_while_offline(on, monkeypatch):
    settings(on, mode="remote", interval=15)
    calls = results(monkeypatch, *[{"last_error": "offline"}] * 3, {"last_error": None})
    assert drive(loop.Loop(on, clock=lambda: 1_000_000), 5) == [60, 120, 240, 900, 900]
    assert calls == ["timer"] * 5
    assert info(on)["last_try"] == "1970-01-12T13:46:40Z" and info(on)["next_run"] == "1970-01-12T14:01:40Z"


def test_paused_tick_does_nothing(on, monkeypatch):
    settings(on, mode="local")
    calls = results(monkeypatch)
    monkeypatch.setattr(pause, "verified_pause", lambda root, state: {"files": [], "reason": "x"})
    assert loop.Loop(on).tick() is None
    assert drive(loop.Loop(on), 2) == [300, 300]
    assert calls == []


def test_planted_pause_does_not_stop_the_loop(on, monkeypatch):
    settings(on, mode="local")
    (on / ".orch/run/sync/state.json").write_text(json.dumps({"paused": {"files": [], "reason": "x", "mac": "0"}}))
    calls = results(monkeypatch)
    loop.Loop(on).run_forever(once=True)
    assert calls == ["timer"]


def test_tick_exception_keeps_the_loop_and_records_it(on, monkeypatch):
    settings(on, mode="local")
    calls = results(monkeypatch, RuntimeError("boom"), {"last_error": None})
    seen = []
    lp = loop.Loop(on)

    def wait(secs):
        seen.append(info(on)["last_error"])
        if len(seen) == 2:
            raise Stop

    with pytest.raises(Stop):
        lp.run_forever(wait=wait)
    assert calls == ["timer", "timer"]
    assert seen == ["Sync stopped: RuntimeError", None]


def test_turned_off_or_sync_off_ends_the_loop(root, monkeypatch):
    calls = results(monkeypatch)
    settings(root, mode="local")
    monkeypatch.setattr(orchcli, "is_active", lambda r: False)
    assert loop.Loop(root).run_forever(wait=lambda s: pytest.fail("no wait")) == "the sync add-on is turned off here"
    answers = iter([True, False])
    monkeypatch.setattr(orchcli, "is_active", lambda r: next(answers))
    assert loop.Loop(root).run_forever(wait=lambda s: None) == "the sync add-on is turned off here"  # after a pass
    assert calls == ["timer"]
    monkeypatch.setattr(orchcli, "is_active", lambda r: None)  # unknown: keep running, but sync is off here
    settings(root, mode="off")
    assert loop.Loop(root).run_forever(wait=lambda s: pytest.fail("no wait")) == "sync is set to off here"
    assert calls == ["timer"]


def test_every_end_leaves_one_log_line(root, monkeypatch, capsys):
    monkeypatch.setattr(orchcli, "is_active", lambda r: None)
    settings_file = root / ".orch/run/sync/settings.json"
    for prepare, why in (
        (lambda: None, "no readable sync settings here (counted as off)"),
        (lambda: settings_file.write_text("{not json"), "no readable sync settings here (counted as off)"),
        (lambda: settings(root, mode="off"), "sync is set to off here"),
        (lambda: (settings(root, mode="local"), monkeypatch.setattr(orchcli, "is_active", lambda r: False)),
         "the sync add-on is turned off here"),
    ):
        prepare()
        assert cli._run_loop(root) == 0
        assert capsys.readouterr().out.splitlines() == [f"sync: the loop ended: {why}"]
        assert not service.lock_held(root) and not (root / ".orch/run/sync/process.json").exists()
    monkeypatch.setattr(loop.Loop, "ended", lambda self: {}["boom"])
    assert cli._run_loop(root) == 2
    out = capsys.readouterr().out
    assert "Traceback" in out and "KeyError" in out
    assert out.splitlines()[-1] == "sync: the loop ended: an error (traceback above)"
    assert not service.lock_held(root)


def test_tick_tracebacks_are_logged_once_while_they_repeat(on, monkeypatch, capsys):
    settings(on, mode="local")
    boom = RuntimeError("boom")
    results(monkeypatch, boom, boom, boom, {"last_error": None}, boom)
    drive(loop.Loop(on), 5)
    out = capsys.readouterr().out
    assert out.count("Traceback") == 2 and out.count("sync: Sync stopped: RuntimeError") == 2


def test_waiting_loop_rechecks_the_addon(on, monkeypatch):
    monkeypatch.setattr(loop, "POLL", 0.01)
    monkeypatch.setattr(loop, "RECHECK", 0.05)
    asked = []
    monkeypatch.setattr(orchcli, "is_active", lambda r: asked.append(r) or len(asked) < 3)
    begin = time.monotonic()
    loop.Loop(on).sleep(30)  # a 60-minute interval would be just as short
    assert time.monotonic() - begin < 5 and len(asked) == 3


def test_wake_triggers_an_immediate_tick(on, monkeypatch):
    settings(on, mode="remote", interval=60)
    monkeypatch.setattr(loop, "POLL", 0.01)
    calls = results(monkeypatch)
    lp = loop.Loop(on)
    worker = threading.Thread(target=lp.run_forever, daemon=True)
    worker.start()

    def until(n):
        end = time.monotonic() + 5
        while len(calls) < n and time.monotonic() < end:
            time.sleep(0.01)
        return len(calls)

    assert until(1) == 1
    lp.wake.set()  # in this process
    assert until(2) == 2
    loop.wake_up(on)  # from another process: `orch sync now` / `orch sync set`
    assert until(3) == 3
    monkeypatch.setattr(orchcli, "is_active", lambda r: False)
    lp.wake.set()
    worker.join(5)
    assert not worker.is_alive() and calls == ["timer"] * 3
    assert not (on / ".orch/run/sync/wake").exists()


def test_synced_config_cannot_change_mode_or_interval(on, monkeypatch):
    (on / ".orch/config.toml").write_text('[sync]\nmode = "remote"\ninterval = 5\nkind = "team"\n')
    (on / ".orch/tickets").mkdir()
    (on / ".orch/tickets/t_abcdef.json").write_text(json.dumps({"sync": {"mode": "remote", "interval": 5}}))
    monkeypatch.setenv("ORCH_SYNC_INTERVAL", "5")
    calls = results(monkeypatch)
    loop.Loop(on).run_forever(wait=lambda s: pytest.fail("off here: no pass"))  # no local settings = off
    assert calls == []
    settings(on, mode="remote", interval=60)
    lp = loop.Loop(on)
    assert lp.settings()["mode"] == "remote" and lp.settings()["kind"] == "private"
    assert drive(lp, 1) == [3600]


def test_start_status_stop_real_process(root, core_unknown, spawned):
    settings(root, mode="local")
    pid = service.start(root)
    try:
        running, again = service.running_pid(root), service.start(root)
    finally:
        stopped = service.stop(root, wait=30)
    assert running == pid and again == pid and len(spawned) == 1  # no second one
    assert stopped == "stopped" and spawned[0].wait(10) == 0  # it ended by itself, after its pass
    assert service.running_pid(root) is None and service.stop(root) == "not running"
    log = (root / ".orch/run/sync/loop.log").read_text()
    assert log.splitlines()[-1] == "sync: the loop ended: stopped on request"
    assert not (root / ".orch/run/sync/stop").exists()


def test_two_concurrent_starts_make_exactly_one_loop(root, core_unknown, spawned):
    settings(root, mode="local")
    gate, pids = threading.Barrier(2), []

    def go():
        gate.wait()
        pids.append(service.start(root))

    starts = [threading.Thread(target=go) for _ in range(2)]
    try:
        for t in starts:
            t.start()
        for t in starts:
            t.join(30)
        one = until(lambda: sum(child.poll() is None for child in spawned) == 1)
        running = service.running_pid(root)
    finally:
        service.stop(root, wait=30)
    assert len(spawned) == 2  # both saw no loop and spawned one: the lock decided
    assert one and len(pids) == 2 and pids[0] == pids[1] == running
    log = (root / ".orch/run/sync/loop.log").read_text()
    assert log.count("sync: another sync loop already runs for this folder; this one ends.") == 1


def test_a_foreground_run_blocks_a_second_loop(root, core_unknown, spawned, tmp_path, capsys):
    settings(root, mode="local")
    env = {k: v for k, v in os.environ.items() if k != service.NONCE_ENV}
    with open(tmp_path / "foreground.log", "w") as out:
        fg = subprocess.Popen([sys.executable, "-P", "-m", "orch_sync", "--dir", str(root), "run"], cwd=tmp_path,
                              stdout=out, stderr=subprocess.STDOUT, env=env)
    try:
        pid = until(lambda: service.running_pid(root))
        capsys.readouterr()
        second = cli.main(["--dir", str(root), "run"])
        printed = capsys.readouterr().out
        started, still = service.start(root), service.running_pid(root)
    finally:
        stopped = service.stop(root, wait=30)
        if fg.poll() is None:
            fg.kill()
        fg.wait(10)
    assert pid and second == 0
    assert printed.splitlines() == ["sync: another sync loop already runs for this folder; this one ends."]
    assert started == still == pid and spawned == []  # start finds the foreground loop: no second one
    assert stopped == "stopped" and fg.returncode == 0


def test_stop_during_a_slow_pass_finishes_the_pass(on, monkeypatch):
    settings(on, mode="local")
    entered, release, done = slow_pass(monkeypatch)
    lp, ended = loop.Loop(on), []
    worker = threading.Thread(target=lambda: ended.append(lp.run_forever()), daemon=True)
    worker.start()
    assert entered.wait(5)
    lp.stop()  # what SIGTERM does
    time.sleep(0.2)
    assert worker.is_alive() and done == []  # the sync is not cut off
    release.set()
    worker.join(5)
    assert not worker.is_alive() and done == ["timer"] and ended == ["stopped on request"]
    assert info(on)["last_error"] is None and info(on)["next_run"]


def test_orch_sync_stop_waits_for_the_pass(on, monkeypatch, capsys):
    settings(on, mode="local")
    monkeypatch.setattr(loop, "POLL", 0.01)
    entered, release, done = slow_pass(monkeypatch)
    forced = []
    monkeypatch.setattr(service, "_force", lambda *a: forced.append(a))
    worker = threading.Thread(target=cli._run_loop, args=(on,), daemon=True)
    worker.start()
    assert entered.wait(5) and service.running_pid(on) == os.getpid()
    answer = []
    stopper = threading.Thread(target=lambda: answer.append(service.stop(on, wait=10)), daemon=True)
    stopper.start()
    assert until(lambda: (on / ".orch/run/sync/stop").exists())
    time.sleep(0.2)
    assert worker.is_alive() and answer == []  # stop waits for the pass
    release.set()
    stopper.join(10)
    worker.join(10)
    assert answer == ["stopped"] and forced == [] and done == ["timer"]
    assert not service.lock_held(on) and not (on / ".orch/run/sync/process.json").exists()
    assert not (on / ".orch/run/sync/stop").exists()
    assert capsys.readouterr().out.splitlines()[-1] == "sync: the loop ended: stopped on request"


def test_stop_forces_only_after_its_wait(on, monkeypatch):
    settings(on, mode="local")
    monkeypatch.setattr(loop, "POLL", 0.01)
    entered, release, done = slow_pass(monkeypatch)
    forced = []
    monkeypatch.setattr(service, "_force", lambda root, rec, pid: forced.append(pid))
    worker = threading.Thread(target=cli._run_loop, args=(on,), daemon=True)
    worker.start()
    assert entered.wait(5)
    begin = time.monotonic()
    assert service.stop(on, wait=0.5) == "stopped"
    assert time.monotonic() - begin >= 0.5 and forced == [os.getpid()] and done == []
    monkeypatch.setattr(orchcli, "is_active", lambda r: False)  # (nothing was really forced) end the thread
    release.set()
    loop.wake_up(on)
    worker.join(10)
    assert not worker.is_alive()


def test_planted_process_record_is_never_signalled(root, monkeypatch):
    sent, real = [], os.kill
    monkeypatch.setattr(os, "kill", lambda pid, sig: real(pid, 0) if sig == 0 else sent.append((pid, sig)))
    monkeypatch.setattr(procs, "stop_tree", lambda pid, verified: sent.append((pid, "tree")) or True)
    me = os.getpid()
    record(root, pid=me, nonce="1" * 32, started=procs.pid_started(me))  # a live process, its real start time
    assert service.running_pid(root) is None  # no loop holds the lock
    assert service.stop(root) == "not verified" and sent == []
    assert not (root / ".orch/run/sync/process.json").exists()  # not ours, nobody holds the lock: dropped


def test_reused_pid_is_never_signalled_while_a_loop_holds_the_lock(root, monkeypatch):
    sent, real = [], os.kill
    monkeypatch.setattr(os, "kill", lambda pid, sig: real(pid, 0) if sig == 0 else sent.append((pid, sig)))
    monkeypatch.setattr(procs, "stop_tree", lambda pid, verified: sent.append((pid, "tree")) or True)
    held = service.announce(root)
    try:
        assert service.running_pid(root) == os.getpid()
        reused = record(root, pid=os.getpid(), nonce="3" * 32, started="2001-01-01T00:00:00Z")
        assert service.running_pid(root) is None
        assert service.stop(root) == "not verified" and sent == []
        assert json.loads((root / ".orch/run/sync/process.json").read_text()) == reused  # a loop runs: kept
    finally:
        service.forget(root, held)


def test_stale_dead_pid_record_is_not_running(root, capsys):
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait(10)
    settings(root, mode="local")
    record(root, pid=gone.pid, nonce="2" * 32, started="2026-01-01T00:00:00Z")
    assert cli.main(["--dir", str(root), "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["running"] is False
    assert cli.main(["--dir", str(root), "stop", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"stopped": False}  # "not running", no "not the loop" note
    assert not (root / ".orch/run/sync/process.json").exists()
    record(root, pid=gone.pid, nonce="2" * 32, started="2026-01-01T00:00:00Z")
    assert service.stop(root) == "not running"


def test_a_record_that_changed_since_it_was_read_is_kept(root, monkeypatch):
    record(root, pid=999_999, nonce="2" * 32, started="2026-01-01T00:00:00Z")
    fresh = {"pid": os.getpid(), "nonce": "4" * 32, "started": "2026-01-02T00:00:00Z"}

    def alive(pid):  # a new loop writes its record while stop looks at the old one
        record(root, **fresh)
        return False

    monkeypatch.setattr(services, "pid_alive", alive)
    assert service.stop(root) == "not running"
    assert json.loads((root / ".orch/run/sync/process.json").read_text()) == fresh


def test_announce_takes_the_lock_and_drops_the_nonce(root, monkeypatch):
    monkeypatch.setenv(service.NONCE_ENV, "a" * 32)
    held = service.announce(root)
    try:
        assert service.NONCE_ENV not in os.environ and held[1] == "a" * 32  # git and orch never see it
        assert json.loads((root / ".orch/run/sync/process.json").read_text())["nonce"] == "a" * 32
        assert service.lock_held(root)
        monkeypatch.setattr(service, "TAKE", 0.1)
        assert service.announce(root) is None  # a second loop, even in this process
    finally:
        service.forget(root, held)
    assert not service.lock_held(root) and not (root / ".orch/run/sync/process.json").exists()
    held = service.announce(root)  # a foreground run (no nonce from start) records itself too
    try:
        assert service.NONCE.fullmatch(held[1]) and service.running_pid(root) == os.getpid()
    finally:
        service.forget(root, held)


def test_loop_log_is_capped_at_start(root):
    log = root / ".orch/run/sync/loop.log"
    log.parent.mkdir(parents=True)
    log.write_text("old line\n")
    with service._log(root) as out:
        out.write("new line\n")
    assert log.read_text() == "old line\nnew line\n"
    log.write_text("x" * (service.LOG_CAP + 1))
    with service._log(root) as out:
        out.write("new line\n")
    assert log.read_text() == "new line\n"


def test_core_is_this_python_never_orch_bin_or_path(root, tmp_path, monkeypatch):
    marker = tmp_path / "planted-ran"
    fake = tmp_path / "bin" / "orch"
    fake.parent.mkdir()
    fake.write_text(f"#!/bin/sh\ntouch {marker}\necho '[{{\"name\": \"sync\", \"active\": true}}]'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("ORCH_BIN", str(fake))
    monkeypatch.setenv("PATH", f"{fake.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    seen = []
    real = orchcli._run
    monkeypatch.setattr(orchcli, "_run", lambda argv, **kw: seen.append((argv, kw)) or real(argv, **kw))
    assert orchcli.is_active(root) is not True  # the real core: sync is not turned on here
    assert not marker.exists()
    argv, kw = seen[0]
    assert argv == [sys.executable, "-I", "-P", "-m", "orch", "addon", "list", "--json"]
    assert "ORCH_BIN" not in kw["env"] and kw["cwd"] == root


def test_loop_spawn_uses_an_absolute_python_outside_the_workspace(root, monkeypatch):
    seen = []
    monkeypatch.setattr(orchcli, "_popen", lambda argv, **kw: seen.append((argv, kw)))
    orchcli.spawn(["--dir", str(root), "run"], None, {})
    argv, kw = seen[0]
    assert argv[:4] == [sys.executable, "-P", "-m", "orch_sync"] and os.path.isabs(argv[0])
    assert kw["cwd"] == orchcli.HOME and root.resolve() not in (kw["cwd"], *kw["cwd"].parents)
    monkeypatch.setattr(sys, "executable", "python3")
    with pytest.raises(OSError):
        orchcli.spawn(["run"], None, {})
    assert len(seen) == 1
