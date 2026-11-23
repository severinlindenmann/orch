"""`orch automation act <verb> <ticket> [--by <actor>]`: what the dashboard's switch and buttons do (one verb, one ticket).

Delete removes the whole ext.automation entry (orch ext unset) and keeps the ticket and its history: tickets are never deleted here.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from . import orchcli, scripts
from .cron import fmt, parse
from .loop import group_of, record_last_run, script_of, start_group, start_script
from .runner import update_state

VERBS = ("on", "off", "toggle", "run", "delete", "repeat", "copy", "allow-script", "limit", "quick")
KEY = re.compile(r"[0-9a-f]{64}")
TID = re.compile(r"t_[a-z0-9]{6,16}")


class Bad(Exception):
    """The request is not allowed or could not be done (plain words)."""


def _wake_up_used(root: Path, t: dict, result: str, by: str | None) -> None:
    """Start now on a one-time wake-up (a ticket wait, no ext.automation) is the wake-up itself: it runs now, so
    clear the wait (the planned time must not start it again), mark the ticket active like the loop does, log it,
    and remember the start for the row and Recent starts. Same steps as Scheduler.tend for a reached wait."""
    w = t.get("waiting_on") or {}
    until = parse(w.get("until")) if w.get("kind") == "time" else None
    if not until or result not in ("started", "pending"):
        return
    tid = t["id"]
    update_state(root, tid, last_wake=w.get("until"), last_run=fmt(datetime.now(UTC)))
    orchcli.call(root, "wait", tid, "--clear", by=by or True)
    if not script_of(t):
        orchcli.call(root, "ticket", "status", tid, "active", by=by or True)
    orchcli.log(root, tid, "Automation started the helper (Start now on a wake-up).")


def _saved(ok: bool, target: str, text: str) -> dict:
    if not ok:
        raise Bad("That could not be saved. Try again.")
    return {"ticket": target, "text": text}


def _run_now_helper(root: Path, t: dict, by: str | None, sched: dict) -> dict:
    """Run now on a helper: a repeat's run gets its number and the result lines, like a planned run."""
    from . import roles

    n = roles.next_number(root, t["id"]) if sched.get("recurring") is True else None
    r = orchcli.run_start(root, t["id"], text=("Run now." + roles.prompt(t["id"], n)) if n else None, by=by)
    if n and r.get("result") == "started":
        from .loop import time_limit

        roles.begin(root, t["id"], limit=time_limit(t))
    return r


def _write_fresh(root: Path, t: dict, write, tries: int = 3) -> bool:
    """Delete, on and off mean the same on any revision of the ticket: when a running helper wrote to the ticket
    between our read and our write (its revision moved, ORCH-1669), read it again and repeat the write, a few times.
    An entry that is gone by then counts as done (nothing left to delete or switch)."""
    for _ in range(tries):
        if write(t):
            return True
        t = orchcli.ticket(root, t["id"])
        if t is None:
            return False
        if not (t.get("ext") or {}).get("automation"):
            return True
    return False


