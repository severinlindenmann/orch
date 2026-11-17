"""`orch services view`: a minimal valid page (orch.addon-view/1, one list block). The real page is a later step."""

from __future__ import annotations

from . import store


def build(root, listing: tuple[list[dict], int, str | None]) -> dict:
    rows, _bad, note = listing
    items = []
    for r in rows[:50]:
        running = r["state"] == "running"
        sub = ("Running" if running else "Stopped") + (" · Starts by itself" if r["auto"] else "")
        items.append({"title": r["name"], "subtitle": sub, "tone": "good" if running else "neutral"})
    view = {
        "schema": "orch.addon-view/1",
        "generated_at": store.now(),
        "blocks": [
            {
                "type": "list",
                "title": "Services",
                "count": len(rows),
                "items": items,
                "empty": {
                    "title": "No services yet",
                    "text": "Your helper adds a service when a ticket needs something to keep running.",
                },
            }
        ],
    }
    if note:
        view["notice"] = note
        view["notice_tone"] = "warn"
    return view
