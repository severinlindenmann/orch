"""Helpers that stopped on the subscription's usage limit (ORCH-179).

When the tool's usage limit is reached, every helper stops at once ("You've hit your 5-hour limit · resets
8:40am"). Before this, the helper watcher took them for idle helpers: it sent reminders that failed on the
limit, orch started them again, they failed again and stayed stopped until a person restarted each one.

Now:
- noticing: the last answer in a live helper's saved conversation is a limit error (tend), or a run ends with
  one (runs.wrap). The ticket is noted here with the reset time (from the tool's own data, else from its
  words, else an hour from now);
- holding: until the reset (plus GRACE) the watcher sends no reminders and starts nobody fresh, and an
  automatic start waits in line (runs_live._held) instead of failing on the limit;
- resuming: after it, the watcher starts each noted ticket again on its earlier conversation (tend).

State: one small file, .orch/run/limit-stop.json. No AI call anywhere; a person's own start is never held.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from orch import runs

GRACE = 2 * 60  # wait this long after the reset time before anything starts again
UNKNOWN_WAIT = 60 * 60  # no reset time known: try again after this long
TAIL_BYTES = 64 * 1024  # only the end of a saved conversation is read
STATE_MAX = 256 * 1024
FILE = "limit-stop.json"

_WORDS = re.compile(r"(hit|reached) your .{0,40}limit|usage limit reached", re.IGNORECASE)
# ORCH-642: newer tool versions save the stop as a `system` notice, not an answer: "Usage limit reached ·
# continuing automatically at 7:10pm · esc to cancel", and, when the login changes before then (Usage switched
# the account), "Automatic continue stopped · your login changed or ended · send a prompt to continue".
# Nothing continues it then.
_SWITCHED = re.compile(r"automatic continue stopped.{0,40}login changed", re.IGNORECASE)
_RESETS = re.compile(
    r"(?:resets|continuing automatically at)\s+"
    r"(?:(?P<mon>[A-Z][a-z]{2,8})\s+(?P<day>\d{1,2}),?\s+(?:at\s+)?)?"
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)?(?:\s*\((?P<tz>[A-Za-z_/+-]+)\))?",
    re.IGNORECASE,
)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def _num(v: object) -> float | None:
    return float(v) if type(v) in (int, float) and 0 < v < 1e11 else None  # type: ignore[arg-type]


def reset_from_words(text: str, now: float | None = None) -> float | None:
    """The reset time in the tool's words ("resets 8:40am (Europe/Zurich)", "resets Nov 20, 9am"), as the next
    such moment after now; None when the words hold none."""
    m = _RESETS.search(text or "")
    if not m:
        return None
    now = time.time() if now is None else now
    tz = None
    if m["tz"]:
        with contextlib.suppress(Exception):
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(m["tz"])
    base = datetime.fromtimestamp(now, tz) if tz else datetime.fromtimestamp(now).astimezone()
    h, mi = int(m["h"]), int(m["m"] or 0)
    if m["ap"]:
        h = h % 12 + (12 if m["ap"].lower() == "pm" else 0)
    if h > 23 or mi > 59:
        return None
    try:
        at = base.replace(hour=h, minute=mi, second=0, microsecond=0)
        if m["mon"]:
            mon = m["mon"][:3].lower()
            if mon not in _MONTHS:
                return None
            at = at.replace(month=_MONTHS.index(mon) + 1, day=int(m["day"]))
            if at.timestamp() < now - 86400:
                at = at.replace(year=at.year + 1)
        elif at.timestamp() <= now - GRACE:
            at += timedelta(days=1)
    except ValueError:
        return None
    return at.timestamp()


def _info(limit: dict | None, text: str, now: float | None) -> dict:
    limit = limit if isinstance(limit, dict) else {}
    until = _num(limit.get("resetsAt")) or reset_from_words(text, now)
    window = limit.get("rateLimitType")
    out: dict = {"until": until, "text": " ".join(str(text or "").split())[:200]}
    if isinstance(window, str) and window:
        out["window"] = window[:32]
    return out


def _text(entry: dict) -> str:
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            return block["text"]
    r = entry.get("result")
    return r if isinstance(r, str) else ""


def _limit_entry(entry: dict, now: float | None) -> dict | None:
    """A saved-conversation or stream line that is a limit error, as {until, text, window?}; else None."""
    params = entry.get("apiErrorParams")
    info = params.get("rate_limit_info") if isinstance(params, dict) else None
    if entry.get("apiError") == "usage_limit_reached" or (
        isinstance(info, dict) and info.get("status") == "rejected" and entry.get("error") == "rate_limit"
    ):
        return _info(info or entry.get("quotaLimits"), _text(entry), now)
    if entry.get("is_error") is True and _WORDS.search(_text(entry)):
        return _info(None, _text(entry), now)
    return None


def _notice(entry: dict) -> str:
    c = entry.get("content")
    return c if entry.get("type") == "system" and isinstance(c, str) else ""


def _typed(entry: dict) -> bool:
    """A prompt that went in (a person's words or orch's notice line), not a tool's result."""
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if entry.get("isMeta") or not content:
        return False
    if isinstance(content, str):
        return True
    return isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "text" for b in content)


