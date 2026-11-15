"""`orch diag query`: read the debug log and the activity record, paginated, never everything at once.

Read-only. Oldest first inside the window. Structure only: a record event is shown as ids, kind and
time, never its
text (the text is the content part of a report).
"""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orch import diag, diag_collect
from orch.errors import Refused

DEFAULT_LIMIT = 50
MAX_LIMIT = 500
SCAN_CAP = 50_000  # events looked at per query: a wider window must be narrowed, and the answer says so
_DUR = re.compile(r"^(\d+)([smhd])$")
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_REC_KEYS = ("at", "run", "seq", "kind", "ticket", "id", "via", "source")


def duration(text: str, what: str = "duration") -> float:
    m = _DUR.fullmatch(str(text or ""))
    if not m:
        raise Refused(f"--{what} must be like 30s, 5m, 2h or 7d.")
    return int(m.group(1)) * _UNIT[m.group(2)]


def parse_time(text: str, what: str = "time") -> float:
    try:
        return (
            datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=UTC).timestamp()
            if "T" in text
            else _ts(text)
        )
    except ValueError:
        raise Refused(f"--{what} must be like 09:58 (UTC) or 2026-11-14T09:58:00Z.") from None


def _ts(text: str) -> float:
    h, m = text.split(":")
    now = datetime.now(UTC)
    at = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    if at > now:
        at -= timedelta(days=1)
    return at.timestamp()


def _epoch(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def window(since=None, around=None, span=None, now=None) -> tuple[float, float]:
    now = time.time() if now is None else now
    if around:
        c = parse_time(around, "around")
        w = duration(span or "2m", "window")
        return c - w, c + w
    if since:
        try:
            return now - duration(since, "since"), now
        except Refused:
            return parse_time(since, "since"), now
    return now - 2 * 3600, now


def _rec_item(e: dict) -> dict:
    return {
        "source": "record",
        "ev": "record." + str(e.get("kind")),
        "lvl": "info",
        **{k: e.get(k) for k in _REC_KEYS},
    }


def _diag_item(e: dict) -> dict:
    return {
        "source": "diag",
        **{
            k: e.get(k)
            for k in ("at", "lvl", "ev", "src", "seq", "mono_ms", "ticket", "run", "pid", "code", "kv", "err")
        },
    }


def _fhash(filters: dict) -> str:
    return hashlib.sha256(json.dumps(filters, sort_keys=True).encode()).hexdigest()[:12]


def _encode(offset: int, fh: str) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset, "f": fh}).encode()).decode().rstrip("=")


def _decode(token: str, fh: str) -> int:
    try:
        raw = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        o, f = int(raw["o"]), raw["f"]
    except (ValueError, KeyError, TypeError):
        raise Refused("That page token is not valid. Start again without --page.") from None
    if f != fh or o < 0:
        raise Refused("That page token belongs to another question. Start again without --page.")
    return o


def query(
    root: Path,
    *,
    ticket=None,
    run=None,
    ev=None,
    lvl=None,
    around=None,
    span=None,
    since=None,
    limit=None,
    page=None,
    now=None,
) -> dict:
    lo, hi = window(since, around, span, now)
    n = DEFAULT_LIMIT if limit in (None, "") else int(limit)
    if not 1 <= n <= MAX_LIMIT:
        raise Refused(f"--limit must be between 1 and {MAX_LIMIT}.")
    if lvl is not None and lvl not in diag.LEVELS:
        raise Refused("--lvl must be one of: " + ", ".join(diag.LEVELS) + ".")
    floor = diag.LEVELS.index(lvl) if lvl else 0
    filters = {"t": ticket, "r": run, "e": ev, "l": lvl, "lo": int(lo), "hi": int(hi)}
    fh = _fhash(filters)
    offset = _decode(page, fh) if page else 0
    items: list[dict] = []
    scanned = 0
    capped = False
    for e in diag_collect.recent_events(root, lo, hi):
        scanned += 1
        if scanned > SCAN_CAP:
            capped = True
            break
        if ticket and e.get("ticket") != ticket or run and e.get("run") != run:
            continue
        if ev and not fnmatch.fnmatchcase(str(e.get("ev")), ev):
            continue
        if e.get("lvl") in diag.LEVELS and diag.LEVELS.index(e["lvl"]) < floor:
            continue
        items.append(_diag_item(e))
    unavailable: list[str] = []
    if (ticket or run) and not (lvl and floor > 0):
        rec = diag_collect.collect(root, "activity", {"ticket": ticket, "run": run})
        unavailable = rec["gaps"]
        for e in rec["data"].get("events", []):
            try:
                at = _epoch(e["at"])
            except (KeyError, ValueError):
                continue
            if lo <= at <= hi and (not ev or fnmatch.fnmatchcase("record." + str(e.get("kind")), ev)):
                items.append(_rec_item(e))
    items.sort(key=lambda i: (i.get("at") or "", i["source"], i.get("seq") or 0))
    out = items[offset : offset + n]
    more = offset + n < len(items)
    return {
        "window": {
            "from": datetime.fromtimestamp(lo, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": datetime.fromtimestamp(hi, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "total": len(items),
        "items": out,
        "next": _encode(offset + n, fh) if more else None,
        "unavailable": unavailable
        + (["too many events in the window, narrow it with --since, --ev or --around"] if capped else []),
    }
