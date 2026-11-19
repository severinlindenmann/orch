"""Two default skill header fields that need more than one skill to act on (skill format, ORCH-531 step 5).

`metadata.review-by: "YYYY-MM-DD"`: when the date has passed, `orch skill review-due` (run by the automation loop,
no AI) opens one ticket "Look at the skill <name> again" for the skill's owner. One ticket per skill and date: what
was opened is kept in `.orch/skill-reviews.json`, so a new date later opens a new ticket and the same date never a
second one (also when an older date comes back). No helper is started on it; it waits on the list for a person. Only the workspace's own skills count:
orch's skills have no date, and a skill shared over the relay belongs to the admin's workspace, which gets the
reminder there.

`metadata.requires-skills: "a, b"`: `orch skill check` warns when a needed skill is not in this workspace (any
source counts: orch, add-on, workspace or relay). The relay asks for the needed skills when the admin shares a
skill (relay/src/admin.rs `assign`).
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from orch import net, relay, skillmeta, tickets
from orch.errors import Refused

BY = "orch"
STATE = "skill-reviews.json"
LOCK = "skill-reviews.lock"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _meta(entry: dict) -> dict:
    h = entry.get("header") if isinstance(entry, dict) else None
    m = h.get("metadata") if isinstance(h, dict) else None
    return m if isinstance(m, dict) else {}


def review_date(value: object) -> date | None:
    """The review-by date, or None when it is not written as YYYY-MM-DD (the check says so)."""
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def needed(entry: dict) -> list[str]:
    return skillmeta.split_list(_meta(entry).get("requires-skills") or "")


# ---- skill check (skillmeta.CHECKS: functions over the whole list of skills)


def check_needed_skills(entries: list[dict], root: Path | None = None) -> list[dict]:
    """A warning per needed skill that is not here. With root, every skill of the workspace counts (also when only
    some are checked); without it (folders checked by path) only the checked ones."""
    every = skillmeta.list_skills(root) if root is not None else entries
    have = {e.get("name") for e in [*every, *entries] if isinstance(e, dict)}
    out = []
    for e in entries:
        for n in needed(e):
            if n not in have:
                out.append(
                    {
                        "skill": e.get("name"),
                        "level": "warn",
                        "field": "metadata.requires-skills",
                        "message": f"needs the skill {n}, which is not in this workspace",
                    }
                )
    return out


def check_review_by(entries: list[dict], root: Path | None = None, today: date | None = None) -> list[dict]:
    """A warning for a review-by that is no date, and for one that has passed."""
    today = today or date.today()
    out = []
    for e in entries:
        raw = _meta(e).get("review-by")
        if raw is None:
            continue
        d = review_date(raw)
        if d is None:
            msg = f"review-by {raw!r} is not a date like 2027-03-01"
        elif d < today:
            msg = f"review-by {d.isoformat()} has passed: look at this skill again"
        else:
            continue
        out.append({"skill": e.get("name"), "level": "warn", "field": "metadata.review-by", "message": msg})
    return out


for _fn in (check_needed_skills, check_review_by):
    if _fn not in skillmeta.CHECKS:
        skillmeta.CHECKS.append(_fn)


# ---- review-by reminder (`orch skill review-due`)


def _path(root: Path) -> Path:
    return root / ".orch" / STATE


def _load(root: Path) -> dict:
    d = net.read_json(_path(root), {})
    return d if isinstance(d, dict) else {}


def _note(name: str, d: date, owner: str | None) -> str:
    who = f" Its owner is {owner}." if owner else ""
    return (
        f"The skill {name} asked to be looked at again by {d.isoformat()} (review-by in its header).{who}\n"
        "Check that it is still right and still used. Then write a new review-by date in its header, "
        'or set its status to "retired" when it is no longer needed.'
    )


def review_due(root: Path, *, today: date | None = None, dry_run: bool = False) -> dict:
    """One pass, no AI: a ticket for each workspace skill whose review-by date has passed and has no ticket yet.
    Returns {"opened": [{skill, date, ticket, key, title}], "waiting": [{skill, date}]} ("waiting" = not due)."""
    today = today or date.today()
    try:
        with relay.locked(root, wait=2.0, name=LOCK):  # one pass at a time: a date never makes two tickets
            return _pass(root, today, dry_run)
    except Refused as e:
        if "busy" in str(e):
            return {"busy": True, "opened": [], "waiting": []}
        raise


def _pass(root: Path, today: date, dry_run: bool) -> dict:
    state = _load(root)
    res: dict = {"opened": [], "waiting": []}
    for e in skillmeta.list_skills(root):
        if not isinstance(e, dict) or e.get("source") != "workspace":
            continue
        name, meta = e.get("name"), _meta(e)
        d = review_date(meta.get("review-by"))
        if not isinstance(name, str) or d is None:
            continue
        if d >= today:
            res["waiting"].append({"skill": name, "date": d.isoformat()})
            continue
        seen = state.get(name) if isinstance(state.get(name), dict) else {}
        if d.isoformat() in seen:
            continue  # this date has its ticket already
        owner = (meta.get("owner") or "").strip()[:64] or None
        title = f"Look at the skill {name} again"
        row = {"skill": name, "date": d.isoformat(), "title": title, "ticket": None, "key": None}
        if not dry_run:
            fields = {"note": _note(name, d, owner)}
            if owner:
                fields["owner"] = owner
            t = tickets.create(root, title, BY, fields=fields)
            state[name] = {**seen, d.isoformat(): t["id"]}  # every date that had a ticket: {date: ticket id}
            net.write_json(_path(root), state)  # saved right after the ticket: a date never makes two
            row.update(ticket=t["id"], key=t.get("key"))
        res["opened"].append(row)
    return res


def text(res: dict) -> str:
    if res.get("busy"):
        return "Another pass is running; nothing done."
    out = [f"Opened {r.get('key') or r.get('ticket') or '(dry run)'}: {r['title']}" for r in res["opened"]]
    return "\n".join(out) or "No skill is due for a look."


def dumps(res: dict) -> str:
    return json.dumps(res, indent=2, ensure_ascii=False)
