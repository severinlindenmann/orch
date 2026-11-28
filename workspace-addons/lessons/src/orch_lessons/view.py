"""`orch lessons view`: the dashboard page blocks (orch.addon-view/1), read only."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from . import store

PROMPT = "Edit lesson"
_ANGLE = re.compile(r"[<>]")  # the dashboard shows plain text only (addon-view.schema.json)
MAX_ROWS = 50  # maxItems of a list block in the view schema
MAX_PAGES = 20  # maxItems of a view's blocks: 1000 lessons can be reached page by page
TITLE = "Saved lessons"


def _day(iso: str) -> str:
    try:
        t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).astimezone()
        return f"{t.day} {t.strftime('%b')}"
    except ValueError:
        return iso[:10]


def _who(actor: str) -> str:
    name = actor.split(":", 1)[-1]
    return name[:1].upper() + name[1:]


def _ticket(root, tid: str) -> dict:
    """The source ticket as the dashboard links it: its key and title when the file reads, else the bare id."""
    out = {"id": tid, "title": tid}
    try:
        t = json.loads((root / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if not isinstance(t, dict):  # a ticket file that holds a list or a bare value: the bare id
        return out
    key, title = t.get("key"), t.get("title")
    if isinstance(key, str) and 1 <= len(key) <= 24 and not _ANGLE.search(key):
        out["key"] = key
    title = " ".join(_ANGLE.sub("", title).split())[:200] if isinstance(title, str) else ""
    if title:
        out["title"] = title
    return out


def _item(root, r: dict) -> dict:
    sub = f"Added {_day(r['at'])} by {_who(r['by'])}"
    src = _ticket(root, r["ticket"]) if r.get("ticket") else None
    if src:
        sub += f" · from {src.get('key') or src['id']}"
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
    if src:
        item["link"] = src["id"]
        # the row opens like an accordion: the source ticket is a real link inside it
        if src["title"] != src["id"]:
            item["tickets"] = [src]
    return item


def build(root) -> dict:
    """W-052 (owner 28 Nov): every lesson can be reached. The lessons go out as pages of one list (blocks with the
    same title, 50 rows each, newest first); the dashboard shows one page at a time and each row keeps Edit and
    Delete. There is no delete-many."""
    data = store.load(root)
    total = len(data["lessons"])
    listed = data["lessons"][: MAX_ROWS * MAX_PAGES]
    pages = [listed[i : i + MAX_ROWS] for i in range(0, len(listed), MAX_ROWS)] or [[]]
    blocks = [
        {
            "type": "list",
            "title": TITLE,
            "count": total,
            "items": [_item(root, r) for r in page],
            **(
                {
                    "empty": {
                        "title": "No lessons yet",
                        "text": "Your helper adds a lesson when it learns something the next helper should know. Nothing to do for you.",
                    }
                }
                if n == 0
                else {}
            ),
        }
        for n, page in enumerate(pages)
    ]
    older = total - MAX_ROWS
    view = {
        "schema": "orch.addon-view/1",
        "generated_at": store.now(),
        # with older lessons the heading's link leads to them (it is the warning's one button); else back to Add-ons
        "header": {
            "link": {"label": "Show older lessons", "to": "app:addon/lessons"}
            if older > 0
            else {"label": "← Add-ons", "to": "app:settings/addons"}
        },
        "blocks": blocks,
    }
    notes = []
    if data["shown"] < total:
        notes.append("The list is too long: helpers see only the newest lessons. Shorten or delete old ones.")
    if older > 0:
        notes.append(
            f"This page shows {MAX_ROWS} at a time; {older} older "
            f"{'is' if older == 1 else 'are'} on the next page{'' if len(pages) == 2 else 's'}."
        )
    unlisted = total - len(listed)
    if unlisted > 0:
        notes.append(f"The oldest {unlisted} show once newer ones are deleted.")
    n = data["unreadable"]
    if n:
        what = (
            "1 lesson file could not be read and is left out"
            if n == 1
            else f"{n} lesson files could not be read and are left out"
        )
        notes.append(
            f"{what}. Fix or delete {'it' if n == 1 else 'them'} in the folder .orch/addons/lessons."
        )
    if notes:
        view["notice"] = " ".join(notes)
        view["notice_tone"] = "warn"
    return view
