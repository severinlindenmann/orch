"""One shared test clock for every Python test tree: workspace/tests and each add-on's tests (ORCH-451).

Three of four red develop spells in the night of 17/18 Nov came from tests that read the real clock: a
fixture made "a few minutes ago" landed on yesterday after midnight, a run id took the day twice and the day
changed in between. A test that shows or files something by the day runs on this clock, so it passes at any
hour CI picks:

    from testclock import Clock, at

    def test_the_label(monkeypatch):
        clock = Clock(at(23, 59, 59))           # local time, on the fixed day DAY
        clock.patch(monkeypatch, view, record)  # these modules now read `clock`
        clock.advance(2)                        # and the day turns over when the test says so

`Clock.patch` replaces a module's `datetime` (the class) and `time` (the module) names with stand-ins that
read this clock; everything else in them stays real, and so do monotonic time, sleeps and timeouts. Only the
named modules move, so a test says exactly which code is on the fixed clock. Add-on test trees reach this
file through their conftest (`sys.path` gets `workspace/tests`); page tests have the same clock in
`testclock.cjs` next to it.
"""

from __future__ import annotations

import datetime as _dt
import time as _time
from types import ModuleType, SimpleNamespace
from typing import Any

UTC = _dt.UTC
# The fixed day: a Wednesday mid-month, no daylight-saving change within a week in any zone CI uses.
DAY = _dt.date(2026, 11, 11)


def at(
    hour: int = 12, minute: int = 0, second: int = 0, *, day: _dt.date = DAY, tz: _dt.tzinfo | None = None
) -> _dt.datetime:
    """An aware datetime at hour:minute:second on `day`, in local time unless `tz` is given."""
    naive = _dt.datetime(day.year, day.month, day.day, hour, minute, second)
    return naive.replace(tzinfo=tz) if tz is not None else naive.astimezone()


def real_today(tz: _dt.tzinfo | None = None) -> _dt.date:
    """Today on the real clock (in `tz`, else local): for a clock pinned to an hour of the real day, where
    code that is not on the clock (retention, files the kernel stamps) must still see a fresh day."""
    return _dt.datetime.now(tz).date() if tz is not None else _dt.date.today()


class _AnyDatetime(type):
    """`isinstance(x, datetime)` in a patched module still holds for a real datetime made elsewhere."""

    def __instancecheck__(cls, obj: object) -> bool:
        return isinstance(obj, _dt.datetime)


class Clock:
    """A wall clock that stands still until the test moves it (`advance`, `set`)."""

    def __init__(self, start: _dt.datetime | None = None) -> None:
        self._now = (start or at(12)).astimezone(UTC)
        self.datetime = self._datetime_class()
        self.time = self._time_module()

    # ---- reading and moving ----
    def now(self, tz: _dt.tzinfo | None = None) -> _dt.datetime:
        """The clock's time, aware; in `tz`, or local when tz is None."""
        return self._now.astimezone(tz) if tz is not None else self._now.astimezone()

    def timestamp(self) -> float:
        return self._now.timestamp()

    def iso(self) -> str:
        """The clock's time as orch writes stamps: 2026-11-11T12:00:00Z."""
        return self._now.strftime("%Y-%m-%dT%H:%M:%SZ")

    def ago(self, **delta: float) -> _dt.datetime:
        """The clock's time minus a timedelta (`clock.ago(minutes=5)`), aware UTC."""
        return self._now - _dt.timedelta(**delta)

    def advance(self, seconds: float = 0, **delta: float) -> _dt.datetime:
        self._now += _dt.timedelta(seconds=seconds, **delta)
        return self._now

    def set(self, when: _dt.datetime) -> None:
        self._now = when.astimezone(UTC)

    # ---- putting code on this clock ----
    def patch(self, monkeypatch: Any, *modules: ModuleType) -> Clock:
        """Point each module's `datetime` class and `time` module names at this clock (the ones it has)."""
        for mod in modules:
            if isinstance(getattr(mod, "datetime", None), type):
                monkeypatch.setattr(mod, "datetime", self.datetime)
            if getattr(mod, "time", None) is _time:
                monkeypatch.setattr(mod, "time", self.time)
        return self

    def _datetime_class(self) -> type:
        clock = self

        class ClockDatetime(_dt.datetime, metaclass=_AnyDatetime):
            @classmethod
            def now(cls, tz: _dt.tzinfo | None = None):  # type: ignore[override]
                t = (
                    clock._now.astimezone(tz)
                    if tz is not None
                    else clock._now.astimezone().replace(tzinfo=None)
                )
                return cls._wrap(t)

            @classmethod
            def utcnow(cls):  # type: ignore[override]
                return cls._wrap(clock._now.replace(tzinfo=None))

            @classmethod
            def today(cls):  # type: ignore[override]
                return cls.now()

            @classmethod
            def _wrap(cls, t: _dt.datetime) -> _dt.datetime:
                return cls(t.year, t.month, t.day, t.hour, t.minute, t.second, t.microsecond, t.tzinfo)

        ClockDatetime.__name__ = ClockDatetime.__qualname__ = "datetime"
        return ClockDatetime

    def _time_module(self) -> SimpleNamespace:
        clock = self
        real = {k: getattr(_time, k) for k in dir(_time) if not k.startswith("__")}

        def now() -> float:
            return clock._now.timestamp()

        def gmtime(secs: float | None = None):
            return _time.gmtime(now() if secs is None else secs)

        def localtime(secs: float | None = None):
            return _time.localtime(now() if secs is None else secs)

        def strftime(fmt: str, t=None) -> str:
            return _time.strftime(fmt, localtime() if t is None else t)

        def ctime(secs: float | None = None) -> str:
            return _time.ctime(now() if secs is None else secs)

        real.update(
            time=now,
            time_ns=lambda: int(now() * 1_000_000_000),
            gmtime=gmtime,
            localtime=localtime,
            strftime=strftime,
            ctime=ctime,
            asctime=lambda t=None: _time.asctime(localtime() if t is None else t),
        )
        return SimpleNamespace(**real)
