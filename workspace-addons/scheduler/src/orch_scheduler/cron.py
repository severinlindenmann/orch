"""5-field cron, always UTC. Missed runs collapse into one catch-up run."""
from __future__ import annotations

from datetime import UTC, datetime

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


def is_due(expr: str, since: datetime, now: datetime) -> bool:
    """True if a scheduled time lies in (since, now]. Any number of missed times still means one run."""
    if not valid(expr):
        return False
    prev = croniter(expr, now).get_prev(datetime)
    return since < prev.astimezone(UTC) <= now


def next_after(expr: str, now: datetime) -> datetime | None:
    if not valid(expr):
        return None
    return croniter(expr, now).get_next(datetime).astimezone(UTC)
