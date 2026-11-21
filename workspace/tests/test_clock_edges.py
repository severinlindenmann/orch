"""Focused midnight and time-zone tests on the shared test clock (ORCH-451).

The two whole-suite runs at a fake hour (CI job clock, 22:30 and 23:59:40 UTC) now run on merge queue groups,
at night and on pull requests that change time code. These few tests run everywhere, every time: the clock and
the day the unattributed record run is filed under. The "today / yesterday" labels have theirs where they live
(services add-on: tests/test_clock_edges.py; page labels: workspace/src/orch_ui/tests/clock_edges.test.mjs).
"""

from __future__ import annotations

import datetime as dt
import time
import types

from testclock import DAY, UTC, Clock, at

from orch import secretrun


# ---- the clock itself ----
def test_the_clock_stands_still_and_turns_the_day_when_told(monkeypatch):
    mod = types.ModuleType("m")
    mod.datetime, mod.time = dt.datetime, time
    clock = Clock(at(23, 59, 59)).patch(monkeypatch, mod)
    assert mod.datetime.now().date() == DAY and mod.time.strftime("%H:%M:%S") == "23:59:59"
    # waits and timeouts stay real
    assert mod.time.monotonic is time.monotonic and mod.time.sleep is time.sleep
    clock.advance(2)
    assert mod.datetime.now().date() == DAY + dt.timedelta(days=1)
    assert mod.datetime.now(UTC) == clock.now(UTC) and mod.time.time() == clock.timestamp()
    # a real datetime still counts in a patched module
    assert isinstance(dt.datetime(2026, 1, 1), mod.datetime)


def test_only_the_named_modules_move(monkeypatch):
    mod = types.ModuleType("m")
    mod.datetime, mod.time = dt.datetime, time
    Clock(at(3)).patch(monkeypatch, mod)
    # the rest of the process is on the real clock
    assert abs(time.time() - dt.datetime.now().timestamp()) < 5


# ---- the unattributed record run is the UTC day of each use ----
def test_the_unattributed_run_follows_the_utc_day_across_midnight(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(secretrun, "_run_ids", lambda: None)
    clock = Clock(at(23, 59, 59, tz=UTC)).patch(monkeypatch, secretrun)

    def grab():
        ev = {
            "kind": "secret.change",
            "outcome": {"ok": True},
            "profile": "plain",
            "action": "disable",
            "by": "test",
        }
        line = secretrun._record_event(tmp_path, ev)
        seen.append(line and line["run"])

    grab()
    clock.advance(2)
    grab()
    assert seen == ["r_outside_20261111", "r_outside_20261112"]
