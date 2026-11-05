"""UX-05: plain-word repeats. Five phrases become a cron (read in a time zone) or a one-off time. Nothing else is accepted."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

EXAMPLES = ('every monday 08:00 · daily 07:30 · every 15 minutes · every 2 hours · monthly 1 09:00 · '
            'tomorrow 09:00 · today 17:30')
DAYS = {"sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4, "friday": 5, "saturday": 6}
_TIME = r"([01]?\d|2[0-3]):([0-5]\d)"


class Plain(ValueError):
    """The phrase is not one of the five; the message has examples."""


@dataclass
class Plan:
    cron: str | None = None  # a repeat
    until: str | None = None  # a one-off: UTC time for `orch wait --until`


def zone(name: str | None) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def local_tz_name() -> str:
    """The computer's IANA time zone ($TZ, else /etc/localtime), else UTC."""
    tz = os.environ.get("TZ", "").lstrip(":")
    if tz and zone(tz):
        return tz
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            name = target.split("zoneinfo/", 1)[1]
            if zone(name):
                return name
    except OSError:
        pass
    return "UTC"


def parse(text: str, tz: str, now: datetime | None = None) -> Plan:
    t = " ".join(str(text).lower().split())
    z = zone(tz)
    if z is None:
        raise Plain(f"'{tz}' is not a time zone. Use a name like Europe/Zurich.")
    m = re.fullmatch(rf"every (\w+) {_TIME}", t)
    if m and m[1] in DAYS:
        return Plan(cron=f"{int(m[3])} {int(m[2])} * * {DAYS[m[1]]}")
    m = re.fullmatch(rf"daily {_TIME}", t)
    if m:
        return Plan(cron=f"{int(m[2])} {int(m[1])} * * *")
    m = re.fullmatch(r"every (\d{1,3}) (minutes?|hours?)", t)
    if m and int(m[1]) >= 1:
        n = int(m[1])
        if m[2].startswith("minute") and n <= 59:
            return Plan(cron=f"*/{n} * * * *")
        if m[2].startswith("hour") and n <= 23:
            return Plan(cron=f"0 */{n} * * *")
    m = re.fullmatch(rf"monthly (\d{{1,2}}) {_TIME}", t)
    if m and 1 <= int(m[1]) <= 28:
        return Plan(cron=f"{int(m[3])} {int(m[2])} {int(m[1])} * *")
    m = re.fullmatch(rf"(today|tomorrow) {_TIME}", t)
    if m:
        local = (now or datetime.now(UTC)).astimezone(z)
        day = local.date() + timedelta(days=1 if m[1] == "tomorrow" else 0)
        at = datetime(day.year, day.month, day.day, int(m[2]), int(m[3]), tzinfo=z)
        if at <= local:
            raise Plain(f"{m[0]} is already past. Try tomorrow {m[2]}:{m[3]}.")
        return Plan(until=at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    raise Plain(f"I don't understand \"{text}\". Say it like: {EXAMPLES}. Monthly days go from 1 to 28.")


def daily_or_slower(cron: str) -> bool:
    """One fixed minute and hour (each_run needs this; also checked by the ext contract)."""
    return re.fullmatch(r"[0-9]{1,2} [0-9]{1,2} \S+ \S+ \S+", cron) is not None


def workspace_tz(root: Path) -> str | None:
    import tomllib

    try:
        t = tomllib.loads((root / ".orch" / "config.toml").read_text()).get("workspace")
    except (OSError, tomllib.TOMLDecodeError):
        return None
    name = t.get("tz") if isinstance(t, dict) else None
    return name if isinstance(name, str) and zone(name) else None
