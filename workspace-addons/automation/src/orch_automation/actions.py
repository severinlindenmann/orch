"""`orch automation act <verb> <ticket>`: what the dashboard's switch and buttons do (one verb, one ticket).

Delete removes the repeat (ext.automation) and keeps the ticket and its history: tickets are never deleted here.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import orchcli

VERBS = ("on", "off", "toggle", "run", "delete")
TID = re.compile(r"t_[a-z0-9]{6,16}")


class Bad(Exception):
    """The request is not allowed or could not be done (plain words)."""


def act(root: Path, verb: str, target: str) -> dict:
    if verb not in VERBS:
        raise Bad("That is not something automation can do.")
    if not isinstance(target, str) or not TID.fullmatch(target):
        raise Bad("That is not a ticket id.")
    t = next((x for x in orchcli.tickets(root) if x["id"] == target), None)
    if t is None:
        raise Bad(f"There is no ticket {target}.")
    sched = (t.get("ext") or {}).get("automation") or {}
    if verb == "run":
        r = orchcli.run_start(root, target)
        if r["result"] == "failed":
            raise Bad(r["reason"])
        return {"ticket": target, "result": r["result"],
                "text": "Run started." if r["result"] == "started" else "The ticket is busy: your request waits for the current run."}
    if not sched:
        raise Bad("This ticket has no automation to change.")
    if verb == "delete":
        if not orchcli.set_ext(root, t, remove=tuple(sched)):
            raise Bad("The ticket changed or the change was not accepted. Try again.")
        return {"ticket": target, "deleted": True, "text": "Removed. The ticket stays."}
    paused = (verb == "off") if verb != "toggle" else sched.get("paused") is not True
    if not orchcli.set_ext(root, t, paused=paused):
        raise Bad("The ticket changed or the change was not accepted. Try again.")
    return {"ticket": target, "paused": paused, "text": "Switched off." if paused else "Switched on."}
