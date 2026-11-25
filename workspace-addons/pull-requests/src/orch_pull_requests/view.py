"""`orch pull-requests view`: the Pull requests page (orch.addon-view/1). Read only, from prs.json: no GitHub call."""

from __future__ import annotations

import re
import statistics
import time
from datetime import UTC, datetime, timedelta, tzinfo

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
    {"key": "num", "label": "#", "type": "text"},
    {"key": "pr", "label": "Pull request", "type": "text"},
    {"key": "why", "label": "What is going on", "type": "text"},
    {"key": "ticket", "label": "Ticket", "type": "text"},
    {"key": "state", "label": "State", "type": "text"},
    {"key": "in_line", "label": "In line for", "type": "duration"},
]
FOLD = 15  # rows shown under All before "Show N more"
DAYS = 14  # the charts' span
CHIPS = 30  # pull requests shown in one stage of a merge queue
RECENT_GROUPS = 12  # the bars under "Merged lately"
# the State column is the tab: one word per kind, its colour; the detail sits in "What is going on"
TONE = {"Checks failed": "bad", "Has a conflict": "warn", "Ready to merge": "good"}


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


def repair_note(tk: dict | None, runs: dict[str, str] | None) -> str:
    """Whether a helper is on the linked ticket of a red pull request, read from `orch run list` (`runs`; None when
    it could not be read). An open ticket is not a helper waiting for it, and a helper on the ticket may be busy with
    other work, so the words never say it is fixing the check. The ticket is named, so it stays with the check."""
    if not tk:
        return "No ticket is linked: make a ticket for it so a helper can fix it."
    key = _clean(tk.get("key") or tk["id"])[:40]
    if runs is None:
        return f"Helper status on {key} could not be checked; tries again by itself."
    if tk["id"] in runs:
        return f"A helper is running on {key}, maybe not on this check."
    return f"No helper running on {key}. Open the ticket to fix it."


def _runs(root) -> dict[str, str] | None:
    """{ticket id: helper name} of every live helper run; None when orch cannot list them (not known, not "none")."""
    got = poll.orch(root, "run", "list")
    rows = got.get("runs") if isinstance(got, dict) else None
    if not isinstance(rows, list):
        return None
    return {
        r["ticket"]: str(r.get("agent") or "")
        for r in rows
        if isinstance(r, dict) and isinstance(r.get("ticket"), str) and r.get("state") == "alive"
    }


def _pr_state(r: dict, repair: str = "", has_ticket: bool = True) -> tuple[int, str, str]:
    """(order, state, note) of an open pull request that is not in the merge queue."""
    status, merge, checks = r.get("status"), r.get("merge"), r.get("checks") or {}
    if status == "draft" or merge == "draft":
        return DRAFT, "Draft", "Not checked while it is a draft."
    if status == "checks failed":
        names = ", ".join((checks.get("failed_names") or [])[:2])
        what = (
            f"{names} failed." if names else "A check failed."
        )  # the check first: the State column says the rest
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
        left = checks.get("running")
        return OTHER, "Checks running", f"{left} checks left." if left else ""
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
        paused = False
        if r.get("state") == store.RUNNING:
            order, state, place = CHECKING, "Being checked", 0
            where = "In the group being checked"
        else:
            places[line] = place = places.get(line, 0) + 1
            order, state = IN_LINE, "In line"
            where = _nth(place)[:1].upper() + _nth(place)[1:]
            later = float(r.get("not_before") or 0)
            if not alive:
                why = "The merge queue is not running; it starts again with the next pull request added."
            elif later > now:
                mins = max(1, round((later - now) / 60))
                where += ", paused"
                paused = True
                why = f"{why or 'Paused'}; tries again by itself in {mins} min."
        out[r["url"]] = {
            "order": (order, place),
            "state": state,
            "place": place,
            "paused": paused,
            "note": f"{where}. {why}" if why else f"{where.rstrip('.')}.",
            "why": why,
            "in_line": _since(r.get("added"), now),
        }
    return out


def _stamp(stamp) -> float | None:
    try:
        return datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None


def _short(repo: str) -> str:
    return str(repo or "").rsplit("/", 1)[-1]


def _when(t: float, now: float, tz: tzinfo | None) -> str:
    """'09:40' today, '18 Nov 19:40' before."""
    d, today = datetime.fromtimestamp(t, tz), datetime.fromtimestamp(now, tz)
    return d.strftime("%H:%M") if d.date() == today.date() else f"{d.day} {d:%b %H:%M}"


