"""Shared fixtures for the diag query / checks / report tests: a workspace with a stuck ticket."""

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

from orch import diag, runs, tickets

SECRET = "sk-live-0123456789abcdef"


def dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def tree_hash(root: Path, skip=()) -> str:
    h = hashlib.sha256()
    base = root / ".orch"
    for dp, dn, fn in os.walk(base):
        dn[:] = sorted(d for d in dn if not (Path(dp) == base and d in skip))
        for f in sorted(fn):
            p = Path(dp) / f
            h.update(str(p.relative_to(base)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def stuck(proj: Path, minutes_ago: float = 30, title: str = "Write the invoice export") -> str:
    """A ticket that is Working, old, and has no run: what `settle_orphan` would flip to Ready."""
    (proj / ".orch").mkdir(exist_ok=True)
    t = tickets.create(proj, title, "human:t")
    tid = t["id"]
    tickets.set_status(proj, tid, "active", "human:t")
    raw = tickets.load(proj, tid)
    raw["updated_at"] = runs._iso(time.time() - minutes_ago * 60)
    tickets._write(proj, raw)
    return tid


def claim_dead(proj: Path, tid: str, minutes_ago: float = 30) -> dict:
    rec = runs._new_record(tid, "agent:claude", "claude", "oneshot", tickets.load(proj, tid), None, proj)
    rec["pid"] = dead_pid()
    rec["pid_started"] = "2020-01-01T00:00:00Z"
    ago = runs._iso(time.time() - minutes_ago * 60)
    rec["started_at"] = rec["renewed_at"] = ago
    runs._write(proj, rec)
    lock = runs.run_dir(proj) / "tickets" / f"{tid}.lock"
    lock.write_text(f"{rec['pid']} 2020-01-01T00:00:00Z", encoding="utf-8")
    return rec


def reset_diag(monkeypatch) -> None:
    monkeypatch.setattr(diag, "_state", {"root": None, "src": "cli", "seq": 0, "last_prune": None})
    for d in (diag._dropped, diag._rate, diag._enabled_cache, diag._hider_cache, diag._ws_cache):
        d.clear()
    diag._trace.set(None)
