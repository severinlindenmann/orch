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


# Day 29-31 of the month: in a shorter month the run happens on that month's last day.
_SHORT_MONTHS = {29: "2", 30: "2", 31: "2,4,6,9,11"}


def _exprs(expr: str) -> list[str]:
    """The cron expression, plus (for a single day 29-31) one that runs on the last day of the shorter months."""
    f = expr.split()
    if len(f) == 5 and f[2] in ("29", "30", "31") and f[3] == "*" and f[4] == "*":
        return [expr, " ".join([f[0], f[1], "L", _SHORT_MONTHS[int(f[2])], "*"])]
    return [expr]


def last_due(expr: str, now: datetime, tz: tzinfo | None = None) -> datetime | None:
    """The latest planned time at or before `now` (UTC)."""
    if not valid(expr):
        return None
    local = now.astimezone(tz or UTC)
    return max(croniter(e, local).get_prev(datetime) for e in _exprs(expr)).astimezone(UTC)


def is_due(expr: str, since: datetime, now: datetime, tz: tzinfo | None = None) -> bool:
    """True if a scheduled time lies in (since, now]. Any number of missed times still means one run."""
    prev = last_due(expr, now, tz)
    return prev is not None and since < prev <= now


def next_after(expr: str, now: datetime, tz: tzinfo | None = None) -> datetime | None:
    if not valid(expr):
        return None
    local = now.astimezone(tz or UTC)
    return min(croniter(e, local).get_next(datetime) for e in _exprs(expr)).astimezone(UTC)
