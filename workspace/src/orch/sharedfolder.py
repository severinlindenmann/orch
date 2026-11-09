"""Who else is changing this folder: other alive runs that started in this one's folder.

A HINT, not a lock. It is computed from the run records in .orch/run/tickets when somebody looks, so a
run that starts a second later is not in it, and nothing is blocked or waited for. Liveness is
runs.state(), the one place that decides alive / dead / maybe-stale (a maybe-stale run has no pid to
look at and does not count). The start folder is the run record's `folder` (the workspace root today;
a copy's path once copies exist). A record without it was started in the root.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from orch import runs, tickets


def _folder(root: Path, rec: dict) -> Path:
    f = rec.get("folder")
    try:
        return Path(f if isinstance(f, str) and f else root).resolve()
    except (OSError, RuntimeError, ValueError):
        return root.resolve()


def alive_in(root: Path, where: Path, exclude_ticket: str | None = None) -> list[dict]:
    """Alive runs (any ticket but `exclude_ticket`) whose start folder is `where`."""
    where = where.resolve()
    out = []
    for f in sorted((runs.run_dir(root) / "tickets").glob("*.json")):
        if f.stem == exclude_ticket:
            continue
        rec = runs.read(root, f.stem)
        if not rec or runs.state(rec) != "alive" or _folder(root, rec) != where:
            continue
        title = f.stem
        with contextlib.suppress(Exception):
            title = tickets.load(root, f.stem).get("title") or f.stem
        out.append({"ticket": f.stem, "title": title, "agent": rec.get("agent") or "an agent"})
    return out


def others_in_folder(root: Path, ticket_id: str) -> list[dict]:
    """Other alive runs (any ticket) in this ticket's run folder: [{ticket, title, agent}], by ticket id.
    Empty when this ticket has no alive run of its own."""
    me = runs.read(root, ticket_id)
    if not me or runs.state(me) != "alive":
        return []
    return alive_in(root, _folder(root, me), ticket_id)


def line(others: list[dict]) -> str | None:
    """The one quiet line (draft 1a): the ticket's name when one, a count when several. None = say nothing."""
    if not others:
        return None
    if len(others) == 1:
        return f'"{others[0]["title"]}" is also changing this folder.'
    return f"{len(others)} other agents are also changing this folder."
