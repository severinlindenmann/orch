"""The worked-time clock of one ticket: counts only the time the agent really worked.

Kept per ticket (not per run claim), so a new session claim does not reset it. Worked time grows while the
agent is working. It is advanced by every look at the ticket and by the server's own ticker (`active()` names the
tickets to look at), so it does not depend on a page being open. A gap between two looks longer than WORKED_GAP
(a sleeping laptop, a stopped server) counts as nothing. Paused time is the time between a stop and the next
start. One record per ticket in .orch/addons/focus/runs/clock-<ticket>.state.
"""

from __future__ import annotations

import math
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from . import runfiles
from .events import runs_dir

TID_RE = re.compile(r"t_[a-z0-9]{6,16}")
WORKED_GAP = 300  # seconds: a longer gap between two looks at a working ticket is not counted
STOP_GAP = 15  # the stop happened somewhere in the last look: count at most this much of it
PAUSE_MAX = 12 * 3600  # a pause longer than this is not added up
SEED_MAX = 6 * 3600  # a run first seen already running: count its age, up to this
SAVE_EVERY = 20.0


def _num(v) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0 else 0.0


def _age(iso: str | None, now: float) -> float:
    try:
        return now - datetime.fromisoformat(str(iso)).timestamp()
    except (ValueError, TypeError):
        return 0.0


class WorkClock:
    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.Lock()
        self.recs: dict[str, dict] = {}
        self.saved: dict[str, float] = {}

    def _file(self, tid: str) -> Path:
        # not under .orch/run: the page watches every .json there and would reload on each save
        return runs_dir(self.root) / f"clock-{tid}.state"

    def _load(self, tid: str) -> dict:
        rec = self.recs.get(tid)
        if rec is None:
            try:
                d = runfiles.read_json(self._file(tid)) or {}
            except (RuntimeError, OSError):
                d = {}
            first = d.get("first") if isinstance(d.get("first"), str) else None
            mode = d.get("mode") if d.get("mode") in ("worked", "paused") else None
            rec = {"worked": _num(d.get("worked")), "paused": _num(d.get("paused")), "first": first, "mode": mode,
                   "seen": _num(d.get("seen")), "since": _num(d.get("since"))}  # fmt: skip
            self.recs[tid] = rec
        return rec

    def active(self) -> list[str]:
        """Tickets whose clock is running now: the server's ticker looks at these."""
        with self.lock:
            return [t for t, r in self.recs.items() if r["mode"] == "worked"]

    def tick(self, tid: str, mode: str | None, first: str | None = None, now: float | None = None) -> dict:
        """Add the time since the last look and return {worked, paused, first} (seconds, seconds, ISO or None).
        mode: "worked" (agent working), "paused" (started, not working) or None (not started or done)."""
        if not TID_RE.fullmatch(tid):
            return {"worked": 0, "paused": 0, "first": None}
        t = time.time() if now is None else now
        with self.lock:
            rec = self._load(tid)
            fresh = rec["first"] is None and rec["mode"] is None
            delta = max(0.0, t - rec["seen"]) if rec["seen"] else 0.0
            if rec["mode"] == "worked" and delta <= WORKED_GAP:
                rec["worked"] += delta if mode == "worked" else min(delta, STOP_GAP)
            if mode == "worked" and rec["mode"] != "worked":
                if fresh and first:
                    rec["worked"] += min(max(0.0, _age(first, t)), SEED_MAX)  # first seen already running
                if rec["mode"] == "paused" and rec["since"] and t - rec["since"] <= PAUSE_MAX:
                    rec["paused"] += t - rec["since"]
            changed = mode != rec["mode"]
            if mode == "paused" and rec["mode"] != "paused":
                rec["since"] = t
            if mode and not rec["first"]:
                rec["first"] = first or datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                changed = True
            rec["mode"], rec["seen"] = mode, t
            paused = rec["paused"] + (t - rec["since"] if mode == "paused" and 0 <= t - rec["since"] <= PAUSE_MAX else 0)
            out = {"worked": int(rec["worked"]), "paused": int(paused), "first": rec["first"]}
            if changed or t - self.saved.get(tid, 0.0) >= SAVE_EVERY:
                self.saved[tid] = t
                try:
                    runfiles.write_json(self._file(tid), rec)
                except (RuntimeError, OSError):
                    pass
            if mode is None:  # not started or done: nothing to keep in memory (the file has it)
                self.recs.pop(tid, None)
                self.saved.pop(tid, None)
            return out
