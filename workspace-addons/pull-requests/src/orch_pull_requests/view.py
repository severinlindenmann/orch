"""`orch pull-requests view`: the Pull requests page (orch.addon-view/1). Read only, from prs.json: no GitHub call."""

from __future__ import annotations

from . import poll, service

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


def build(root, running: bool | None = None) -> dict:
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
