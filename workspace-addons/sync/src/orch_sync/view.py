"""`orch sync view --json`: read-only blocks for the dashboard's Sync tab (contracts/addon-view.schema.json).

Plain words only: whether sync is on, when it last worked, and what was kept here (a ticket with a problem, a file
left out). Reads the same facts as the Sync card (`act.status`); changes nothing.
"""

import re
from datetime import UTC, datetime

from . import act

STATE = {
    "off": ("Sync is off", "neutral"),
    "never": ("Sync is on, nothing synced yet", "neutral"),
    "synced": ("Everything is synced", "good"),
    "syncing": ("Syncing now", "neutral"),
    "paused": ("Sync is paused, something needs you", "needs-you"),
    "offline": ("Sync can't reach the other place right now", "warn"),
}
MODE = {"off": "Off", "local": "On this computer", "remote": "On this computer and a remote place"}


def clean(s, n=190):
    return (re.sub(r"[<>]", "", " ".join(str(s).split())).strip()[:n]) or "-"


def local_time(iso):
    """An ISO time as the person reads it (this computer's zone), or 'never'."""
    try:
        dt = datetime.fromisoformat(str(iso))
    except ValueError:
        return "never"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone().strftime("%-d %b, %H:%M")


def build(root, settings, now=None):
    s = act.status(root, settings)
    now = now or datetime.now(UTC)
    text, tone = STATE.get(s["shown"], STATE["never"])
    blocks = [
        {"type": "stat", "label": "Sync", "value": MODE.get(s["mode"], "Off")[:24], "tone": tone},
        {"type": "stat", "label": "Last synced", "value": local_time(s["last_ok"])},
    ]
    if s["mode"] == "remote" and s["remote"]:
        blocks.append({"type": "stat", "label": "Where", "value": clean(s["remote"], 24)})
    problems = s["not_synced"]
    items = [
        {"title": clean(p["name"]), "subtitle": clean(p["why"]), "tone": "warn"}
        if p["why"]
        else {"title": clean(p["name"]), "tone": "warn"}
        for p in problems[:50]
    ]
    blocks.append(
        {
            "type": "list",
            "title": f"Kept here, not synced · {len(problems)}",
            "items": items or [{"title": "Nothing was left out", "tone": "good"}],
            "more": max(0, len(problems) - 50),
        }
    )
    view = {
        "schema": "orch.addon-view/1",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notice": clean(text),
        "notice_tone": tone,
        "blocks": blocks,
    }
    if s["last_error"] and s["last_error"] != "offline":
        view["notice"] = clean(f"{text}. Last problem: {s['last_error']}")
        view["notice_tone"] = "warn"
    return view
