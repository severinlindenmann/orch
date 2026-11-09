"""The worked-time clock of one ticket: counts only the time the agent really worked.

Kept per ticket (not per run claim), so a new session claim does not reset it. Worked time grows while the
agent is working; paused time grows (a little per look) while a started ticket waits. It is counted from what
this server sees, one record per ticket in .orch/run/focus/clock-<ticket>.json.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from pathlib import Path

from . import runfiles

TID_RE = re.compile(r"t_[a-z0-9]{6,16}")
WORKED_GAP = 6 * 3600  # a gap longer than this between two looks at a still-working ticket is not counted
PAUSED_GAP = 30  # a pause counts at most this much per look: a closed page does not add days
SAVE_EVERY = 20.0


class WorkClock:
    def __init__(self, root: Path):
        self.root = root
        self.recs: dict[str, dict] = {}
        self.saved: dict[str, float] = {}

    def _file(self, tid: str) -> Path:
        return runfiles.run_dir(self.root, "focus") / f"clock-{tid}.json"

    def _load(self, tid: str) -> dict:
        rec = self.recs.get(tid)
        if rec is None:
            try:
                d = runfiles.read_json(self._file(tid)) or {}
            except RuntimeError:
                d = {}
            num = lambda k: float(d[k]) if isinstance(d.get(k), (int, float)) and d[k] >= 0 else 0.0
            first = d.get("first") if isinstance(d.get("first"), str) else None
            mode = d.get("mode") if d.get("mode") in ("worked", "paused") else None
            rec = {"worked": num("worked"), "paused": num("paused"), "first": first, "mode": mode, "seen": num("seen")}
            self.recs[tid] = rec
        return rec

    def tick(self, tid: str, mode: str | None, first: str | None = None, now: float | None = None) -> dict:
        """Add the time since the last look and return {worked, paused, first} (seconds, seconds, ISO or None).
        mode: "worked" (agent working), "paused" (started, not working) or None (not started or done)."""
        if not TID_RE.fullmatch(tid):
            return {"worked": 0, "paused": 0, "first": None}
        t = time.time() if now is None else now
        rec = self._load(tid)
        delta = max(0.0, t - rec["seen"]) if rec["seen"] else 0.0
        if rec["mode"] == "worked":
            rec["worked"] += min(delta, WORKED_GAP if mode == "worked" else PAUSED_GAP)
        elif rec["mode"] == "paused":
            rec["paused"] += min(delta, PAUSED_GAP)
        changed = mode != rec["mode"]
        if mode and not rec["first"]:
            rec["first"] = first or datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            changed = True
        rec["mode"], rec["seen"] = mode, t
        if changed or t - self.saved.get(tid, 0.0) >= SAVE_EVERY:
            self.saved[tid] = t
            try:
                runfiles.write_json(self._file(tid), rec)
            except (RuntimeError, OSError):
                pass
        return {"worked": int(rec["worked"]), "paused": int(rec["paused"]), "first": rec["first"]}
