"""Mobile mode and the Relay tab's "Send a message" are what the dashboard shows of the relay add-on. Everything that names the add-on lives
in this file (the other dashboard sources name no add-on; a test keeps it that way)."""

from __future__ import annotations

import re
from pathlib import Path

HOURS = (4, 8, 12, 24)


def _actions():
    from . import actions  # imported late: actions builds its op table from this file

    return actions


def _bad(msg):
    return _actions().BadRequest(msg)


def _hours(v) -> int:
    if isinstance(v, bool) or v not in HOURS:
        raise _bad("Pick 4, 8, 12 or 24 hours.")
    return v


def _mobile_set(a):
    """Mobile mode on or off: `orch relay mobile on [--hours=N]` / `off` (the relay add-on does the work)."""
    _only = _actions()._only
    _only(a, ("on", "hours"))
    if not isinstance(a.get("on"), bool):
        raise _bad("Say on or off.")
    if not a["on"]:
        if "hours" in a:
            raise _bad("Hours only go with turning it on.")
        return ["relay", "mobile", "off"], [], []
    return ["relay", "mobile", "on"], ([f"--hours={_hours(a['hours'])}"] if "hours" in a else []), []


def _mobile_hours(a):
    """Save how long Mobile mode stays on by default: `orch relay mobile hours N`."""
    _only = _actions()._only
    _only(a, ("hours",))
    return ["relay", "mobile", "hours", str(_hours(a.get("hours")))], [], []


def _mobile_ack(a):
    """Dismiss the 'Mobile mode ended' notice: `orch relay mobile ack`."""
    _only = _actions()._only
    _only(a, ())
    return ["relay", "mobile", "ack"], [], []


PEER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


def _relay_send(a):
    """Send a text to a workspace or phone from the Relay tab: `orch relay send <peer> -- <text>`."""
    acts = _actions()
    acts._only(a, ("workspace", "text"))
    peer = a.get("workspace")
    if not (isinstance(peer, str) and PEER.fullmatch(peer)):
        raise _bad("Choose who to send to.")
    return ["relay", "send", peer], [], [acts._text(a.get("text"), "message")]


MOBILE_OPS = {
    "mobile.set": _mobile_set,
    "mobile.hours": _mobile_hours,
    "mobile.ack": _mobile_ack,
    "message.send": _relay_send,
}


def load_mobile(root: Path, orch_bin: str | None) -> dict | None:
    """Mobile mode from `orch relay mobile status --json` (the relay add-on). None when the add-on is not on here:
    the page then shows no switch. Only the fields the page uses, strings cut short."""
    from .data import run_orch  # late: data imports this file

    d = run_orch(orch_bin, ["relay", "mobile", "status", "--json"], root)
    if not isinstance(d, dict) or not isinstance(d.get("on"), bool):
        return None
    s = lambda v, n=80: v[:n] if isinstance(v, str) else None
    ended = d.get("ended")
    ended = (
        {
            "reason": s(ended.get("reason"), 10),
            "text": s(ended.get("text"), 200),
            "at": s(ended.get("at"), 30),
        }
        if isinstance(ended, dict) and ended.get("text")
        else None
    )
    choices = [h for h in (d.get("hours_choices") or []) if h in (4, 8, 12, 24)] or [4, 8, 12, 24]
    dh = d.get("default_hours")
    return {
        "on": d["on"],
        "default_hours": dh if dh in choices else 12,
        "hours_choices": choices,
        "awake": d.get("awake") if d.get("awake") in ("ok", "could_not_keep_awake") else None,
        "since": s(d.get("since"), 30),
        "ends_at": s(d.get("ends_at"), 30),
        "machine": s(d.get("machine"), 60),
        "ended": ended,
    }


def is_chat_entry(e: dict) -> bool:
    """A history line that is a real Chat message: the core's `chat_message: true` flag. Lines written before the
    flag existed (no key at all) count only when they came from a person on the dashboard (human:) or from the
    relay for a phone text ("agent:relay from ph_..."); `via` alone is env-controlled and never enough."""
    if not isinstance(e, dict):
        return False
    if "chat_message" in e:
        return e["chat_message"] is True
    by, via = str(e.get("by", "")), e.get("via")
    return (via == "dashboard" and by.startswith("human:")) or (via == "phone" and by.startswith("agent:relay from ph_"))


def mark_chat_history(t: dict) -> None:
    """`in_chat: true` on the history entries that are real Chat/group messages, so the Chat page shows messages
    only: never run, task, status or instruction rows."""
    for e in t["history"]:
        if is_chat_entry(e):
            e["in_chat"] = True
