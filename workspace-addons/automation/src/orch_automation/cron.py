"""5-field cron, read in the job's time zone (UTC when none). Missed runs collapse into one catch-up run."""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo

from croniter import croniter


def parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts).astimezone(UTC)
    except ValueError:
        return None


def fmt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def valid(expr: str) -> bool:
    return isinstance(expr, str) and len(expr.split()) == 5 and croniter.is_valid(expr)


def last_due(expr: str, now: datetime, tz: tzinfo | None = None) -> datetime | None:
    """The latest planned time at or before `now` (UTC)."""
    if not valid(expr):
        return None
    return croniter(expr, now.astimezone(tz or UTC)).get_prev(datetime).astimezone(UTC)


def is_due(expr: str, since: datetime, now: datetime, tz: tzinfo | None = None) -> bool:
    """True if a scheduled time lies in (since, now]. Any number of missed times still means one run."""
    prev = last_due(expr, now, tz)
    return prev is not None and since < prev <= now


def next_after(expr: str, now: datetime, tz: tzinfo | None = None) -> datetime | None:
    if not valid(expr):
        return None
    return croniter(expr, now.astimezone(tz or UTC)).get_next(datetime).astimezone(UTC)
