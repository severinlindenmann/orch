"""Earlier sessions of one ticket for the Focus pane's History tab (read-only; orch lists them).

`orch run history <ticket> --json` gives the ticket's remembered sessions (the last 10, orch.tickets.SESSIONS_KEPT);
this keeps only the fields the page shows, each checked, so nothing else of the tool's files reaches the page.
Reopening one is the `session.reopen` action (actions.py: `orch run start <ticket> --session <id>`).
"""

from __future__ import annotations

import re
from pathlib import Path

from .data import run_orch

SID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
MAX_ROWS = 20


def _s(v, n: int) -> str:
    return " ".join(v.split())[:n] if isinstance(v, str) else ""


def listing(root: Path, orch_bin: str | None, tid: str) -> dict:
    """{"available": bool, "sessions": [{id, label, last_used, title, turns, current, reopenable}]}, newest first."""
    d = run_orch(orch_bin, ["run", "history", tid, "--json"], root, timeout=15.0)
    rows = d.get("sessions") if isinstance(d, dict) else None
    if not isinstance(rows, list):
        return {"available": False, "sessions": []}
    out = []
    for r in rows[:MAX_ROWS]:
        if not isinstance(r, dict) or not isinstance(r.get("id"), str) or not SID.fullmatch(r["id"]):
            continue
        turns = r.get("turns")
        out.append(
            {
                "id": r["id"],
                "label": _s(r.get("label"), 40),
                "last_used": _s(r.get("last_used"), 40),
                "title": _s(r.get("title"), 100),
                "turns": turns
                if isinstance(turns, int) and not isinstance(turns, bool) and turns >= 0
                else 0,
                "current": r.get("current") is True,
                "reopenable": r.get("reopenable") is True,
            }
        )
    return {"available": True, "sessions": out}
