import json
import threading
import time

import pytest

from orch_sync import loop, orchcli, pause, service, step


class Stop(Exception):
    pass


@pytest.fixture
def on(root, monkeypatch):
    monkeypatch.setattr(orchcli, "is_active", lambda r: True)
    return root


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
    loop.Loop(root).run_forever(wait=lambda s: pytest.fail("no wait"))
    answers = iter([True, False])
    monkeypatch.setattr(orchcli, "is_active", lambda r: next(answers))
    assert loop.Loop(root).run_forever(wait=lambda s: None) is None  # turned off after one pass
    assert calls == ["timer"]
    monkeypatch.setattr(orchcli, "is_active", lambda r: None)  # unknown: keep running, but sync is off here
    settings(root, mode="off")
    loop.Loop(root).run_forever(wait=lambda s: pytest.fail("no wait"))
    assert calls == ["timer"]


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


def test_start_status_stop_real_process(root, monkeypatch):
    settings(root, mode="local")
    monkeypatch.setenv("ORCH_BIN", str(root / "no-orch-here"))  # is_active unknown: the loop keeps running
    pid = service.start(root)
    try:
        assert service.running_pid(root) == pid
        assert service.start(root) == pid  # no second one
    finally:
        assert service.stop(root) == "stopped"
    end = time.monotonic() + 10
    while service.running_pid(root) is not None and time.monotonic() < end:
        time.sleep(0.1)
    assert service.running_pid(root) is None and service.stop(root) == "not running"


def test_planted_process_record_is_never_signalled(root, monkeypatch):
    import os

    sent, real = [], os.kill
    monkeypatch.setattr(os, "kill", lambda pid, sig: real(pid, 0) if sig == 0 else sent.append((pid, sig)))
    d = root / ".orch/run/sync"
    d.mkdir(parents=True)
    me = os.getpid()
    from orch import procs

    (d / "process.json").write_text(json.dumps({"pid": me, "nonce": "1" * 32, "started": procs.pid_started(me)}))
    assert service.running_pid(root, clean=False) is None  # not the loop's command line
    assert service.stop(root) == "not verified" and sent == []
