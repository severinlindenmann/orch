"""Read-only facts for `orch focus view|needs`: which runs are alive here, and the ticket titles.

Runs: the claim records `.orch/run/tickets/<id>.json` (contracts/run.schema.json). Titles: one `orch ticket list --json`.
Nothing here writes anything or starts anything.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from . import actions, runfiles

TID = re.compile(r"t_[a-z0-9]{6,16}")
MAX_RECORD = 64 * 1024
STALE_SECONDS = (
    30 * 60
)  # same rule as core: a claim without a pid is 'maybe stale' after 30 min without an orch write


def _time(s) -> float | None:
    try:
        return datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return None


def _running(pid, started) -> bool:
    if not runfiles.valid_pid(pid) or not runfiles.alive(pid):
        return False
    return not (started and runfiles.proc_start(pid) not in (None, started))  # a reused pid is not the run


def alive(rec: dict, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    if isinstance(rec.get("pid"), int) or isinstance(rec.get("agent_pid"), int):
        return _running(rec.get("pid"), rec.get("pid_started")) or _running(
            rec.get("agent_pid"), rec.get("agent_pid_started")
        )
    seen = _time(rec.get("renewed_at"))
    return seen is not None and now - seen <= STALE_SECONDS


def records(root: Path) -> list[dict]:
    """The claim records of runs that are alive here (a bad, big or linked file is skipped)."""
    d = Path(root) / ".orch" / "run" / "tickets"
    out: list[dict] = []
    if d.is_symlink() or not d.is_dir():
        return out
    for f in sorted(d.glob("t_*.json"))[:200]:
        if not TID.fullmatch(f.stem) or f.is_symlink():
            continue
        try:
            fd = os.open(f, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as fh:
                rec = json.loads(fh.read(MAX_RECORD))
        except (OSError, ValueError, RecursionError):
            continue
        if (
            isinstance(rec, dict)
            and rec.get("ticket") == f.stem
            and isinstance(rec.get("run"), str)
            and alive(rec)
        ):
            out.append(rec)
    return out


def tickets(root: Path, orch_bin: str | None) -> dict[str, dict]:
    try:
        code, out, _ = actions.orch(Path(root), orch_bin, ["ticket", "list", "--all", "--json"], timeout=10)
        rows = json.loads(out) if code == 0 else []
    except (actions.Unavailable, ValueError, RecursionError):
        rows = []
    return {t["id"]: t for t in rows if isinstance(t, dict) and TID.fullmatch(str(t.get("id")))}


def title(t: dict | None) -> str:
    return (
        str((t or {}).get("title") or "A ticket").replace("<", "").replace(">", "").strip() or "A ticket"
    )[:200]
