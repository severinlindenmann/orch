"""`orch lessons view`: the dashboard page blocks (orch.addon-view/1), read only."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from . import store

PROMPT = "Edit lesson"
ROWS = 50  # the list block holds at most this many rows (addon-view.schema.json)


def _day(iso: str) -> str:
    try:
        t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone()
        return f"{t.day} {t.strftime('%b')}"
    except ValueError:
        return iso[:10]


def _who(actor: str) -> str:
    name = actor.split(":", 1)[-1]
    return name[:1].upper() + name[1:]


def _ticket_label(root, tid: str) -> str:
    try:
        t = json.loads((root / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))
        key = t.get("key")
        if isinstance(key, str) and key:
            return key
    except (OSError, ValueError):
        pass
    return tid


def build(root) -> dict:
    data = store.load(root)
    items = []
    for r in data["lessons"][:ROWS]:
        sub = f"Added {_day(r['at'])} by {_who(r['by'])}"
        if r["outdated"]:
            sub += f" · last reviewed {_day(store.last_checked(r))}, check it still holds"
        if r.get("ticket"):
            sub += f" · from {_ticket_label(root, r['ticket'])}"
        item = {
            "title": r["text"],
            "subtitle": sub,
            "actions": [
                {
                    "label": "Edit",
                    "action": {
                        "op": "addon.prompt",
                        "args": {"verb": "edit", "target": r["id"], "value": r["text"], "label": PROMPT},
                    },
                },
                {
                    "label": "Delete",
                    "tone": "bad",
                    "action": {"op": "addon.act", "args": {"verb": "rm", "target": r["id"]}},
                },
            ],
        }
        if r.get("ticket"):
            item["link"] = r["ticket"]
        items.append(item)
    block = {
        "type": "list",
        "title": "Lessons",
        "count": len(data["lessons"]),
        "items": items,
        "empty": {
            "title": "No lessons yet",
            "text": "Your helper adds a lesson when it learns something the next helper should know.",
        },
    }
    view = {
        "schema": "orch.addon-view/1",
        "generated_at": store.now(),
        "blocks": [block],
    }
    notes = []
    if data["shown"] < len(data["lessons"]):
        notes.append("Helpers see only the newest lessons. Merge or delete some.")
    if len(data["lessons"]) > ROWS:
        notes.append(f"{len(data['lessons']) - ROWS} older lessons are not listed here: orch lessons list.")
    if data["unreadable"]:
        notes.append(f"{data['unreadable']} file(s) in .orch/addons/lessons could not be read and are skipped.")
    if notes:
        view["notice"] = " ".join(notes)
        view["notice_tone"] = "warn"
    return view
