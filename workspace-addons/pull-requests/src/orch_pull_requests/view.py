"""`orch pull-requests view`: the Pull requests page (orch.addon-view/1). Read only, from prs.json: no GitHub call."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

from . import poll, service, settings, store

REPOS_SHOWN = 8  # kept for older callers; the page shows one table of every open pull request
MOST_ROWS = 100
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
PR_LINK = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/(\d+)")
DEFAULT_WHY = ("waiting in line", "in the group being checked")
# order on the page: what needs someone first, then the merge queue in its order, then the rest
NEEDS, CHECKING, IN_LINE, OTHER, READY, DRAFT = range(6)

COLUMNS = [
    {"key": "pr", "label": "Pull request", "type": "text"},
    {"key": "ticket", "label": "Ticket", "type": "text"},
    {"key": "state", "label": "State", "type": "text"},
    {"key": "in_line", "label": "In line for", "type": "duration"},
]


def checks_text(c: dict) -> str:
    word = c.get("word") or "none"
    if word == "failed" and c.get("failed_names"):
        return ("Failed: " + ", ".join(c["failed_names"][:2]))[:200]
    if word == "running" and c.get("running"):
        return f"Running ({c['running']} left)"
    if word == "passed" and c.get("passed"):
        return f"Passed ({c['passed']})"
    return CHECKS_TEXT.get(word, "No checks")


def _clean(text: str) -> str:
    """One line for the page: no angle brackets, a pull request by its number, never a raw address."""
    text = " ".join(str(text or "").replace("<", "").replace(">", "").split())
    return PR_LINK.sub(lambda m: f"#{m[1]}", text)


def _cut(text: str, limit: int) -> str:
    """The text up to `limit` characters, cut at a whole word and ended with '…' (never in the middle of a word)."""
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    if text[limit - 1] != " " and " " in head:
        head = head.rsplit(" ", 1)[0]
    return head.rstrip(" ;,:(-") + "…"


def _since(stamp, now: float) -> int | None:
    try:
        t = datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None
    secs = max(0, int(now - t))
    return secs if secs < 60 else secs // 60 * 60  # whole minutes: the seconds only add noise


def minutes(secs: int | None) -> str:
    """A wait in words, as the dashboard writes a duration cell: '12 min', '2 h 10 min'."""
    if secs is None:
        return ""
    if secs < 60:
        return "less than a minute"
    m = secs // 60
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60} min"


def _nth(n: int) -> str:
    end = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{end} in line"


def _plain_why(why: str) -> str:
    """The queue's own reason, without its default words (the place says those) and its 'waits again:'."""
    why = _clean(why)
    if why.lower() in DEFAULT_WHY or why.lower().startswith("in the group #"):
        return ""
    why = why.removeprefix("waits again: ").removeprefix("Waits again: ")
    return why[:1].upper() + why[1:] if why else ""


def repair_note(tk: dict | None, runs: dict[str, str], status: dict[str, str]) -> str:
    """Who is fixing a red pull request: the helper on its ticket, a helper place it waits for, or nobody."""
    if not tk:
        return "No ticket is linked, so no helper fixes it."
    if tk["id"] in runs:
        return f"Being repaired by {_clean(runs[tk['id']])[:40] or 'a helper'}."
    if status.get(tk["id"]) in ("open", "ready", "active"):
        return "Waits for a helper place."
    return "No helper is on it. Open the ticket to fix it."


def _runs(root) -> dict[str, str]:
    """{ticket id: helper name} of every live helper run (empty when orch cannot list them)."""
    got = poll.orch(root, "run", "list")
    rows = got.get("runs") if isinstance(got, dict) else None
    return {
        r["ticket"]: str(r.get("agent") or "")
        for r in rows or []
        if isinstance(r, dict) and isinstance(r.get("ticket"), str) and r.get("state") == "alive"
    }


