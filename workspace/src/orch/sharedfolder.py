"""Who else is changing this folder: other alive runs that started in this one's folder.

A HINT, not a lock. It is computed from the run records in .orch/run/tickets when somebody looks, so a
run that starts a second later is not in it, and nothing is blocked or waited for. Liveness is
runs.state(), the one place that decides alive / dead / maybe-stale (a maybe-stale run has no pid to
look at and does not count). The start folder is the run record's `folder` (the workspace root today;
a copy's path once copies exist). A record without it was started in the root.
"""

from __future__ import annotations

import contextlib
import os
import unicodedata
from pathlib import Path

from orch import runs, tickets

TITLE_MAX = 60


def _key(p: Path) -> str:
    return os.path.normcase(str(p.resolve()))


def _folder(root: Path, rec: dict) -> str:
    """The record's start folder as a comparable key. Missing, relative or malformed = the root."""
    f = rec.get("folder")
    try:
        if isinstance(f, str) and f and "\0" not in f and os.path.isabs(f):
            return _key(Path(f))
    except (OSError, RuntimeError, ValueError):
        pass
    return _key(root)


def clean_title(title) -> str:
    """One short printable line: whitespace collapsed, control characters dropped, at most TITLE_MAX chars."""
    t = "".join(c for c in str(title or "") if unicodedata.category(c)[0] != "C" or c.isspace())
    t = " ".join(t.split())
    return t if len(t) <= TITLE_MAX else t[: TITLE_MAX - 1].rstrip() + "\u2026"


def alive_in(root: Path, folder: Path | str | None, exclude_ticket: str | None = None) -> list[dict]:
    """Alive runs (any ticket, but exclude_ticket) whose start folder is `folder` (None = the root):
    [{ticket, title, agent}], by ticket id. Non-ticket files and unreadable records are skipped one by one."""
    where = _key(Path(folder)) if folder else _key(root)
    out = []
    for f in sorted((runs.run_dir(root) / "tickets").glob("*.json")):
        if f.stem == exclude_ticket:
            continue
        try:
            rec = runs.read(root, f.stem)
            if not rec or runs.state(rec) != "alive" or _folder(root, rec) != where:
                continue
        except Exception:  # noqa: BLE001 - a stray or broken record must not break the page
            continue
        title = "another ticket"  # a deleted ticket: never a raw id
        with contextlib.suppress(Exception):
            title = clean_title(tickets.load(root, f.stem).get("title")) or title
        out.append({"ticket": f.stem, "title": title, "agent": str(rec.get("agent") or "an agent")[:32]})
    return out


def others_in_folder(root: Path, ticket_id: str) -> list[dict]:
    """Other alive runs (any ticket) in this ticket's run folder. Empty when this ticket has no alive run."""
    try:
        me = runs.read(root, ticket_id)
    except Exception:  # noqa: BLE001
        return []
    if not me or runs.state(me) != "alive":
        return []
    return alive_in(root, _folder(root, me), exclude_ticket=ticket_id)


def line(others: list[dict]) -> str | None:
    """The one quiet line (draft 1a): the ticket's name when one, a count when several. None = say nothing."""
    if not others:
        return None
    if len(others) == 1:
        return f'"{others[0]["title"]}" is also changing this folder.'
    return f"{len(others)} other agents are also changing this folder."