def act(root: Path, verb: str, target: str, by: str | None = None, value: str | None = None) -> dict:
    if verb not in VERBS:
        raise Bad("That is not something automation can do.")
    if not isinstance(target, str) or not TID.fullmatch(target):
        raise Bad("That is not a ticket id.")
    if value is not None and verb not in ("repeat", "allow-script", "limit", "quick"):
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
        name = _to_allow(root, t)
        if not name:
            raise Bad("This repeat runs no script.")
        if not isinstance(value, str) or not KEY.fullmatch(value):
            raise Bad("Look at the command again.")
        try:
            scripts.allow(root, name, value)
        except scripts.ScriptError as e:
            raise Bad(str(e)) from None
        return {"ticket": target, "script": name, "allowed": True, "text": "Script allowed."}
    if verb == "limit":  # ORCH-827 Schedule: "Stops after N minutes" or no limit
        from .loop import TIME_LIMITS

        if sched.get("recurring") is not True:
            raise Bad("Only a repeat has a time limit.")
        if script_of(t) or "group" in sched:
            raise Bad("A repeat that runs a script has no time limit.")
        if value == "none":
            ok = orchcli.set_ext(root, t, remove=("time_limit",), by=by)
            return _saved(ok, target, "No time limit. It counts from the next run.")
        if not isinstance(value, str) or not value.isdigit() or int(value) not in TIME_LIMITS:
            raise Bad("The time limit is one of " + ", ".join(map(str, TIME_LIMITS)) + " minutes, or none.")
        ok = orchcli.set_ext(root, t, by=by, time_limit=int(value))
        return _saved(ok, target, f"Stops after {value} minutes from the next run.")
    if verb == "quick":  # ORCH-827 Schedule: Quick check first on or off (keeps the branch it watches)
        if value not in ("on", "off") or sched.get("recurring") is not True:
            raise Bad("Quick check is on or off, for a repeat.")
        if value == "off":
            if not sched.get("when_changed"):
                return {"ticket": target, "text": "Quick check is already off."}
            ok = orchcli.set_ext(
                root, t, remove=("when_changed",), by=by, when_changed_off=sched["when_changed"]
            )
            return _saved(ok, target, "Quick check off: every planned time starts a helper.")
        back = sched.get("when_changed") or sched.get("when_changed_off")
        if not back:
            raise Bad(
                "There is nothing to check yet. A helper sets what to watch with orch automation repeat --when-changed."
            )
        ok = orchcli.set_ext(root, t, remove=("when_changed_off",), by=by, when_changed=back)
        return _saved(ok, target, "Quick check on: a run with nothing new is skipped and costs nothing.")
    if verb == "run":
        group = group_of(t)
        name = script_of(t) or (", ".join(sorted(group)) if group else None)
        r = (
            start_group(root, t, sorted(group))
            if group
            else start_script(root, t, name)
            if name
            else _run_now_helper(root, t, by, sched)
        )
        if r["result"] == "failed":
            raise Bad(r["reason"])
        if sched:  # a manual run counts as the last run (same writer as the schedule); re-read: the run bumped the revision
            fresh = next((x for x in orchcli.tickets(root) if x["id"] == target), t)
            record_last_run(root, fresh, datetime.now(UTC), by=by)
        else:
            _wake_up_used(root, t, r["result"], by)
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
        if not _write_fresh(root, t, lambda x: orchcli.ext_unset(root, x, by=by)):
            raise Bad("The ticket changed or the change was not accepted. Try again.")
        return {"ticket": target, "deleted": True, "text": "Removed. The ticket stays."}
    paused = (verb == "off") if verb != "toggle" else sched.get("paused") is not True
    if verb == "toggle":  # the person flipped what they saw: a changed ticket asks them again
        ok = orchcli.set_ext(root, t, by=by, paused=paused)
    else:
        ok = _write_fresh(root, t, lambda x: orchcli.set_ext(root, x, by=by, paused=paused))
    if not ok:
        raise Bad("The ticket changed or the change was not accepted. Try again.")
    return {"ticket": target, "paused": paused, "text": "Switched off." if paused else "Switched on."}


def _to_allow(root: Path, t: dict | None) -> str | None:
    """The script an Allow click is about: the repeat's script, or the first script of its group not allowed yet."""
    from .view import waiting_script

    return (waiting_script(root, t) if group_of(t) else None) or script_of(t)


def review(root: Path, verb: str, target: str) -> dict:
    """What the person reads before a confirming click (`act <verb> --proof-target -- <ticket>`; changes nothing).
    allow-script: the script's command in full and a target ending in the entry's key; the click sends that key back
    as the value, so only what was shown is allowed. {"target": None, "review": None} for every other verb."""
    if verb != "allow-script":
        return {"target": None, "review": None}
    if not isinstance(target, str) or not TID.fullmatch(target):
        raise Bad("That is not a ticket id.")
    t = next((x for x in orchcli.tickets(root) if x["id"] == target), None)
    name = _to_allow(root, t)
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
