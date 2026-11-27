"""`orch changes --since <date|tag>`: release notes from the tickets (read-only).

A view over existing tickets, no new object: every ticket that became Done since a date or a git tag, with its
title and the web links in its evidence, grouped by kind (`orch ticket kind`). When a ticket was done is the
time of the newest history line that moved it to Done (the file's last change when it has none)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from orch import history, safegit, tickets
from orch.errors import Refused

NO_KIND = "Kind not set"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_TAG = re.compile(r"^[\w][\w./+-]{0,199}$")


def since_time(root: Path, text: str) -> str:
    """A date or time (local without an offset) or a git tag of the workspace -> UTC RFC 3339 ending in Z."""
    text = (text or "").strip()
    if _DATE.match(text):
        return tickets.parse_time(text)
    if _TAG.match(text) and ".." not in text:
        rc, out, _ = safegit.run(
            ["log", "-1", "--format=%cI", f"refs/tags/{text}", "--"], root, 10, read_only=True, root=root
        )
        if rc == 0 and out.strip():
            return tickets.parse_time(out.strip().splitlines()[0])
    raise Refused(
        f"'{text}' is neither a date nor a git tag here. Use a date like 2026-11-01 or a tag from `git tag`."
    )


def done_at(root: Path, t: dict) -> str:
    from orch.worktrees import _DONE_LINE  # the one pattern for "this line moved the ticket to Done"

    for h in reversed(history.lines(root, t)):
        if (
            isinstance(h, dict)
            and _DONE_LINE.fullmatch(str(h.get("text", "")))
            and isinstance(h.get("at"), str)
        ):
            return h["at"]
    return str(t.get("updated_at") or t.get("created_at") or "")


def _urls(t: dict) -> list[str]:
    out: list[str] = []
    for item in t.get("checklist") or []:
        for ev in (item.get("evidence") or []) if isinstance(item, dict) else []:
            ref = ev.get("ref") if isinstance(ev, dict) else None
            if isinstance(ref, str) and ref.startswith(("https://", "http://")) and ref not in out:
                out.append(ref)
    return out


def _at(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def collect(root: Path, since: str) -> dict:
    start = _at(tickets.parse_time(since))
    groups: dict[str | None, list[dict]] = {}
    for t in tickets.list_all(root):
        if t.get("status") != "done":
            continue
        when = done_at(root, t)
        at = _at(when) if when else None
        if at is None or at < start:
            continue
        row = {
            "id": t["id"],
            "key": t.get("key"),
            "title": t.get("title", ""),
            "done_at": when,
            "urls": _urls(t),
        }
        groups.setdefault(tickets.kind(t), []).append(row)
    order = [*tickets.KINDS, None]
    out = []
    for k in order:
        rows = sorted(groups.get(k, []), key=lambda r: r["done_at"])
        if rows:
            out.append({"kind": k, "label": tickets.KINDS.get(k, NO_KIND), "tickets": rows})
    return {"since": since, "count": sum(len(g["tickets"]) for g in out), "groups": out}


def text(data: dict, asked: str) -> str:
    if not data["count"]:
        return f"No tickets were done since {asked}."
    n = data["count"]
    lines = [f"Changes since {asked} ({n} {'ticket' if n == 1 else 'tickets'})"]
    for g in data["groups"]:
        lines += ["", g["label"]]
        for r in g["tickets"]:
            lines.append(f"- {r['key'] or r['id']}  {r['title']}")
            lines += [f"  {u}" for u in r["urls"]]
    return "\n".join(lines)
