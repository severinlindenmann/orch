"""Outlook calendar for Personal: the backup way in when the Calendar app cannot be used.

Personal runs it as the `read` action (values {"from": "YYYY-MM-DD", "days": n} on stdin) and expects the Calendar
reader's answer (schema orch.calendar.read/1) on stdout. The same rules per calendar apply afterwards; every Outlook
calendar starts at Nothing.

How it reaches Outlook is one command in fetch.json, next to this file:

    {"fetch": ["<program>", "<arg>", ...]}       e.g. {"fetch": ["python3", "./fetch_outlook.py"]}

("./x" is a file in this folder.) It runs in Personal's data folder for this way in, never in this folder.

It gets {"start": "<ISO time>", "end": "<ISO time>", "zone": "<IANA zone>"} on stdin and prints the Outlook calendars
with their events as Microsoft Graph returns them (calendarView), in one JSON object:

    {"calendars": [{"id": "...", "name": "Calendar", "owner": {"name": "..."}, "events": [<Graph event>, ...]}]}

Only these Graph fields are read: subject, start, end, isAllDay, isCancelled, showAs, responseStatus, organizer and
attendees (their names only). Body, location, links, online meeting and email addresses are never passed on.
Plain Python 3.9+ standard library (the Mac's own python3).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python < 3.9
    sys.exit("The Outlook calendar way in needs Python 3.9 or newer.")

SCHEMA = "orch.calendar.read/1"
FETCH_TIMEOUT = 50  # Personal stops a way in after 60 seconds
MAX_EVENTS = 2000
SHOW_AS = {
    "free": "free",
    "tentative": "tentative",
    "busy": "busy",
    "oof": "unavailable",
    "workingElsewhere": "busy",
}
# Outlook sometimes names Windows time zones; the common ones here, everything else must come as IANA or UTC.
WINDOWS_ZONES = {
    "UTC": "UTC",
    "W. Europe Standard Time": "Europe/Zurich",
    "Central Europe Standard Time": "Europe/Budapest",
    "Romance Standard Time": "Europe/Paris",
    "GMT Standard Time": "Europe/London",
    "Eastern Standard Time": "America/New_York",
    "Pacific Standard Time": "America/Los_Angeles",
}


class Stop(Exception):
    """One plain sentence for the person; the way in counts as stopped."""


def local_zone() -> str:
    tz = os.environ.get("TZ", "")
    if tz and not tz.startswith(":"):
        return tz
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return "UTC"


def zone_of(name: str) -> ZoneInfo | None:
    name = WINDOWS_ZONES.get(name, name)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def graph_time(v, all_day: bool) -> str | None:
    """A Graph dateTimeTimeZone as the reader writes it: a date for all-day, else a time with offset."""
    if not isinstance(v, dict) or not isinstance(v.get("dateTime"), str):
        return None
    raw = v["dateTime"]
    if all_day:
        return raw[:10]
    try:
        # Graph gives 7 decimals and sometimes Z; Python 3.9 reads at most 6 and no Z. The offset is kept.
        m = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)?", raw.strip())
        if not m:
            return None
        frac = f".{(m.group(2) + '000000')[:6]}" if m.group(2) else ""
        off = "+00:00" if m.group(3) == "Z" else (m.group(3) or "")
        t = dt.datetime.fromisoformat(m.group(1) + frac + off)
    except ValueError:
        return None
    if t.tzinfo is None:
        z = zone_of(str(v.get("timeZone") or ""))
        if z is None:
            return None  # a time without a zone is ambiguous: dropped
        t = t.replace(tzinfo=z)
    return t.isoformat()


def names(e: dict) -> list[str]:
    out = []
    people = [e.get("organizer")] + list(e.get("attendees") or [])
    for p in people:
        n = ((p or {}).get("emailAddress") or {}).get("name") if isinstance(p, dict) else None
        if isinstance(n, str) and n.strip() and "@" not in n and n.strip() not in out:
            out.append(n.strip())
    return out[:20]


def convert(graph: dict, zone: str, now: str | None = None) -> dict:
    """Graph calendars and events -> the Calendar reader's answer. Unknown or broken items are left out."""
    if not isinstance(graph, dict) or not isinstance(graph.get("calendars"), list):
        raise Stop("Outlook gave an answer the way in cannot read.")
    cals, events, seen = [], [], set()
    for c in graph["calendars"]:
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not c["id"]:
            continue
        raw_id = c["id"]  # opaque: a long id is hashed, never cut, so two calendars never share one rule
        cid = "outlook:" + (raw_id if len(raw_id) <= 190 else hashlib.sha256(raw_id.encode()).hexdigest())
        if cid in seen:
            continue
        seen.add(cid)
        owner = c["owner"].get("name") if isinstance(c.get("owner"), dict) else ""
        cals.append(
            {
                "id": cid,
                "title": str(c.get("name") or "Calendar"),
                "account": owner if isinstance(owner, str) and owner and "@" not in owner else "Outlook",
                "kind": "exchange",
                "shared": c.get("canShare") is False and c.get("canEdit") is False,
            }
        )
        for e in c.get("events") or []:
            if not isinstance(e, dict) or e.get("isCancelled") is True:
                continue
            all_day = e.get("isAllDay") is True
            start, end = graph_time(e.get("start"), all_day), graph_time(e.get("end"), all_day)
            if start is None or end is None:
                continue
            rs = e.get("responseStatus")
            response = rs.get("response") if isinstance(rs, dict) else ""
            events.append(
                {
                    "cal": cid,
                    "start": start,
                    "end": end,
                    "all_day": all_day,
                    "title": str(e.get("subject") or ""),
                    "people": names(e),
                    "declined": response == "declined",
                    "availability": SHOW_AS.get(str(e.get("showAs") or ""), "busy"),
                }
            )
    answer = {
        "schema": SCHEMA,
        "status": "full",
        "zone": zone,
        "read_at": now or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017 (Python 3.9)
        "calendars": cals,
        "events": events[:MAX_EVENTS],
    }
    if len(events) > MAX_EVENTS:
        answer["error"] = f"More than {MAX_EVENTS} events: the rest were left out."
    return answer


