"""`orch pull-requests view`: the Pull requests page (orch.addon-view/1). Read only, from prs.json: no GitHub call."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

from . import poll, service, settings, store

REPOS_SHOWN = 8
CHECKS_TEXT = {"passed": "Passed", "running": "Running", "failed": "Failed", "none": "No checks"}
MERGE_TEXT = {
    "ready": "Ready to merge",
    "blocked": "Blocked",
    "behind": "Behind its base",
    "conflict": "Has a conflict",
    "draft": "Draft",
    "unknown": "Not known yet",
    "merged": "Merged",
    "closed": "Closed",
}
_ORDER = {"checks failed": 0, "conflict": 1, "checks running": 2, "ready to merge": 3}


def checks_text(c: dict) -> str:
    word = c.get("word") or "none"
    if word == "failed" and c.get("failed_names"):
        return ("Failed: " + ", ".join(c["failed_names"][:2]))[:200]
    if word == "running" and c.get("running"):
        return f"Running ({c['running']} left)"
    if word == "passed" and c.get("passed"):
        return f"Passed ({c['passed']})"
    return CHECKS_TEXT.get(word, "No checks")


def _row(r: dict, tk: dict | None) -> dict:
    sub = f"{r['head']} into {r['base']}" if r.get("head") and r.get("base") else r.get("repo", "")
    if r.get("author"):
        sub += f" · {r['author']}"
    return {
        "cells": {
            "pr": f"#{r['number']} {r.get('title') or ''}".strip()[:200],
            "ticket": tk["key"] if tk else None,
            "checks": checks_text(r.get("checks") or {}),
            "merge": MERGE_TEXT.get(r.get("merge"), "Not known yet"),
        },
        "link": tk["id"] if tk else r["url"],
        "subtitle": sub[:200] or r["url"],
    }


COLUMNS = [
    {"key": "pr", "label": "Pull request", "type": "text"},
    {"key": "ticket", "label": "Ticket", "type": "text"},
    {"key": "checks", "label": "Checks", "type": "text"},
    {"key": "merge", "label": "Merge", "type": "text"},
]


QUEUE_COLUMNS = [
    {"key": "pr", "label": "Pull request", "type": "text"},
    {"key": "ticket", "label": "Ticket", "type": "text"},
    {"key": "place", "label": "Place", "type": "text"},
    {"key": "waited", "label": "Waited", "type": "duration"},
    {"key": "why", "label": "Why", "type": "text"},
]


def _since(stamp, now: float) -> int | None:
    try:
        t = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None
    secs = max(0, int(now - t))
    return secs if secs < 60 else secs // 60 * 60  # whole minutes: the seconds only add noise


def _nth(n: int) -> str:
    end = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{end} in line"


PR_LINK = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/(\d+)")
DEFAULT_WHY = ("waiting in line", "in the group being checked")


def _plain_why(why: str) -> str:
    """The runner's reason as one line for the page; its prefix 'waits again:' adds nothing to a waiting row."""
    why = " ".join(str(why or "").replace("<", "").replace(">", "").split())
    why = PR_LINK.sub(lambda m: f"#{m[1]}", why)  # a pull request by its number, never a raw address
    if why.lower() in DEFAULT_WHY:  # the default words: the place says it
        return ""
    why = why.removeprefix("waits again: ").removeprefix("Waits again: ")
    return why[:1].upper() + why[1:] if why else ""


