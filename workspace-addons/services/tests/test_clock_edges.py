"""The services page's "today / yesterday" label on the shared test clock, both sides of local midnight, in four
time zones (ORCH-451). Runs with the services suite; the whole-suite fake-hour runs (CI job clock) run on queue groups."""

from __future__ import annotations

import datetime as dt
import time

import pytest
from testclock import DAY, UTC, at

from orch_services import view

ZONES = ["UTC", "America/Los_Angeles", "Asia/Kolkata", "Pacific/Auckland"]


@pytest.fixture
def zone(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip(
            "time zones switch with time.tzset, which Windows lacks (the same code runs on Linux and macOS)"
        )

    def use(name):
        monkeypatch.setenv("TZ", name)
        time.tzset()

    yield use
    monkeypatch.undo()
    time.tzset()


def _z(t: dt.datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.parametrize("name", ZONES)
def test_today_turns_into_yesterday_at_local_midnight(zone, name):
    zone(name)
    started = _z(at(23, 58))  # 23:58 on DAY in this zone
    assert view._when(started, at(23, 59, 50)) == "today 23:58"
    assert view._when(started, at(0, 0, 10, day=DAY + dt.timedelta(days=1))) == "yesterday 23:58"
    # local noon is another UTC day in Auckland (UTC+13): the label still goes by the local day
    assert view._when(_z(at(12)), at(12, 30)) == "today 12:00"
    assert view._when(_z(at(12)), at(0, 30, day=DAY + dt.timedelta(days=2))) == "Wed 11 Nov, 12:00"


def test_the_zone_really_changes(zone):
    # guards the test above: if TZ were ignored every zone would be UTC and prove nothing
    zone("Pacific/Auckland")
    assert at(12).utcoffset() == dt.timedelta(hours=13)
