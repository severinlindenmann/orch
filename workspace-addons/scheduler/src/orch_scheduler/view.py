"""`orch scheduler view --json`: read-only blocks for the dashboard tab (addon-view.schema.json)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from croniter import croniter

from . import orchcli, service
from .cron import fmt, parse
from .loop import OPEN

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def clean(s: object, n: int = 80) -> str:
    out = "".join(c for c in str(s) if c not in "<>").strip()[:n]
    return out or "-"


def cron_human(expr: str) -> str:
    m, h, dom, mon, dow = expr.split()
    if m.isdigit() and h.isdigit() and dom == mon == "*":
        at = f"{int(h):02d}:{int(m):02d} UTC"
        if dow == "*":
            return f"Every day at {at}"
        if dow.isdigit() and int(dow) % 7 in range(7):
            return f"Every {DAYS[(int(dow) - 1) % 7]} at {at}"
    return f"Repeats {expr} (UTC)"


def _in(delta: timedelta) -> str:
    s = int(delta.total_seconds())
    if s < 60:
        return "now"
    if s < 3600:
        return f"in {s // 60} min"
    if s < 86400:
        return f"in {s // 3600} h"
    return f"in {s // 86400} d"


def _events(tickets: list[dict], now: datetime, horizon: datetime) -> list[tuple[datetime, dict, str]]:
    """Upcoming starts: (when, ticket, what) for time waits and cron repeats, until `horizon`."""
    out: list[tuple[datetime, dict, str]] = []
    for t in tickets:
        if t["status"] not in OPEN:
            continue
        w = t.get("waiting_on") or {}
        until = parse(w.get("until")) if w.get("kind") == "time" else None
        if until and until <= horizon:
            out.append((max(until, now), t, f"Wakes {fmt(until)}"))
        sched = (t.get("ext") or {}).get("scheduler") or {}
        cron = sched.get("cron")
        if sched.get("recurring") is True and isinstance(cron, str) and croniter.is_valid(cron) and len(cron.split()) == 5:
            it = croniter(cron, now)
            for _ in range(20):
                nxt = it.get_next(datetime).astimezone(UTC)
                if nxt > horizon:
                    break
                out.append((nxt, t, cron_human(cron)))
    return sorted(out, key=lambda e: e[0])


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
        items = [{"time": e[0].astimezone().strftime("%H:%M"), "title": clean(e[1]["title"]), "link": e[1]["id"]}
                 for e in events if e[0].astimezone().date() == d][:20]
        days.append({"date": d.isoformat(), "items": items})
    blocks.append({"type": "calendar", "days": days})

    items = [{"title": clean(e[1]["title"]), "subtitle": clean(e[2], 200), "link": e[1]["id"]} for e in events]
    blocks.append({"type": "list", "title": "Next runs", "items": items[:10], "more": max(0, len(items) - 10)})

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
