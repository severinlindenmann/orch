"""`orch personal view --json`: the dashboard tab data when the page is not running (one tile per part)."""

from __future__ import annotations

import time
from pathlib import Path

from . import api


def build(root: Path, who: api.Who) -> dict:
    d = api.today(root, who)
    blocks: list[dict] = []
    for t in d["parts"]:
        tone = {"ok": "good", "empty": "needs-you", "stopped": "warn"}.get(t["state"], "neutral")
        blocks.append(
            {"type": "stat", "label": t["label"][:40], "value": _clean(t["status"])[:24], "tone": tone}
        )
    if d.get("ways"):
        tone = {"works": "good", "permission": "needs-you", "stopped": "warn"}
        blocks.append(
            {
                "type": "list",
                "title": "Ways in",
                "items": [
                    {
                        "title": _clean(w["name"]),
                        "subtitle": _clean(
                            w["words"]
                            + (
                                f" · last worked {w['last_worked'][:16].replace('T', ' ')}"
                                if w.get("last_worked")
                                else ""
                            )
                        ),
                        "tone": tone.get(w["status"], "neutral"),
                    }
                    for w in d["ways"][:20]
                ],
            }
        )
    if d["needs_you"]:
        blocks.append(
            {
                "type": "list",
                "title": "Needs you now",
                "items": [
                    {"title": _clean(n["title"]), "subtitle": _clean(n["text"]), "tone": "needs-you"}
                    for n in d["needs_you"][:20]
                ],
            }
        )
    blocks.append({"type": "footnote", "text": "Helpers get only what each part allows."})
    view = {
        "schema": "orch.addon-view/1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "blocks": blocks,
    }
    if not d["parts"]:
        view["notice"] = "Nothing is added yet. Open Personal and add Notes."
    return view


def _clean(text: str) -> str:
    return (str(text).replace("<", "‹").replace(">", "›").strip() or "-")[:200]