def _pr_state(r: dict, repair: str = "", has_ticket: bool = True) -> tuple[int, str, str]:
    """(order, state, note) of an open pull request that is not in the merge queue."""
    status, merge, checks = r.get("status"), r.get("merge"), r.get("checks") or {}
    if status == "draft" or merge == "draft":
        return DRAFT, "Draft", "Not checked while it is a draft."
    if status == "checks failed":
        names = ", ".join((checks.get("failed_names") or [])[:2])
        what = f"Checks failed: {names}." if names else "A check failed."
        return NEEDS, "Checks failed", f"{what} {repair or 'Open the ticket to fix it.'}"
    if status == "conflict" or merge == "conflict":
        if not has_ticket:
            return (
                NEEDS,
                "Has a conflict",
                "No ticket is linked: make a ticket for it so a helper can sort out the conflict.",
            )
        return NEEDS, "Has a conflict", "Open the ticket to sort out the conflict."
    if status == "checks running":
        return OTHER, checks_text(checks).replace("Running", "Checks running"), ""
    if status == "ready to merge":
        return READY, "Ready to merge", "Not in the merge queue."
    return OTHER, MERGE_TEXT.get(merge, "Not known yet"), ""


def _queue_rows(root) -> list[dict]:
    try:
        rows = store.read(root)
    except Exception:  # noqa: BLE001 - a damaged queue file must not take the page down
        return []
    running = [r for r in rows if r.get("state") == store.RUNNING]
    return running + [r for r in rows if r.get("state") == store.WAITING]


def _queue_state(rows: list[dict], alive: bool, now: float) -> dict[str, dict]:
    """{url: {order, state, note, in_line}} for every pull request in the merge queue; the place counts within
    its own repository and base branch."""
    out, places = {}, {}  # each repository and base branch has its own line
    for r in rows:
        why = _plain_why(r.get("why") or "")
        line = (r.get("repo"), r.get("base"))
        if r.get("state") == store.RUNNING:
            order, state, place = CHECKING, "Being checked", 0
        else:
            places[line] = place = places.get(line, 0) + 1
            order, state = IN_LINE, _nth(place)
            later = float(r.get("not_before") or 0)
            if not alive:
                why = "The merge queue is not running; it starts again with the next pull request added."
            elif later > now:
                mins = max(1, round((later - now) / 60))
                state += ", paused"
                why = f"{why or 'Paused'}; tries again by itself in {mins} min."
        out[r["url"]] = {
            "order": (order, place),
            "state": state,
            "note": why,
            "in_line": _since(r.get("added"), now),
        }
    return out


def queue_blocks(root, data: dict, alive: bool, now: float) -> list[dict]:
    """The merge queue, one list per repository and base branch (a project whose pull requests are
    grouped and merged together): each group being checked with its pull requests, then the line. With nothing
    in the queue: one Merge queue block with its empty state, so the page always shows where the queue is."""
    rows = _queue_rows(root)
    size = settings.max_group(root)
    titles = {r.get("url"): r.get("title") for r in data["prs"].values() if r.get("title")}

    def name(r: dict) -> str:
        return _cut(_clean(r.get("title") or titles.get(r.get("url")) or f"#{r.get('number')}"), 80)

    if not rows:
        return [
            {
                "type": "list",
                "title": "Merge queue",
                "meta": f"groups of up to {size}",
                "items": [],
                "empty": {
                    "title": "Nothing in the merge queue",
                    "text": "A pull request put in the merge queue shows here with the group it is checked in.",
                },
            }
        ]
    projects: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        projects.setdefault((str(r.get("repo") or ""), str(r.get("base") or "")), []).append(r)
    blocks = []
    for (repo, base), mine in projects.items():
        items: list[dict] = []
        groups: dict[str, list[dict]] = {}
        for r in mine:
            if r.get("state") == store.RUNNING:
                groups.setdefault(str(r.get("group") or ""), []).append(r)
        for members in groups.values():
            n = len(members)
            taken = min((_since(m.get("taken"), now) or 0 for m in members), default=0)
            items.append(
                {
                    "title": (f"Group of {n}" if n > 1 else "Checked alone")
                    + (f" · checks running {minutes(taken)}" if taken else " · being checked"),
                    "subtitle": _cut("; ".join(name(m) for m in members), 200),
                    "tone": "neutral",
                }
            )
        waiting = [r for r in mine if r.get("state") == store.WAITING]
        if waiting:
            first = [name(r) for r in waiting[:2]]
            more = len(waiting) - len(first)
            sub = "Next: " + ", ".join(first) + (f" and {more} more" if more else "")
            longest = max((_since(r.get("added"), now) or 0 for r in waiting), default=0)
            item = {
                "title": f"{len(waiting)} waiting in line"
                + (f" · longest {minutes(longest)}" if longest else ""),
                "subtitle": sub[:200],
                "tone": "neutral",
            }
            if not alive:
                item["subtitle"] = (
                    "The merge queue is not running; it starts again with the next pull request added."
                )
                item["tone"] = "warn"
            items.append(item)
        meta = (f"into {base} · " if base else "") + f"groups of up to {size}"
        blocks.append(
            {
                "type": "list",
                "title": f"Merge queue: {repo}"[:60],
                "meta": meta[:60],
                "items": items,
            }
        )
    return blocks


