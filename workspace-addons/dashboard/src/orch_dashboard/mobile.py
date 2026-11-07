"""Mobile mode is the one feature of the relay add-on the dashboard shows. Everything that names the add-on lives
in this file (the other dashboard sources name no add-on; a test keeps it that way)."""
from __future__ import annotations

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


MOBILE_OPS = {"mobile.set": _mobile_set, "mobile.hours": _mobile_hours, "mobile.ack": _mobile_ack}


def load_mobile(root: Path, orch_bin: str | None) -> dict | None:
    """Mobile mode from `orch relay mobile status --json` (the relay add-on). None when the add-on is not on here:
    the page then shows no switch. Only the fields the page uses, strings cut short."""
    from .data import run_orch  # late: data imports this file
    d = run_orch(orch_bin, ["relay", "mobile", "status", "--json"], root)
    if not isinstance(d, dict) or not isinstance(d.get("on"), bool):
        return None
    s = lambda v, n=80: v[:n] if isinstance(v, str) else None
    ended = d.get("ended")
    ended = {"reason": s(ended.get("reason"), 10), "text": s(ended.get("text"), 200), "at": s(ended.get("at"), 30)} \
        if isinstance(ended, dict) and ended.get("text") else None
    choices = [h for h in (d.get("hours_choices") or []) if h in (4, 8, 12, 24)] or [4, 8, 12, 24]
    dh = d.get("default_hours")
    return {"on": d["on"], "default_hours": dh if dh in choices else 12, "hours_choices": choices,
            "awake": d.get("awake") if d.get("awake") in ("ok", "could_not_keep_awake") else None,
            "since": s(d.get("since"), 30), "ends_at": s(d.get("ends_at"), 30), "machine": s(d.get("machine"), 60), "ended": ended}
