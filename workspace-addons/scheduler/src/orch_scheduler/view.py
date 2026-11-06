"""`orch scheduler view --json`: read-only blocks for the dashboard tab (Schedule first, then Listen) (addon-view.schema.json)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from itertools import pairwise
from pathlib import Path

from croniter import croniter

from . import listen, needs, orchcli, service
from .cron import fmt, next_after, parse
from .loop import OPEN
from .plain import zone

DAYS = ("Sundays", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays")  # cron 0 = Sunday
_NAMES = {n: i for i, n in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}
HOUR = 3600
SCAN = 7 * 1440 + 1  # at most one run per minute for a week


def clean(s: object, n: int = 80) -> str:
    out = "".join(c for c in str(s) if c not in "<>").strip()[:n]
    return out or "-"


def _dows(field: str) -> set[int] | None:
    out: set[int] = set()
    for part in field.lower().split(","):
        lo, _, hi = part.partition("-")
        try:
            a = _NAMES[lo] if lo in _NAMES else int(lo)
            z = (_NAMES[hi] if hi in _NAMES else int(hi)) if hi else a
        except ValueError:
            return None
        if not (0 <= a <= 7 and 0 <= z <= 7 and a <= z):
            return None
        out |= {d % 7 for d in range(a, z + 1)}
    return out


def _days_words(days: set[int]) -> str:
    if days == {1, 2, 3, 4, 5}:
        return "Weekdays"
    if days == {0, 6}:
        return "Weekends"
    names = [DAYS[d] for d in sorted(days, key=lambda d: (d - 1) % 7)]  # Monday first
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def cron_human(expr: str, tz=None) -> str:
    """Plain words for a 5-field cron read in `tz` (UTC when None, then said so): "Every 5 minutes", "Mondays at 08:00"."""
    try:
        m, h, dom, mon, dow = expr.split()
    except ValueError:
        return f"On a custom plan ({expr})"
    if dom == mon == "*" and dow == "*" and h == "*":
        if m == "*":
            return "Every minute"
        if m.startswith("*/") and m[2:].isdigit():
            return f"Every {int(m[2:])} minutes"
        if m.isdigit():
            return "Every hour" if int(m) == 0 else f"Every hour at {int(m)} past"
    if dom == mon == dow == "*" and m.isdigit() and h.startswith("*/") and h[2:].isdigit():
        return f"Every {int(h[2:])} hours"
    if m.isdigit() and h.isdigit() and mon == "*":
        at = f"{int(h) % 24:02d}:{int(m) % 60:02d}" + ("" if tz else " UTC")
        if dom == "*" and dow == "*":
            return f"Every day at {at}"
        if dom == "*":
            days = _dows(dow)
            if days:
                return f"{_days_words(days)} at {at}"
        if dow == "*" and dom.isdigit():
            return f"Every month on day {int(dom)} at {at}"
    return f"On a custom plan ({expr}{'' if tz else ', UTC'})"


def _every(gap: int) -> str:
    return "Every minute" if gap <= 60 else f"Every {gap // 60} min"


def _in(delta: timedelta) -> str:
    s = int(delta.total_seconds())
    if s < 60:
        return "now"
    if s < 3600:
        return f"in {s // 60} min"
    if s < 86400:
        return f"in {s // 3600} h"
    return f"in {s // 86400} d"


def _tz(t: dict):
    return zone(((t.get("ext") or {}).get("scheduler") or {}).get("tz"))


def _repeats(t: dict) -> str | None:
    sched = (t.get("ext") or {}).get("scheduler") or {}
    cron = sched.get("cron")
    if sched.get("recurring") is True and isinstance(cron, str) and len(cron.split()) == 5 and croniter.is_valid(cron):
        return cron
    return None


def _times(cron: str, start: datetime, end: datetime, tz=None) -> list[datetime]:
    """Runs of a cron in [start, end), at most SCAN."""
    out: list[datetime] = []
    it = croniter(cron, (start - timedelta(seconds=1)).astimezone(tz or UTC))
    while len(out) < SCAN:
        nxt = it.get_next(datetime).astimezone(UTC)
        if nxt >= end:
            break
        out.append(nxt)
    return out


def _events(tickets: list[dict], now: datetime, horizon: datetime) -> list[tuple[datetime, dict, str]]:
    """The next start of each ticket (time wait or cron repeat) until `horizon`, soonest first."""
    out: list[tuple[datetime, dict, str]] = []
    for t in tickets:
        if t["status"] not in OPEN:
            continue
        w = t.get("waiting_on") or {}
        until = parse(w.get("until")) if w.get("kind") == "time" else None
        if until and until <= horizon:
            out.append((max(until, now), t, f"Wakes {until.astimezone().strftime('%a %d %b, %H:%M')}"))
        cron = _repeats(t)
        nxt = next_after(cron, now, _tz(t)) if cron else None
        if nxt and nxt <= horizon:
            out.append((nxt, t, f"{cron_human(cron, _tz(t))} · next {nxt.astimezone().strftime('%a %H:%M')}"))
    return sorted(out, key=lambda e: e[0])


def _day_items(tickets: list[dict], now: datetime, day_start: datetime, day_end: datetime, today: bool) -> list[dict]:
    """Calendar items for one local day. A repeat more often than hourly is ONE item ("Every 5 min",
    "next 15:05 · 288 runs/day"); hourly or less shows each time."""
    items: list[tuple[datetime, dict]] = []
    for t in tickets:
        if t["status"] not in OPEN:
            continue
        w = t.get("waiting_on") or {}
        until = parse(w.get("until")) if w.get("kind") == "time" else None
        if until:
            at = max(until, now)
            if day_start <= at < day_end:
                items.append((at, {"time": at.astimezone().strftime("%H:%M"), "title": clean(t["title"]), "link": t["id"]}))
        cron = _repeats(t)
        if not cron:
            continue
        whole = _times(cron, day_start, day_end, _tz(t))
        left = [x for x in whole if x >= now]
        if not left:
            continue
        gaps = [(b - a).total_seconds() for a, b in pairwise(whole)]
        if gaps and min(gaps) < HOUR:
            first = left[0].astimezone().strftime("%H:%M")
            lead = f"next {first}" if today else (f"from {first}" if first != "00:00" else "")
            note = " · ".join(x for x in (lead, f"{len(whole)} runs/day") if x)
            items.append((left[0], {"time": first, "every": _every(int(min(gaps))), "title": clean(t["title"]),
                                    "note": note, "link": t["id"]}))
        else:
            items += [(x, {"time": x.astimezone().strftime("%H:%M"), "title": clean(t["title"]), "link": t["id"]})
                      for x in left]
    return [i for _, i in sorted(items, key=lambda e: e[0])][:20]


_KINDS = {"text": "Message", "file": "File", "delegate": "Task", "start": "Start request", "webhook": "Webhook",
          "answer": "Answer", "question": "Question"}


def _arrival(a: dict) -> dict:
    kind = _KINDS.get(a.get("type"), "Message")
    when = (parse(a.get("at")) or datetime.now(UTC)).astimezone().strftime("%a %H:%M")
    if a.get("type") in ("start", "delegate"):
        chip = {"label": "Started a run", "tone": "good"} if a.get("allowed") else {"label": "Waiting for you", "tone": "warn"}
    elif a.get("type") == "answer" and a.get("applied"):
        chip = {"label": "Answered", "tone": "good"}
    else:
        chip = {"label": "Seen" if a.get("seen") else "New"}
    return {"title": kind, "subtitle": when, "chips": [chip]}


def _runs(root: Path) -> list[dict]:
    out = []
    try:
        lines = (root / ".orch" / "addons" / "scheduler" / "runs.jsonl").read_text().splitlines()
    except OSError:
        return out
    for line in lines[-200:]:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and parse(r.get("at")) and isinstance(r.get("exit"), int):
            out.append(r)
    return out


def build(root: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    tickets = orchcli.tickets(root)
    by_id = {t["id"]: t for t in tickets}
    title = lambda tid: clean(by_id.get(tid, {}).get("title", tid))
    events = _events(tickets, now, now + timedelta(days=7))
    runs = _runs(root)
    pid = service.running_pid(root, clean=False)
    blocks: list[dict] = []

    nxt = events[0][0] if events else None
    blocks.append({"type": "stat", "label": "Next run", "value": _in(nxt - now) if nxt else "none planned"})
    today = now.strftime("%Y-%m-%d")
    blocks.append({"type": "stat", "label": "Runs today", "value": sum(r["at"].startswith(today) for r in runs)})
    if runs and runs[-1]["exit"] != 0:
        blocks.append({"type": "stat", "label": "Last run failed", "value": f"exit {runs[-1]['exit']}", "tone": "bad"})

    local = now.astimezone()
    days = []
    for i in range(7):
        d = (local + timedelta(days=i)).date()
        start = datetime.combine(d, time.min, tzinfo=local.tzinfo).astimezone(UTC)
        end = datetime.combine(d + timedelta(days=1), time.min, tzinfo=local.tzinfo).astimezone(UTC)
        days.append({"date": d.isoformat(), "items": _day_items(tickets, now, start, end, i == 0)})
    blocks.append({"type": "calendar", "days": days})

    items = [{"title": clean(e[1]["title"]), "subtitle": clean(e[2], 200), "link": e[1]["id"]} for e in events]
    blocks.append({"type": "list", "title": "Next runs", "items": items[:10], "more": max(0, len(items) - 10)})
    reps = sorted(((next_after(c, now, _tz(t)), t, c) for t in tickets if t["status"] in OPEN and (c := _repeats(t))),
                  key=lambda e: e[0] or now)
    if reps:  # UX-06: one row per repeat, soonest first; a monthly job stays visible
        rep = [{"title": clean(t["title"]), "link": t["id"],
                "subtitle": f"{cron_human(c, _tz(t))} · next {_in(n - now) if n else 'never'}"} for n, t, c in reps]
        blocks.append({"type": "list", "title": "Repeats", "items": rep[:20], "more": max(0, len(rep) - 20)})

    ls = listen.read(root) if pid else {}
    blocks.append({"type": "stat", "label": "Listening", "value": "yes" if ls.get("listening") else "no",
                   "tone": "good" if ls.get("listening") else "warn"})
    arrived = [_arrival(a) for a in reversed(ls.get("recent") or []) if isinstance(a, dict)]
    blocks.append({"type": "list", "title": "What arrived", "items": arrived[:10],
                   "more": max(0, len(arrived) - 10)})
    warn = needs.rows(root, now)
    if warn:
        blocks.append({"type": "list", "title": "Needs a look", "items": [
            {"title": clean(r["title"]), "subtitle": clean(r["text"], 200), "tone": r["tone"], "link": r["ticket"]}
            for r in warn[:10]]})

    rows = [{"cells": {"ticket": title(r["ticket"]), "state": "good" if r["exit"] == 0 else "bad",
                       "took": r.get("took", 0), "at": r["at"], "exit": r["exit"]},
             **({"link": r["ticket"]} if r["ticket"] in by_id else {})} for r in reversed(runs[-20:])]
    blocks.append({"type": "table", "title": "Recent runs", "columns": [
        {"key": "ticket", "label": "Ticket", "type": "text"}, {"key": "state", "label": "State", "type": "tone"},
        {"key": "exit", "label": "Exit", "type": "number"}, {"key": "took", "label": "Took", "type": "duration"},
        {"key": "at", "label": "When", "type": "date"}], "rows": rows})

    view = {"schema": "orch.addon-view/1", "generated_at": fmt(now), "blocks": blocks}
    if pid:
        view.update(notice="Running. Checks every minute.", notice_tone="good")
    else:
        view.update(notice="The scheduler is stopped: nothing starts by itself.", notice_tone="warn")
    return view