def fetch_command(here: Path) -> list[str]:
    try:
        cfg = json.loads((here / "fetch.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    argv = cfg.get("fetch") if isinstance(cfg, dict) else None
    if not argv or not isinstance(argv, list) or not all(isinstance(a, str) and a for a in argv):
        raise Stop("The Outlook way in is not set up yet: fetch.json needs the command that reads Outlook.")
    # "./x" (program or argument) means a file in this folder; the command itself runs in the data folder
    first = argv[0]
    if "/" in first and not os.path.isabs(first):
        first = str((here / first).resolve())
    return [first, *(str((here / a).resolve()) if a.startswith("./") else a for a in argv[1:])]


def work_dir(here: Path) -> Path:
    """Where the fetch command runs: Personal's data folder for this way in (outside the checked folder)."""
    d = os.environ.get("ORCH_PERSONAL_WAY_DATA")
    if d and Path(d).is_dir():
        return Path(d)
    return Path(tempfile.gettempdir())


def window(values: dict, zone: str) -> tuple[dt.datetime, dt.datetime]:
    try:
        frm = dt.date.fromisoformat(str(values.get("from") or dt.date.today().isoformat()))
        days = int(values.get("days") or 7)
    except (TypeError, ValueError):
        raise Stop("The way in got a day it cannot read.") from None
    if not 1 <= days <= 35:
        raise Stop("Ask for 1 to 35 days.")
    z = zone_of(zone) or ZoneInfo("UTC")
    start = dt.datetime.combine(frm, dt.time.min, z)
    return start, dt.datetime.combine(frm + dt.timedelta(days=days), dt.time.min, z)


def read(values: dict, here: Path) -> dict:
    zone = local_zone()
    start, end = window(values, zone)
    argv = fetch_command(here)
    ask = json.dumps({"start": start.isoformat(), "end": end.isoformat(), "zone": zone})
    try:
        p = subprocess.run(
            argv,
            check=False,
            input=ask,
            capture_output=True,
            text=True,
            timeout=FETCH_TIMEOUT,
            cwd=work_dir(here),  # never this folder: a file written here would stop the way in
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except subprocess.TimeoutExpired:
        raise Stop(f"Outlook did not answer within {FETCH_TIMEOUT} seconds.") from None
    except OSError:
        raise Stop("The command in fetch.json could not be started.") from None
    if p.returncode != 0:
        raise Stop(f"Reading Outlook did not work (the command ended with code {p.returncode}).")
    try:
        graph = json.loads(p.stdout)
    except ValueError:
        raise Stop("Outlook gave an answer the way in cannot read.") from None
    return convert(graph, zone)


def main() -> int:
    here = Path(__file__).resolve().parent
    try:
        msg = json.loads(sys.stdin.read() or "{}")
        values = msg.get("values") if isinstance(msg, dict) else None
        print(json.dumps(read(values if isinstance(values, dict) else {}, here), ensure_ascii=False))
    except Stop as e:
        print(str(e), file=sys.stderr)
        return 1
    except ValueError:
        print("The way in got values it cannot read.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
