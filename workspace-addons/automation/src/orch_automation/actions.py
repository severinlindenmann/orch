"""`orch automation act <verb> <ticket> [--by <actor>]`: what the dashboard's switch and buttons do (one verb, one ticket).

Delete removes the whole ext.automation entry (orch ext unset) and keeps the ticket and its history: tickets are never deleted here.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from . import orchcli, scripts
from .loop import record_last_run, script_of, start_script

VERBS = ("on", "off", "toggle", "run", "delete", "repeat", "copy", "allow-script")
KEY = re.compile(r"[0-9a-f]{64}")
TID = re.compile(r"t_[a-z0-9]{6,16}")


class Bad(Exception):
    """The request is not allowed or could not be done (plain words)."""


def act(root: Path, verb: str, target: str, by: str | None = None, value: str | None = None) -> dict:
    if verb not in VERBS:
        raise Bad("That is not something automation can do.")
    if not isinstance(target, str) or not TID.fullmatch(target):
        raise Bad("That is not a ticket id.")
    if value is not None and verb not in ("repeat", "allow-script"):
        raise Bad("Only repeat takes a time.")
    if verb == "repeat":
        if not isinstance(value, str) or not value.strip() or len(value) > 200 or "\x00" in value:
            raise Bad("Say when in at most 200 characters.")
        from .cli import Refused, repeat

        try:
            return {**repeat(root, target, value, False, by=by), "text": "Repeat saved."}
        except Refused as e:
            raise Bad(str(e)) from None
    t = next((x for x in orchcli.tickets(root) if x["id"] == target), None)
    if t is None:
        raise Bad(f"There is no ticket {target}.")
    if verb == "copy":
        flags = []
        for field in ("owner", "note"):
            v = t.get(field) or (t.get("description") if field == "note" else None)
            if v:
                flags.append(f"--{field}={v}")
        parent = t.get("parent")
        if parent:
            if not isinstance(parent, str) or not TID.fullmatch(parent):
                raise Bad("That is not a parent ticket id.")
            flags.append(f"--parent={parent}")
        new = orchcli.call(root, "ticket", "new", *flags, "--", t["title"], by=by or True)
        if not isinstance(new, dict) or not isinstance(new.get("id"), str) or not TID.fullmatch(new["id"]):
            raise Bad("The copy could not be made. Try again.")
        if orchcli.call(root, "log", new["id"], "--", f"Copy of {target}", by=by or True) is None:
            raise Bad(f"The copy {new['id']} was made, but its log could not be added.")
        return {"ticket": new["id"], "text": "Copy created."}
    sched = (t.get("ext") or {}).get("automation") or {}
    if verb == "allow-script":
        name = script_of(t)
        if not name:
            raise Bad("This repeat runs no script.")
        if not isinstance(value, str) or not KEY.fullmatch(value):
            raise Bad("Look at the command again.")
        try:
            scripts.allow(root, name, value)
        except scripts.ScriptError as e:
            raise Bad(str(e)) from None
        return {"ticket": target, "script": name, "allowed": True, "text": "Script allowed."}
    if verb == "run":
        name = script_of(t)
        r = start_script(root, t, name) if name else orchcli.run_start(root, target, by=by)
        if r["result"] == "failed":
            raise Bad(r["reason"])
        if sched:  # a manual run counts as the last run (same writer as the schedule); re-read: the run bumped the revision
            fresh = next((x for x in orchcli.tickets(root) if x["id"] == target), t)
            record_last_run(root, fresh, datetime.now(UTC), by=by)
        return {
            "ticket": target,
            "result": r["result"],
            "text": "Run started."
            if r["result"] == "started"
            else "It is still running from before."
            if name
            else "The ticket is busy: your request waits for the current run.",
        }
    if not sched:
        raise Bad("This ticket has no automation to change.")
    if verb == "delete":
        if not orchcli.ext_unset(root, t, by=by):
            raise Bad("The ticket changed or the change was not accepted. Try again.")
        return {"ticket": target, "deleted": True, "text": "Removed. The ticket stays."}
    paused = (verb == "off") if verb != "toggle" else sched.get("paused") is not True
    if not orchcli.set_ext(root, t, by=by, paused=paused):
        raise Bad("The ticket changed or the change was not accepted. Try again.")
    return {"ticket": target, "paused": paused, "text": "Switched off." if paused else "Switched on."}


def review(root: Path, verb: str, target: str) -> dict:
    """What the person reads before a confirming click (`act <verb> --proof-target -- <ticket>`; changes nothing).
    allow-script: the script's command in full and a target ending in the entry's key; the click sends that key back
    as the value, so only what was shown is allowed. {"target": None, "review": None} for every other verb."""
    if verb != "allow-script":
        return {"target": None, "review": None}
    if not isinstance(target, str) or not TID.fullmatch(target):
        raise Bad("That is not a ticket id.")
    t = next((x for x in orchcli.tickets(root) if x["id"] == target), None)
    name = script_of(t)
    argv = scripts.load(root).get(name) if name else None
    if not argv:
        raise Bad("This repeat runs no script that is set up on this computer.")
    if scripts.approved(root, name, argv):
        raise Bad("This script is already allowed on this computer.")
    if not scripts.showable(argv):
        raise Bad(
            "That command cannot be shown safely (too long or odd characters), so it cannot be allowed."
        )
    return {
        "target": f"automation:{target}:{scripts.key(root, name, argv)}",
        "review": {
            "title": "Allow this script?",
            "value": scripts.shown(argv),
            "body": f"Each time the repeat is due, orch runs this command here, without a helper ({name}). "
            "If it changes, orch asks again.",
        },
    }
