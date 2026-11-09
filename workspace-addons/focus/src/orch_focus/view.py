"""`orch focus view --json`: the dashboard tab "Focus" (addon-view.schema.json). Declarative blocks, no actions.

Live now = runs in a live session; Working now = one-shot runs. Each links to its page: addon:t/<ticket>."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from . import actions, livedata
from .server import agent_label


def _item(rec: dict, ticket: dict | None, attention: bool, agents: list[dict] | None = None) -> dict:
    live = rec.get("mode") == "live"
    label = agent_label(rec, agents)
    key = (ticket or {}).get("key")
    item = {
        "title": (f"{key} · " if isinstance(key, str) and key else "") + livedata.title(ticket),
        "subtitle": f"{label} · {'live session' if live else 'one run'}",
        "link": f"addon:t/{rec['ticket']}",
    }
    if attention:
        item["chips"] = [{"label": "Waiting for your OK", "tone": "needs-you"}]
        item["tone"] = "needs-you"
    else:
        item["tone"] = "good"
    return item


def _agents(root: Path, orch_bin: str | None) -> list[dict]:
    try:
        code, out, _ = actions.orch(root, orch_bin, ["agents", "--json"], timeout=10)
        data = json.loads(out) if code == 0 else []
    except (actions.Unavailable, ValueError):
        return []
    return [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []


def build(root: Path, orch_bin: str | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    recs = livedata.records(root)
    titles: dict[str, dict] = {}
    agents: list[dict] = []
    if recs:
        # both asks start an `orch` command: at the same time, so a slow machine pays for one, not two
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_titles = pool.submit(livedata.tickets, root, orch_bin)
            f_agents = pool.submit(_agents, root, orch_bin)
            titles, agents = f_titles.result(), f_agents.result()
    live, work = [], []
    for rec in recs:
        attention = (rec.get("live") or {}).get("state") == "attention"
        (live if rec.get("mode") == "live" else work).append(_item(rec, titles.get(rec["ticket"]), attention, agents))
    blocks: list[dict] = [
        {"type": "stat", "label": "Running now", "value": len(recs), "tone": "good" if recs else "neutral"}
    ]
    for name, items in (("Live now", live), ("Working now", work)):
        if items:
            blocks.append(
                {
                    "type": "list",
                    "title": name,
                    "items": items[:50],
                    **({"more": len(items) - 50} if len(items) > 50 else {}),
                }
            )
    view: dict = {
        "schema": "orch.addon-view/1",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "blocks": blocks,
    }
    if not recs:
        view["notice"] = "No agent is working on a ticket now."
    return view
