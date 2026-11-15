"""Measured active time of an order (#681): from core's activity record (`orch record query --ticket T --json`), never
from the agent's word. Per run, the gaps between consecutive events are added up, each at most IDLE_CAP: a live session
waiting at its prompt (for the person, or for nothing) writes no events, so waiting never counts."""

from datetime import datetime
from itertools import pairwise

from . import orchcli
from .store import Refused

IDLE_CAP = 300  # seconds: a longer quiet gap counts as 5 minutes of work at most
PAGES = 20  # 20 x 500 events per ticket at most per reading (older events beyond that are not counted)


def _when(value):
    try:
        at = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return at if at.tzinfo is not None else None  # core writes UTC with Z; anything else is not counted


def _events(root, tid):
    after, out = None, []
    for _ in range(PAGES):
        page = orchcli.call(
            root, "record", "query", "--ticket", tid, "--limit", "500", *(["--after", after] if after else [])
        )
        items = page.get("items") if isinstance(page, dict) else None
        if not isinstance(items, list):
            raise Refused("The activity record could not be read.", "not_available")
        out.extend(i for i in items if isinstance(i, dict))
        after = page.get("next")
        if not isinstance(after, str) or not after:
            break
    return out


def active_minutes(root, ticket_ids):
    """Whole minutes of measured agent work on these tickets (rounded up), or None when the record can't be read."""
    seconds = 0.0
    try:
        for tid in ticket_ids:
            runs = {}
            for e in _events(root, tid):
                at = _when(e.get("at"))
                if at is not None and isinstance(e.get("run"), str):
                    runs.setdefault(e["run"], []).append(at)
            for times in runs.values():
                times.sort()
                seconds += sum(min((b - a).total_seconds(), IDLE_CAP) for a, b in pairwise(times))
    except Refused:
        return None
    return int(-(-seconds // 60))
