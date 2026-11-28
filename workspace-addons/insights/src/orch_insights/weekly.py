"""The last 7 days from ticket history (`orch insights week`): tickets done, stuck now, time from new to Done.

One implementation, two surfaces (R4.3): `collect` reads the tickets and answers the facts (the CLI's --json);
`view` turns that answer into the plain words the CLI prints and the page shows. Read-only, nothing is stored.
"""

import re
from datetime import UTC, datetime, timedelta
from statistics import median

SCHEMA = "orch.insights.week/1"
DAYS = 7
TOP = 5  # done tickets listed by name; the rest is "and N more"
DONE_LINE = re.compile(r"Status \w+ -> done|Patched .*\(status \w+ -> done\)")  # as worktrees._DONE_LINE
FINISHED = ("done", "dropped")
WHY = {  # the dashboard's words for a stuck ticket (helpers.js stuckWords)
    "question": "Question waits",
    "quiet": "Quiet for a day",
    "overdue": "Past its due date",
    "helper": "Helper is stuck",
}
EMPTY = "Nothing was finished in the last 7 days and nothing is stuck."
ERROR = "Insights could not read the tickets."


def _at(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def done_at(root, ticket):
    """When the ticket last moved to Done: its newest history line that says so, else its last change."""
    from orch import history

    for h in reversed(history.lines(root, ticket)):
        if isinstance(h, dict) and DONE_LINE.fullmatch(str(h.get("text", ""))):
            at = _at(h.get("at"))
            if at:
                return at
    return _at(ticket.get("updated_at"))


def _counted(ticket):
    """Real work only: not the hidden General chat, not an epic or release (their sub-tickets are the work)."""
    return not any(ticket.get(k) is True for k in ("general", "epic", "release"))


def _name(ticket):
    return {"key": str(ticket.get("key") or ticket["id"]), "title": str(ticket.get("title") or "")[:200]}


def _stuck(root, open_):
    """{ticket id: reason} by the one Stuck rule every page uses (counts.stuck, ORCH-476)."""
    from orch import counts

    try:
        per = counts.summary(open_, counts.live_runs(root))["tickets"]
        return {tid: row["stuck"] for tid, row in per.items() if row.get("stuck")}
    except Exception:  # noqa: BLE001 - a run that cannot be read: the ticket rule alone
        return {t["id"]: why for t in open_ if (why := counts.stuck(t))}


def collect(root, now=None):
    """The facts of the last 7 days (and the 7 before, to compare). Only the tickets that can count are read
    (the ticket index): every unfinished one, and the finished ones changed in the last 14 days."""
    from orch import ticketindex

    now = now or datetime.now(UTC)
    start, before = now - timedelta(days=DAYS), now - timedelta(days=2 * DAYS)
    cutoff = before.isoformat().replace("+00:00", "Z")

    def keep(row):
        if row.get("status") == "dropped":
            return False
        return row.get("status") != "done" or str(row.get("updated_at") or "") >= cutoff[:19]

    found = [
        t for t in ticketindex.load_where(root, keep) if isinstance(t, dict) and isinstance(t.get("id"), str)
    ]
    done, earlier = [], 0
    for t in found:
        if t.get("status") != "done" or not _counted(t):
            continue
        at = done_at(root, t)
        if at is None or at > now or at < before:
            continue
        if at < start:
            earlier += 1
            continue
        made = _at(t.get("created_at"))
        took = int((at - made).total_seconds()) if made and made <= at else None
        done.append({**_name(t), "at": at.isoformat().replace("+00:00", "Z"), "took": took})
    done.sort(key=lambda d: d["at"], reverse=True)
    # every unfinished ticket, an epic too: the same Stuck count as "Stuck now" on every page
    open_ = [t for t in found if t.get("status") not in FINISHED and t.get("general") is not True]
    why = _stuck(root, open_)
    stuck = [{**_name(t), "why": why[t["id"]]} for t in open_ if t["id"] in why]
    return {
        "schema": SCHEMA,
        "days": DAYS,
        "from": start.isoformat().replace("+00:00", "Z"),
        "to": now.isoformat().replace("+00:00", "Z"),
        "done": done,
        "done_before": earlier,
        "stuck": stuck,
    }


def span(seconds):
    """A time from new to Done in plain words: "40 min", "5 h", "1 day", "3 days"."""
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    hours = round(seconds / 3600)
    if hours < 24:
        return f"{hours} h"
    days = round(seconds / 86400)
    return "1 day" if days == 1 else f"{days} days"


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _compare(now, then):
    if now == then:
        return "Same as the 7 days before"
    more = now - then
    return f"{abs(more)} {'more' if more > 0 else 'fewer'} than the 7 days before"


def _rows(items, keep):
    return [
        {"key": str(r.get("key") or ""), "title": str(r.get("title") or ""), **keep(r)}
        for r in items
        if isinstance(r, dict) and r.get("key")
    ]


def view(answer):
    """Plain words for the page and the CLI. Fails closed: an unreadable answer is an error, never zeros."""
    if not isinstance(answer, dict) or answer.get("schema") != SCHEMA:
        return {"error": ERROR}
    done = _rows(
        answer.get("done") or [], lambda r: {"took": _count(r.get("took")) if r.get("took") else None}
    )
    stuck = _rows(answer.get("stuck") or [], lambda r: {"why": WHY.get(r.get("why"), "Stuck")})
    took = [d["took"] for d in done if d["took"]]
    return {
        "window": "Last 7 days",
        "empty": not done and not stuck,
        "text": EMPTY if not done and not stuck else None,
        "done": len(done),
        "done_text": _compare(len(done), _count(answer.get("done_before"))),
        "typical": f"about {span(median(took))}" if took else None,
        "typical_text": (
            "from new to Done" + (f"; the longest took {span(max(took))}" if len(took) > 1 else "")
            if took
            else "Shows once a ticket is done"
        ),
        "stuck": len(stuck),
        "stuck_rows": stuck[:TOP],
        "stuck_more": max(0, len(stuck) - TOP),
        "done_rows": [{"key": d["key"], "title": d["title"]} for d in done[:TOP]],
        "more": max(0, len(done) - TOP),
    }


def text(v):
    """The CLI's words (`orch insights week`), the same facts the page shows."""
    if "error" in v:
        return v["error"]
    lines = [v["window"]]
    if v["empty"]:
        return "\n".join([*lines, v["text"], 'Next: open a ticket with `orch ticket new "<title>"`.'])
    lines.append(f"Done: {v['done']} ({v['done_text'].lower()})")
    lines += [f"  {r['key']}  {r['title']}" for r in v["done_rows"]]
    if v["more"]:
        lines.append(f"  and {v['more']} more")
    if v["typical"]:
        lines.append(f"Time to done: {v['typical']} {v['typical_text']}")
    lines.append(f"Stuck now: {v['stuck']}")
    lines += [f"  {r['key']}  {r['title']} ({r['why']})" for r in v["stuck_rows"]]
    if v["stuck_more"]:
        lines.append(f"  and {v['stuck_more']} more")
    lines.append(
        f"Next: look at a stuck ticket with `orch ticket show {v['stuck_rows'][0]['key']}`."
        if v["stuck_rows"]
        else "Next: see the page with `orch insights open`."
    )
    return "\n".join(lines)
