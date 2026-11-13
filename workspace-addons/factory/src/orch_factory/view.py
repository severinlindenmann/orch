"""Read-only dashboard blocks."""

from datetime import datetime, timedelta

from .commands import listing
from .store import Store, now


def plain(text):
    return " ".join(str(text).replace("<", "").replace(">", "").split())[:200] or "Untitled"


def view(root):
    orders = listing(root)
    local = datetime.now().astimezone()
    monday = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    shipped = {
        r["order"]
        for r in Store(root).journal_read()
        if r["type"] == "shipped" and monday <= datetime.fromisoformat(r["at"]) <= local
    }
    waiting = [
        t for t in orders if not t["started"] and any(q["kind"] == "factory:start" for q in t["questions"])
    ]
    running = [t for t in orders if t["started"] and t["stage"] not in ("shipped", "cancelled")]
    finished = [t for t in orders if t["order"] in shipped]
    needs = [t for t in orders if any(q["kind"] != "factory:start" for q in t["questions"])]
    blocks = [
        {"type": "stat", "label": label, "value": len(items)}
        for label, items in (
            ("Waiting for your Start", waiting),
            ("Needs you", needs),
            ("Running", running),
            ("Shipped this week", finished),
        )
    ]
    for title, items in (
        ("Proposals waiting for Start", waiting),
        ("Running", running),
        ("Shipped this week", finished),
    ):
        blocks.append(
            {
                "type": "list",
                "title": title,
                "items": [
                    {
                        "title": plain(t["title"]),
                        "link": t["order"],
                        "subtitle": "running"
                        if t["started"] and t["stage"] == "proposed"
                        else plain(t["stage"]),
                    }
                    for t in items[:50]
                ],
                "more": max(0, len(items) - 50),
            }
        )
    return {"schema": "orch.addon-view/1", "generated_at": now(), "blocks": blocks}
