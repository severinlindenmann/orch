"""Read-only dashboard blocks."""

from datetime import datetime, timedelta

from . import autopilot, flow, orchcli
from .commands import listing
from .store import Refused, Store, clock, now


def plain(text):
    return " ".join(str(text).replace("<", "").replace(">", "").split())[:200] or "Untitled"


def view(root):
    orders = listing(root)
    store = Store(root)
    tickets = orchcli.tickets(root)
    stops = []
    for t in orders:
        # A stop the agent decided under a valid autopilot grant no longer needs you.
        try:
            d = flow.derive(root, store, next(x for x in tickets if x["id"] == t["order"]), tickets)
        except Refused:
            continue
        t["questions"] = [q for q in t["questions"] if q["id"] not in d["decided_ok"]]
        if d["open"] and d["open"]["row"]["kind"] == "factory:stop":
            stops.append((t, d["open"]["data"]["stage"]))
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
    blocks.append(
        {
            "type": "list",
            "title": "Stops waiting for you",
            "items": [
                {"title": plain(t["title"]), "link": t["order"], "subtitle": "stop at " + plain(stage)}
                for t, stage in stops[:50]
            ],
            "more": max(0, len(stops) - 50),
        }
    )
    view = {"schema": "orch.addon-view/1", "generated_at": now(), "blocks": blocks}
    live = [g for g in autopilot.grants(store, tickets) if clock() < g["until"]]
    if live:
        today = sum(
            1
            for r in store.journal_read()
            if r["type"] == "decided" and datetime.fromisoformat(r["at"]).astimezone().date() == local.date()
        )
        until = max(g["until"] for g in live).astimezone().strftime("%d %b %H:%M")
        view["notice"] = f"Autopilot is on until {until} · decided today: {today}"
        view["notice_tone"] = "good"
    return view