def from_entries(entries: Iterable[dict], now: float | None = None) -> dict | None:
    """The limit stop shown by the LAST answer in these lines (a saved conversation, or one run's stream), or
    None when the last answer is a normal one (the helper went on after it). A `rate_limit_event` that was
    rejected gives the reset time when the error line itself carries none. The tool's own notices count too
    (ORCH-642): "Usage limit reached · continuing automatically at 7:10pm", and after it "Automatic continue
    stopped · your login changed": then the hit has switched=True (the account changed; one prompt carries it
    on). A prompt that went in after a notice means it goes on."""
    found, event = None, None
    for e in entries:
        if not isinstance(e, dict):
            continue
        words = _notice(e)
        if words and _SWITCHED.search(words):
            found = {**(found or {"until": None}), "text": " ".join(words.split())[:200], "switched": True}
            continue
        if words and _WORDS.search(words):
            found = {**_info(None, words, now), "notice": True}
            continue
        if e.get("type") == "user" and found is not None and found.get("notice") and _typed(e):
            found = None  # a prompt went in after the tool's notice: it goes on
            continue
        if e.get("type") == "rate_limit_event":
            info = e.get("rate_limit_info")
            if isinstance(info, dict) and info.get("status") == "rejected":
                event = info
            continue
        if e.get("type") not in ("assistant", "result"):
            continue
        found = _limit_entry(e, now)
        if found is not None and found.get("until") is None and event is not None:
            found = {
                **found,
                **{k: v for k, v in _info(event, "", now).items() if k != "text" and v is not None},
            }
        if found is None and e.get("type") == "result" and e.get("is_error") is not True:
            event = None  # the run went on and finished normally
    if found is not None and found.get("until") is None and event is not None:
        found = {**found, **{k: v for k, v in _info(event, "", now).items() if k != "text" and v is not None}}
    if found is not None:
        found.pop("notice", None)
    return found


def _lines(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            with contextlib.suppress(ValueError):
                out.append(json.loads(line))
    return out


def from_output(out: str, why: str | None = None, now: float | None = None) -> dict | None:
    """A one-step run's output (stream lines) or its failure words: the limit stop, or None."""
    found = from_entries(_lines(out or ""), now)
    if found is None and why and _WORDS.search(why):
        found = _info(None, why, now)
    return found


def from_transcript(path: Path | None, now: float | None = None) -> dict | None:
    """The end of a saved conversation: the limit stop its last answer shows, or None."""
    if path is None:
        return None
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    return from_entries(_lines(tail), now)


# ---------------------------------------------------------------- the workspace's record


def _path(root: Path) -> Path:
    return runs.run_dir(root) / FILE


def read(root: Path) -> dict:
    try:
        p = _path(root)
        if p.stat().st_size > STATE_MAX:
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("tickets"), dict):
        return {}
    return data


def _write(root: Path, data: dict) -> None:
    with contextlib.suppress(OSError):
        if not data.get("tickets"):
            _path(root).unlink(missing_ok=True)
            return
        runs.run_dir(root).mkdir(parents=True, exist_ok=True)
        runs._atomic(_path(root), json.dumps(data, indent=1) + "\n")


