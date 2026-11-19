"""Times a person gives Usage for a rule's end, in the workspace's time zone (`[workspace] tz` in .orch/config.toml,
else this computer's zone), to the minute.

    tomorrow            the end of tomorrow (midnight after it)
    tomorrow 08:00      that minute; today 18:00, 2026-11-19 07:59 and 2026-11-19T07:59 the same way
    reset               the account's next reset (a subscription's week, else its 5 hours; a monthly limit: the 1st)

Stored as UTC 'YYYY-MM-DDTHH:MM:00Z'.
"""

from __future__ import annotations

import re
import tomllib
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path

from .store import Refused

RESET_WORDS = ("reset", "next-reset", "next reset", "at its next reset", "at-reset")
_DAY_TIME = re.compile(r"(today|tomorrow|\d{4}-\d\d-\d\d)(?:[ t](\d{1,2}):(\d\d))?")


def zone(root: Path) -> tzinfo | None:
    """The workspace's zone; None = this computer's own (what `astimezone(None)` uses)."""
    import zoneinfo

    try:
        cfg = tomllib.loads((root / ".orch" / "config.toml").read_text(encoding="utf-8"))
        name = (cfg.get("workspace") or {}).get("tz")
        return zoneinfo.ZoneInfo(name) if isinstance(name, str) and name else None
    except (OSError, ValueError, zoneinfo.ZoneInfoNotFoundError):  # no config, or a zone it does not know
        return None


def _wall(day: datetime, hour: int, minute: int, tz: tzinfo | None) -> datetime:
    """That wall-clock minute in the zone, as an aware time."""
    naive = datetime(day.year, day.month, day.day, hour, minute)
    return naive.replace(tzinfo=tz) if tz is not None else naive.astimezone()


def stamp(when: datetime) -> str:
    return when.astimezone(UTC).replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_reset(text: str | None) -> bool:
    return " ".join((text or "").strip().lower().split()) in RESET_WORDS


def parse_end(text: str, now: datetime, tz: tzinfo | None, reset: str | None = None, label: str = "") -> str:
    """A person's end words -> stored UTC time. Refused (plain words) when unknown or already passed."""
    t = " ".join((text or "").strip().lower().split())
    if is_reset(t):
        if not reset:
            raise Refused(
                f"Usage does not know when {label or 'this account'} resets next. Pick a day and a time instead."
            )
        when = to_utc(reset)
    else:
        m = _DAY_TIME.fullmatch(t)
        if m:
            today = now.astimezone(tz)
            if m[1] == "today":
                day = today
            elif m[1] == "tomorrow":
                day = today + timedelta(days=1)
            else:
                try:
                    day = datetime.strptime(m[1], "%Y-%m-%d")
                except ValueError:
                    raise Refused(f"'{text}' is not a date.") from None
            if m[2] is None:  # a day only: to the end of that day
                when = _wall(day + timedelta(days=1), 0, 0, tz)
            else:
                hour, minute = int(m[2]), int(m[3])
                if hour > 23 or minute > 59:
                    raise Refused(f"'{text}' is not a time. Write it like 08:00 or 17:30.")
                when = _wall(day, hour, minute, tz)
        else:
            try:
                when = datetime.fromisoformat(text.strip())
            except ValueError:
                raise Refused(
                    f"'{text}' is not a day or time. Write it like tomorrow, tomorrow 08:00 or 2026-11-19 07:59."
                ) from None
            if when.tzinfo is None:
                when = when.replace(tzinfo=tz) if tz is not None else when.astimezone()
    out = stamp(when)
    if to_utc(out) <= now:
        raise Refused(f"{text} has already passed. Pick a time in the future.")
    return out


def to_utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def next_reset(row: dict, now: datetime, tz: tzinfo | None) -> str | None:
    """When the account starts again next, to the minute (UTC), or None when Usage does not know.
    A subscription: its week window's reset, else its 5-hour window's. A monthly limit: the 1st, 00:00."""
    use = row.get("use") or {}
    for name in ("week", "5h"):
        at = (use.get(name) or {}).get("resets_at")
        if isinstance(at, str):
            try:
                t = to_utc(at).replace(second=0, microsecond=0)
            except ValueError:
                continue
            if t > now:
                return stamp(t)
    if any(lim.get("period") == "month" for lim in (row.get("rule") or {}).get("limits", [])):
        local = now.astimezone(tz)
        first = (local.replace(day=1) + timedelta(days=32)).replace(day=1)
        return stamp(_wall(first, 0, 0, tz))
    return None


def local(at: str, tz: tzinfo | None) -> str:
    """A stored UTC time as the workspace's wall clock: 'YYYY-MM-DD' for the end of a day (local midnight: the day
    before it), else 'YYYY-MM-DDTHH:MM'. The page writes it with the kit's one date format."""
    t = to_utc(at).astimezone(tz)
    if (t.hour, t.minute) == (0, 0):
        return (t - timedelta(days=1)).strftime("%Y-%m-%d")
    return t.strftime("%Y-%m-%dT%H:%M")


def words(at: str, tz: tzinfo | None) -> str:
    """For the history and the command line, in the kit's date format with the zone (ORCH-619):
    '19 Nov 2026, 08:00 CET' or 'at the end of 19 Nov 2026'."""
    t = to_utc(at).astimezone(tz)
    if (t.hour, t.minute) == (0, 0):
        d = t - timedelta(days=1)
        return f"at the end of {d.day} {d:%b %Y}"
    return f"{t.day} {t:%b %Y, %H:%M %Z}".strip()