def build(
    root, running: bool | None = None, queue_alive: bool | None = None, now: float | None = None
) -> dict:
    data = poll.load(root)
    if running is None:
        running = service.running_pid(root) is not None
    if queue_alive is None:
        from .cli import runner_alive

        queue_alive = runner_alive(root)
    now = time.time() if now is None else now
    ts = poll.tickets(root)
    owner = poll.ticket_of(ts)
    ids = {t["id"]: t["id"] for t in ts} | {str(t["key"]): t["id"] for t in ts if t.get("key")}
    keys = {t["id"]: t.get("key") or t["id"] for t in ts}
    repos = sorted(data["repos"].items(), key=lambda kv: kv[0].lower())
    every: list[dict] = []
    for repo, rec in repos:
        nums = set(rec.get("open") or [])
        every += [
            r
            for r in data["prs"].values()
            if r.get("repo") == repo and r.get("number") in nums and r.get("state") == "OPEN"
        ]
    qrows = _queue_rows(root)
    queue = _queue_state(qrows, queue_alive, now)
    runs, status = _runs(root), {t["id"]: str(t.get("status") or "") for t in ts}
    seen = {r["url"] for r in every}
    for q in qrows:  # in the queue but not read from a ticket's links: still shown, with what the queue knows
        if q["url"] not in seen:
            every.append(
                {"url": q["url"], "repo": q.get("repo"), "number": q.get("number"), "title": q.get("title")}
            )
            seen.add(q["url"])
    several = len({r.get("repo") for r in every}) > 1
    rows = []
    for r in every:
        tk = owner.get(r["url"])
        q = queue.get(r["url"])
        if q is None:
            order, state, note = _pr_state(r, repair_note(tk, runs, status), tk is not None)
            key, waited = (order, 0, -(r.get("number") or 0)), None
        else:
            state, note, waited = q["state"], q["note"], q["in_line"]
            key = (*q["order"], 0)
        if tk is None:  # the queue knows the ticket even when no link was read
            tid = ids.get(str(next((x.get("ticket") for x in qrows if x["url"] == r["url"]), "") or ""))
            tk = {"id": tid, "key": keys.get(tid, tid)} if tid else None
        sub = note or (str(r.get("repo") or "") if several else "")
        row = {
            "cells": {
                "pr": _clean(r.get("title") or f"#{r.get('number')}")[:200],
                "ticket": tk["key"] if tk else None,
                "state": state[:200],
                "in_line": waited,
            },
            "link": tk["id"] if tk else r["url"],
        }
        if sub:
            row["subtitle"] = sub[:200]
        rows.append((key, row))
    rows.sort(key=lambda kr: kr[0])
    # an empty queue shows where it is only beside open pull requests: a page with nothing gets one empty state
    blocks: list[dict] = queue_blocks(root, data, queue_alive, now) if every else []
    nrepos = len({r.get("repo") for r in every})
    if every:
        block = {
            "type": "table",
            "title": "Open pull requests",
            "meta": f"{len(every)} open" + (f" · {nrepos} repositories" if several else ""),
            "columns": COLUMNS,
            "rows": [row for _, row in rows[:MOST_ROWS]],
        }
        if len(rows) > MOST_ROWS:
            block["more"] = len(rows) - MOST_ROWS
        blocks.append(block)
    else:
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
    size = settings.max_group(root)
    blocks.append(
        {
            "type": "footnote",
            "text": f"The merge queue checks up to {size} pull requests together and merges them when the checks pass.",
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
