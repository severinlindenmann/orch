"""The guards that keep Prepare cheap and calm (ORCH-741, accepted draft ORCH-730 section 4).

A prepare-only run (Save without starting, ORCH-738) asks these first, with no AI call:
- the Settings switch `workflow.prepare_on_save` (on by default): off = the ticket stays as written;
- nothing is missing: title (not a placeholder), description, done-when and estimate are filled, as on tickets
  agents make (sub-tickets, Factory, automation); a sub-ticket a helper made is never prepared (no Prepare
  that splits again);
- once per ticket: a ticket that is Prepared is never prepared again (a repeated Save or delivery);
- a daily limit per workspace (`workflow.prepare_daily_limit`, rolling 24 hours, counted when a prepare run
  really starts). Reached: the ticket stays as saved with "Not prepared yet"; Start still works.

A person's later edit wins: `orch ticket tidy` fills only empty fields and keeps a title a person changed, a
prepare run may not change the ticket's status (tickets.set_status), and a Prepare result never touches a
ticket that is no longer in Backlog (tickets.set_prepare).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from orch import config, history

WINDOW = 24 * 3600
LIMIT_WHY = "today's limit for preparing tickets is reached"


def complete(ticket: dict) -> bool:
    """Every field Prepare fills is there already: nothing for a helper to do."""
    return bool(
        str(ticket.get("title") or "").strip()
        and not ticket.get("title_auto")
        and ticket.get("description")
        and ticket.get("done_when")
        and ticket.get("estimate")
    )


def made_by_agent(root: Path, ticket: dict) -> bool:
    """The ticket's first history line ("Created") was written by a helper, not a person."""
    try:
        lines = history.lines(root, ticket)
    except Exception:  # noqa: BLE001 - unknown counts as a person's ticket (it may be prepared)
        return False
    first = next((h for h in lines if str(h.get("text", "")).startswith("Created")), None)
    return bool(first) and str(first.get("by") or "").startswith("agent:")


def skip_reason(root: Path, ticket: dict) -> str | None:
    """Why this ticket gets no prepare run, decided by the program alone; None = prepare it. The ticket is not
    changed for any of these reasons (the limit is checked separately, when a run would really start)."""
    if not config.prepare_on_save_on(root):
        return "Prepare on Save is off in Settings"
    if complete(ticket):
        return "every field is filled already"
    if ticket.get("epic") is True:  # the person split it into its tickets already: nothing left to plan
        return "it is an epic with its tickets"
    if ticket.get("parent") and made_by_agent(root, ticket):
        return "a helper made this sub-ticket"
    p = ticket.get("prepare") if isinstance(ticket.get("prepare"), dict) else {}
    if p.get("state") == "prepared":
        return "it was prepared already"
    return None


def _path(root: Path) -> Path:
    return root / ".orch" / "run" / "prepare-starts.json"


def _starts(root: Path, now: float) -> list[float]:
    try:
        data = json.loads(_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    raw = data.get("starts") if isinstance(data, dict) else None
    return [x for x in raw or [] if isinstance(x, (int, float)) and 0 <= now - x < WINDOW]


def used(root: Path, now: float | None = None) -> dict:
    """{"used": prepare runs started in the last 24 hours, "limit": the daily limit} (Usage shows it)."""
    now = time.time() if now is None else now
    return {"used": len(_starts(root, now)), "limit": config.prepare_daily_limit(root)}


def take(root: Path, now: float | None = None) -> bool:
    """Count one prepare run against the daily limit; False (nothing counted) when the limit is reached."""
    from orch import runs

    now = time.time() if now is None else now
    with runs.locked(root, "prepare-limit"):
        starts = _starts(root, now)
        if len(starts) >= config.prepare_daily_limit(root):
            return False
        runs._atomic(_path(root), json.dumps({"starts": [*starts, now]}) + "\n")
    return True


def give_back(root: Path, at: float) -> None:
    """A counted run that never started (refused right after) does not use up the limit."""
    from orch import runs

    with runs.locked(root, "prepare-limit"):
        starts = _starts(root, time.time())
        if at in starts:
            starts.remove(at)
            runs._atomic(_path(root), json.dumps({"starts": starts}) + "\n")


def running_prepare(root: Path, tid: str) -> bool:
    """A prepare-only run works on this ticket right now."""
    from orch import runs

    try:
        rec = runs.read(root, tid)
        return bool(rec and rec.get("prepare") and runs.running(root, tid))
    except Exception:  # noqa: BLE001 - a guard reader never fails the caller
        return False