def queue_block(
    root, tickets: list[dict], alive: bool, now: float | None = None, titles: dict | None = None
) -> dict | None:
    """The merge queue's line, in order: what is being checked first, then the waiting ones with their place,
    how long each has waited since it was added and why. None when nothing waits."""
    now = time.time() if now is None else now
    try:
        rows = store.read(root)
    except Exception:  # noqa: BLE001 - a damaged queue file must not take the page down
        return None
    running = [r for r in rows if r.get("state") == store.RUNNING]
    waiting = [r for r in rows if r.get("state") == store.WAITING]
    if not running and not waiting:
        return None
    ids = {t["id"]: t["id"] for t in tickets} | {str(t["key"]): t["id"] for t in tickets if t.get("key")}
    keys = {t["id"]: t.get("key") or t["id"] for t in tickets}
    size = settings.max_group(root)
    out, place = [], 0
    for r in running + waiting:
        why = _plain_why(r.get("why") or "")
        if r.get("state") == store.RUNNING:
            where = "Being checked"
            if not why or why.startswith("In the group #"):  # the group itself: say who it runs with
                others = sum(1 for x in running if x is not r and x.get("group") == r.get("group"))
                why = (
                    f"Checked together with {others} other{'s' if others != 1 else ''}"
                    if others
                    else ("Checked alone on top of " + str(r.get("base") or "its base branch"))
                )
        else:
            place += 1
            where = _nth(place)
            later = float(r.get("not_before") or 0)
            if not alive:
                why = "The merge queue is not running; it starts again with the next pull request added"
            elif later > now:
                mins = max(1, round((later - now) / 60))
                why = f"Paused for {mins} min: {why}" if why else f"Paused for {mins} min"
            elif not why:
                why = "Waits for the group being checked" if running else "Goes into the next group"
        tid = r.get("ticket")
        title = r.get("title") or (titles or {}).get(r.get("url")) or ""
        out.append(
            {
                "cells": {
                    "pr": f"#{r.get('number')} {title}".strip()[:200],
                    "ticket": keys.get(ids.get(tid, ""), tid) if tid else None,
                    "place": where,
                    "waited": _since(r.get("added"), now),
                    "why": why[:200],
                },
                "link": ids.get(tid or "") or r["url"],
                "subtitle": str(r.get("repo") or "")[:200] or r["url"],
            }
        )
    block = {
        "type": "table",
        "title": "Merge queue",
        "meta": f"{len(waiting)} waiting · {len(running)} being checked · groups of up to {size}",
        "columns": QUEUE_COLUMNS,
        "rows": out[:100],
    }
    if len(out) > 100:
        block["more"] = len(out) - 100
    return block


def build(
    root, running: bool | None = None, queue_alive: bool | None = None, now: float | None = None
) -> dict:
    data = poll.load(root)
    if running is None:
        running = service.running_pid(root) is not None
    ts = poll.tickets(root)
    owner = poll.ticket_of(ts)
    repos = sorted(data["repos"].items(), key=lambda kv: kv[0].lower())
    open_rows: dict[str, list[dict]] = {}
    for repo, rec in repos:
        nums = set(rec.get("open") or [])
        rows = [r for r in data["prs"].values() if r.get("repo") == repo and r.get("number") in nums]
        rows = [r for r in rows if r.get("state") == "OPEN"]
        rows.sort(key=lambda r: (_ORDER.get(r.get("status"), 9), -(r.get("number") or 0)))
        open_rows[repo] = rows
    every = [r for rows in open_rows.values() for r in rows]
    failed = sum(1 for r in every if r.get("status") == "checks failed")
    ready = sum(1 for r in every if r.get("status") == "ready to merge")
    blocks: list[dict] = [
        {"type": "stat", "label": "Open", "value": len(every)},
        {"type": "stat", "label": "Checks failed", "value": failed, "tone": "bad" if failed else "neutral"},
        {"type": "stat", "label": "Ready to merge", "value": ready, "tone": "good" if ready else "neutral"},
    ]
    if queue_alive is None:
        from .cli import runner_alive

        queue_alive = runner_alive(root)
    titles = {r.get("url"): r.get("title") for r in data["prs"].values() if r.get("title")}
    queue = queue_block(root, ts, queue_alive, now, titles)
    if queue is not None:
        blocks.append(queue)
    shown = 0
    for repo, rec in repos:
        if shown >= REPOS_SHOWN:
            break
        rows = open_rows.get(repo) or []
        if rec.get("error") and not rows:
            continue
        shown += 1
        block = {
            "type": "table",
            "title": repo[:60],
            "meta": f"{len(rows)} open" if rows else "None open",
            "columns": COLUMNS,
            "rows": [_row(r, owner.get(r["url"])) for r in rows[:100]],
        }
        if len(rows) > 100:
            block["more"] = len(rows) - 100
        blocks.append(block)
    if not shown:
        blocks.append(
            {
                "type": "list",
                "title": "Pull requests",
                "items": [],
                "empty": {
                    "title": "No pull requests yet",
                    "text": "Link a pull request to a ticket and it shows up here with its checks.",
                },
            }
        )
    view: dict = {"schema": "orch.addon-view/1", "generated_at": data.get("polled_at") or poll.now()}
    view["blocks"] = blocks
    errors = sorted({rec["error"] for _, rec in repos if rec.get("error")})
    if not running:
        view["notice"] = "Pull requests are not being read right now, so what you see may be old."
        view["notice_tone"] = "warn"
        view["button"] = {"label": "Start reading", "action": {"op": "addon.start"}}
    elif errors:
        view["notice"] = errors[0]
        view["notice_tone"] = "bad"
    return view