@contextlib.contextmanager
def _locked(root: Path):
    """One writer at a time: helpers stopped by the limit end within the same second (17 Nov: six in one)."""
    from orch import relay

    lock = relay.locked(root, wait=5.0, name="run/limit-stop.lock")
    try:
        lock.__enter__()
    except relay.Refused:  # busy for 5 s: write anyway rather than lose the note
        lock = None
    try:
        yield
    finally:
        if lock is not None:
            lock.__exit__(None, None, None)


def until(data: dict) -> float | None:
    """When starting again makes sense (the reset plus GRACE), or None when nothing is noted."""
    if not data.get("tickets"):
        return None
    u = _num(data.get("until"))
    if u is None:
        u = (_num(data.get("noted_at")) or time.time()) + UNKNOWN_WAIT - GRACE
    return u + GRACE


def note(root: Path, tid: str, info: dict, now: float | None = None) -> bool:
    """Note a ticket as stopped on the limit. True when it was not noted yet (say it once in the history)."""
    now = time.time() if now is None else now
    with _locked(root):
        return _note(root, tid, info, now)


def _note(root: Path, tid: str, info: dict, now: float) -> bool:
    data = read(root)
    ticks = data.get("tickets") or {}
    fresh = tid not in ticks
    u = _num(info.get("until"))
    old = _num(data.get("until"))
    if not ticks or old is None or (u is not None and u > old):
        data["until"] = u
        if info.get("window"):
            data["window"] = info["window"]
        if info.get("text"):
            data["text"] = info["text"]
    if not ticks:
        data["noted_at"] = now
    ticks.setdefault(tid, {"at": now})
    data["tickets"] = ticks
    _write(root, data)
    return fresh


def active(root: Path, now: float | None = None) -> dict | None:
    """The limit stop still in force: {"until": <when starting again makes sense>, ...}, else None."""
    now = time.time() if now is None else now
    data = read(root)
    u = until(data)
    return {**data, "resume_at": u} if u is not None and now < u else None


def due(root: Path, now: float | None = None) -> list[str]:
    """Noted tickets whose limit is over: start them again now."""
    now = time.time() if now is None else now
    data = read(root)
    u = until(data)
    return list(data["tickets"]) if u is not None and now >= u else []


def forget(root: Path, tids: Iterable[str]) -> None:
    with _locked(root):
        data = read(root)
        ticks = data.get("tickets") or {}
        for tid in tids:
            ticks.pop(tid, None)
        data["tickets"] = ticks
        _write(root, data)


def lift(root: Path, now: float | None = None) -> None:
    """The account changed (ORCH-642: Usage switched it): the limit no longer holds anyone back. Noted tickets
    are due at once, and automatic starts no longer wait for the reset."""
    now = time.time() if now is None else now
    with _locked(root):
        data = read(root)
        if data.get("tickets"):
            data["until"] = now - GRACE
            _write(root, data)


def switched_text() -> str:
    return (
        "The account was switched while you waited at the usage limit. Carry on with the open tasks where "
        "you stopped (orch ticket show shows them)."
    )


def clock(ts: object) -> str:
    """The reset time a person reads: 08:40, or a date when it is not today."""
    ts = _num(ts)
    if ts is None:
        return "in about an hour"
    lt, today = time.localtime(ts), time.localtime()
    if (lt.tm_year, lt.tm_yday) == (today.tm_year, today.tm_yday):
        return time.strftime("%H:%M", lt)
    return time.strftime("%d %b %H:%M", lt)


def held_words(root: Path) -> str | None:
    """Why an automatic start waits in line now, or None (runs_live._held)."""
    a = active(root)
    return f"the usage limit is reached until {clock(a.get('until'))}" if a else None


def stopped_text(info: dict) -> str:
    return (
        f"Stopped on the usage limit; it continues by itself after the reset at {clock(info.get('until'))}."
    )


def resume_text(key: str, data: dict) -> str:
    return (
        f"The usage limit reset at {clock(data.get('until'))}. You stopped on it. Go on with {key} where "
        "you stopped (orch ticket show shows the open tasks)."
    )
