"""Read-only facts for `orch focus view|needs`: which runs are alive here, and the ticket titles.

Runs: the claim records `.orch/run/tickets/<id>.json` (contracts/run.schema.json). Titles: one `orch ticket list --json`.
Nothing here writes anything or starts anything.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
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


def _core_start(lstart: str) -> str | None:
    """`ps -o lstart=` text as core writes a process start in claim records: UTC, 2026-11-05T10:00:00Z."""
    try:
        return datetime.fromtimestamp(
            time.mktime(time.strptime(lstart, "%a %b %d %H:%M:%S %Y")), UTC
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError):
        return None


def _running(pid, started) -> bool:
    if not runfiles.valid_pid(pid) or not runfiles.alive(pid):
        return False
    now = runfiles.proc_start(pid)
    # a reused pid is not the run; the record holds core's UTC form, ps prints local text: compare in core's form
    return not (started and now not in (None, started) and _core_start(now) != started)


def alive(rec: dict, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    if isinstance(rec.get("pid"), int) or isinstance(rec.get("agent_pid"), int):
        return _running(rec.get("pid"), rec.get("pid_started")) or _running(
            rec.get("agent_pid"), rec.get("agent_pid_started")
        )
    seen = _time(rec.get("renewed_at"))
    return seen is not None and now - seen <= STALE_SECONDS


def _is_general(root: Path, tid: str) -> bool:
    """The hidden General ticket of the phone conversation is not shown in Focus."""
    try:
        t = json.loads((Path(root) / ".orch" / "tickets" / f"{tid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(t, dict) and t.get("general") is True


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
            and not _is_general(root, f.stem)
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
