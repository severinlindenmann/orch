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
    """The Sync page: the saved setting as rows, the three places to keep a copy as one choice, then what was kept
    here. When the status can't be read the saved setting still shows, with one plain line and Try again."""
    now = now or datetime.now(UTC)
    saved = settings.get("mode") if settings.get("mode") in MODE else "off"
    try:
        s = act.status(root, settings)
        unreadable = False
    except Exception:  # noqa: BLE001 - the setting is known even when the live status is not
        s = {
            "mode": saved,
            "shown": "never",
            "last_ok": None,
            "remote": None,
            "not_synced": [],
            "last_error": None,
        }
        unreadable = True
    text, tone = STATE.get(s["shown"], STATE["never"])
    rows = [
        {
            "label": "Current setting",
            "value": MODE.get(s["mode"], "Off")[:120],
            "note": "Tickets and their files can be copied. Secrets and private files are never included.",
        }
    ]
    if s["mode"] != "off" and not unreadable:
        rows.append({"label": "Status", "value": clean(text, 120), "tone": tone})
        rows.append({"label": "Last synced", "value": local_time(s["last_ok"])})
        if s["mode"] == "remote" and s["remote"]:
            rows.append({"label": "Where", "value": clean(s["remote"], 120)})
    blocks = [
        {"type": "settings", "title": "Keep a copy of my tickets", "rows": rows},
        {
            "type": "radio",
            "title": "Where to keep a copy",
            "options": [
                {
                    "label": "Off",
                    "selected": s["mode"] == "off",
                    "action": {"op": "addon.act", "args": {"verb": "set", "target": "off"}},
                },
                {
                    "label": "On this computer only",
                    "selected": s["mode"] == "local",
                    "action": {"op": "addon.act", "args": {"verb": "set", "target": "local"}},
                },
                {
                    "label": "Also on another computer or server",
                    "selected": s["mode"] == "remote",
                    "link": "app:settings",  # the address is chosen and signed in Settings > General
                },
            ],
        },
    ]
    problems = s["not_synced"]
    if problems:
        blocks.append(
            {
                "type": "list",
                "title": f"Kept here, not synced \u00b7 {len(problems)}",
                "items": [
                    {"title": clean(p["name"]), "subtitle": clean(p["why"]), "tone": "warn"}
                    if p["why"]
                    else {"title": clean(p["name"]), "tone": "warn"}
                    for p in problems[:50]
                ],
                "more": max(0, len(problems) - 50),
            }
        )
    view = {
        "schema": "orch.addon-view/1",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "header": {"link": {"label": "\u2190 General settings", "to": "app:settings"}},
        "blocks": blocks,
    }
    if unreadable:
        view.update(
            notice="Can\u2019t read sync status. The saved setting is shown above. Nothing here was changed.",
            notice_tone="warn",
            button={"label": "Try again", "action": {"op": "addon.refresh"}},
        )
    elif s["shown"] in ("paused", "offline"):
        view.update(notice=clean(text), notice_tone=tone)
    elif s["last_error"] and s["last_error"] != "offline":
        view.update(notice=clean(f"{text}. Last problem: {s['last_error']}"), notice_tone="warn")
    return view