def _days(now: float, tz: tzinfo | None) -> tuple[list[str], dict]:
    """The charts' labels (oldest first, the last one 'Today') and {date: index}."""
    today = datetime.fromtimestamp(now, tz).date()
    dates = [today - timedelta(days=DAYS - 1 - i) for i in range(DAYS)]
    labels = [f"{d.day} {d:%b}" for d in dates[:-1]] + ["Today"]
    return labels, {d: i for i, d in enumerate(dates)}


def _day(t: float | None, index: dict, tz: tzinfo | None) -> int | None:
    return None if t is None else index.get(datetime.fromtimestamp(t, tz).date())


def _sent_back(r: dict) -> bool:
    """Out of the queue by the queue itself (checks failed, a conflict ...), not taken out by someone."""
    return r.get("state") == store.OUT and not str(r.get("why") or "").lower().startswith("taken out by")


def _finished_groups(rows: list[dict]) -> list[dict]:
    """Groups the queue checked and finished, oldest first: {size, merged, ended, mins, wait, urls}."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        manual = r.get("state") == store.OUT and not _sent_back(
            r
        )  # taken out by someone: not how a group went
        if r.get("state") in store.FINISHED and r.get("taken") and _stamp(r.get("ended")) and not manual:
            groups.setdefault(str(r.get("taken")), []).append(r)  # one check run: claimed together
    out = []
    for members in groups.values():
        ended = max(_stamp(m.get("ended")) or 0 for m in members)
        taken = min(_stamp(m.get("taken")) or ended for m in members)
        waits = [ended - a for a in (_stamp(m.get("added")) for m in members) if a]
        out.append(
            {
                "size": len(members),
                "merged": sum(1 for m in members if m.get("state") == store.MERGED),
                "ended": ended,
                "mins": max(1, round((ended - taken) / 60)),
                "wait": statistics.median(waits) if waits else None,
                "urls": [m["url"] for m in members],
            }
        )
    return sorted(out, key=lambda g: g["ended"])


def _chip(r: dict, name: str, place: int | None = None, tone: str | None = None, hint: str = "") -> dict:
    c = {"label": f"#{r.get('number')}", "link": r["url"], "hint": (hint or name)[:200]}
    if place:
        c["place"] = place
    if tone:
        c["tone"] = tone
    return c


def queue_blocks(root, data: dict, alive: bool, now: float, tz: tzinfo | None = None) -> list[dict]:
    """The merge queue, one flow per repository and base branch (a project whose pull requests are grouped and
    merged together): being checked -> in line -> merged lately, each pull request a chip that opens it on GitHub.
    With nothing in the queue and nothing merged by it lately: one Merge queue block with its empty state."""
    try:
        every = store.read(root)
    except Exception:  # noqa: BLE001 - a damaged queue file must not take the page down
        every = []
    size = settings.max_group(root)
    titles = {r.get("url"): r.get("title") for r in data["prs"].values() if r.get("title")}

    def name(r: dict) -> str:
        return _cut(_clean(r.get("title") or titles.get(r.get("url")) or f"#{r.get('number')}"), 80)

    since = now - DAYS * 86400
    projects: dict[tuple[str, str], list[dict]] = {}
    for r in every:
        live = r.get("state") in (store.RUNNING, store.WAITING)
        if live or (_stamp(r.get("ended")) or 0) >= since:
            projects.setdefault((str(r.get("repo") or ""), str(r.get("base") or "")), []).append(r)
    if not projects:
        return [
            {
                "type": "list",
                "title": "Merge queue",
                "meta": f"groups of up to {size}",
                "items": [],
                "empty": {
                    "title": "Nothing in the merge queue",
                    "text": "A pull request put in the merge queue shows here with the group it is checked in.",
                    "button": {"label": "Open tickets", "to": "app:tickets"},  # ORCH-1697: one next step
                },
            }
        ]
    blocks = []
    for (repo, base), mine in sorted(projects.items(), key=lambda kv: (kv[0][0].lower(), kv[0][1])):
        running = [r for r in mine if r.get("state") == store.RUNNING]
        waiting = [r for r in mine if r.get("state") == store.WAITING]
        groups = _finished_groups(mine)
        usual = statistics.median([g["mins"] for g in groups[-20:]]) if groups else None
        # 1. being checked
        if running:
            n_groups = len({str(r.get("group") or r.get("taken") or r["url"]) for r in running})
            taken = max((_since(r.get("taken"), now) or 0 for r in running), default=0)
            mins = taken // 60
            check = {
                "label": "Being checked",
                "value": (f"Group of {len(running)}" if len(running) > 1 else "Checked alone")
                if n_groups == 1
                else f"{n_groups} groups · {len(running)} pull requests",
                "active": True,
                "items": [_chip(r, name(r)) for r in running[:CHIPS]],
            }
            text = f"checks running {minutes(taken)}" if taken else "checks starting"
            if usual:
                text += f" · usually done in about {round(usual)} min"
                check["progress"] = {
                    "value": min(mins, round(usual)),
                    "max": round(usual),
                    "label": f"Checks running {mins} of about {round(usual)} minutes",
                }
            check["text"] = text
            if len(running) > CHIPS:
                check["more"] = len(running) - CHIPS
        else:
            check = {
                "label": "Being checked",
                "value": "Nothing right now",
                "text": "The next group starts by itself." if waiting else "Nothing waiting.",
            }
        if not alive:
            check["tone"] = "warn"
            check["text"] = (
                "The merge queue is not running; it starts again with the next pull request added."
            )
        # 2. in line
        line = {"label": "In line", "value": f"{len(waiting)} waiting" if waiting else "Nobody waiting"}
        if waiting:
            longest = max((_since(r.get("added"), now) or 0 for r in waiting), default=0)
            paused = sum(1 for r in waiting if float(r.get("not_before") or 0) > now)
            line["text"] = (f"longest {minutes(longest)}" if longest else "just joined") + (
                f" · {paused} paused" if paused else ""
            )
            items = []
            for i, r in enumerate(waiting[:CHIPS], 1):
                later = float(r.get("not_before") or 0) > now
                items.append(
                    _chip(
                        r,
                        name(r),
                        place=i,
                        tone="warn" if later else None,
                        hint=name(r) + (" (paused)" if later else ""),
                    )
                )
            line["items"] = items
            if len(waiting) > CHIPS:
                line["more"] = len(waiting) - CHIPS
        # 3. merged lately
        recent = groups[-RECENT_GROUPS:]
        done = {"label": "Merged lately"}
        if recent:
            whole = sum(1 for g in recent if g["merged"] == g["size"])
            part = sum(1 for g in recent if 0 < g["merged"] < g["size"])
            done["value"] = f"{whole + part} of {len(recent)} groups"
            waits = [g["wait"] for g in recent if g["wait"]]
            bits = [f"{part} merged in part" if part else "", f"{len(recent) - whole - part} sent back"]
            if waits:
                bits.append(f"typical wait {minutes(int(statistics.median(waits)))}")
            done["text"] = " · ".join(b for b in bits if b)

            def went(g: dict) -> tuple[str, str]:
                if g["merged"] == g["size"]:
                    return "good", "merged"
                if g["merged"]:
                    return "warn", f"{g['merged']} merged, {g['size'] - g['merged']} sent back"
                return "bad", "sent back"

            done["bars"] = [
                {
                    "value": g["size"],
                    "tone": went(g)[0],
                    "hint": f"{_when(g['ended'], now, tz)}: group of {g['size']}, {went(g)[1]} after {g['mins']} min",
                }
                for g in recent
            ]
            done["bars_label"] = f"{whole + part} of the last {len(recent)} groups merged all or in part"
            merged = sorted(
                (r for r in mine if r.get("state") == store.MERGED),
                key=lambda r: _stamp(r.get("ended")) or 0,
                reverse=True,
            )[:6]
            done["items"] = [_chip(r, name(r), tone="good") for r in merged]
            if not done["items"]:
                del done["items"]
        else:
            done.update(value="Nothing yet", text="Merged groups show here.")
        meta = (f"into {base} · " if base else "") + f"groups of up to {size}"
        block = {
            "type": "flow",
            "title": f"Merge queue: {repo}"[:60],
            "meta": meta[:60],
            "stages": [check, line, done],
        }
        if re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            block["link"] = f"https://github.com/{repo}/pulls"
        blocks.append(block)
    return blocks


def chart_blocks(root, data: dict, now: float, tz: tzinfo | None = None) -> list[dict]:
    """Two charts side by side, per day over the last two weeks: pull requests opened and merged (from what GitHub
    said about the linked ones, plus what the merge queue merged), and how the merge queue went (merged or sent back)."""
    try:
        rows = store.read(root)
    except Exception:  # noqa: BLE001
        rows = []
    labels, index = _days(now, tz)
    opened, merged = [0] * DAYS, [0] * DAYS
    merged_urls = set()
    for r in data["prs"].values():
        i = _day(_stamp(r.get("created_at")), index, tz)
        if i is not None:
            opened[i] += 1
        i = _day(_stamp(r.get("merged_at")), index, tz)
        if i is not None:
            merged[i] += 1
            merged_urls.add(r.get("url"))
    q_merged, q_back = [0] * DAYS, [0] * DAYS
    for r in rows:
        i = _day(_stamp(r.get("ended")), index, tz)
        if i is None:
            continue
        if r.get("state") == store.MERGED:
            q_merged[i] += 1
            if r["url"] not in merged_urls:  # merged by the queue, GitHub's date not read yet
                merged[i] += 1
                merged_urls.add(r["url"])
        elif _sent_back(r):
            q_back[i] += 1
    first = {
        "type": "chart",
        "title": "Opened and merged per day",
        "meta": f"last {DAYS} days",
        "span": "half",
        "labels": labels,
        "series": [
            {"name": "Opened", "tone": "neutral", "values": opened},
            {"name": "Merged", "tone": "good", "values": merged},
        ],
        "empty": {"title": "Nothing in the last two weeks", "text": "Linked pull requests show here by day."},
    }
    waits = [
        e - a
        for r in rows
        if r.get("state") == store.MERGED
        for a, e in [(_stamp(r.get("added")), _stamp(r.get("ended")))]
        if a and e and _day(e, index, tz) == DAYS - 1
    ]
    second = {
        "type": "chart",
        "title": "How the merge queue went",
        "meta": (
            f"typical wait today {minutes(int(statistics.median(waits)))}" if waits else f"last {DAYS} days"
        )[:60],
        "span": "half",
        "labels": labels,
        "stacked": True,
        "series": [
            {"name": "Merged", "tone": "good", "values": q_merged},
            {"name": "Sent back", "tone": "bad", "values": q_back},
        ],
        "empty": {
            "title": "The merge queue has not run lately",
            "text": "Each day shows what it merged and sent back.",
        },
    }
    return [first, second]


def build(
    root,
    running: bool | None = None,
    queue_alive: bool | None = None,
    now: float | None = None,
    tz: tzinfo | None = None,
) -> dict:
    """The page. `tz` is the time zone of the charts' days (None: this computer's)."""
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
    runs = _runs(root)
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
            order, state, note = _pr_state(r, repair_note(tk, runs), tk is not None)
            key, waited = (order, 0, -(r.get("number") or 0)), None
        else:
            state, note, waited = q["state"], q["note"], q["in_line"]
            key = (*q["order"], 0)
        if tk is None:  # the queue knows the ticket even when no link was read
            tid = ids.get(str(next((x.get("ticket") for x in qrows if x["url"] == r["url"]), "") or ""))
            tk = {"id": tid, "key": keys.get(tid, tid)} if tid else None
        why = note or ""
        if several:
            why = f"{_short(r.get('repo'))} · {why}" if why else _short(r.get("repo"))
        row = {
            "cells": {
                "num": f"#{r.get('number')}",
                "pr": _clean(r.get("title") or f"#{r.get('number')}")[:200],
                "why": why[:200] or None,
                "ticket": tk["key"] if tk else None,
                "state": state[:200],
                "in_line": waited,
            },
            "link": tk["id"] if tk else r["url"],
            "links": {"num": r["url"], **({"ticket": tk["id"]} if tk else {})},
        }
        if state in TONE:
            row["tones"] = {"state": TONE[state]}
        rows.append((key, row))
    rows.sort(key=lambda kr: kr[0])
    blocks: list[dict] = []
    # the merge queue first (owner pick B, ORCH-746), then the two charts, then every open pull request; with no open
    # pull request the queue's recent work and the charts still show when there is any, above the empty state
    flows = [b for b in queue_blocks(root, data, queue_alive, now, tz) if b["type"] == "flow" or every]
    charts = chart_blocks(root, data, now, tz)
    if every or flows or any(v for c in charts for x in c["series"] for v in x["values"]):
        blocks += flows + charts
    if every:
        nrepos = len({r.get("repo") for r in every})
        block = {
            "type": "table",
            "title": "Open pull requests",
            "meta": f"{len(every)} open" + (f" · {nrepos} repositories" if several else ""),
            "columns": COLUMNS,
            "rows": [row for _, row in rows[:MOST_ROWS]],
            "compact": True,
            "filter": "state",
            "fold": FOLD,
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
                    "button": {"label": "Open tickets", "to": "app:tickets"},  # ORCH-1697: one next step
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
