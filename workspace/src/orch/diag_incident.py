"""Incident capture: freeze a small report BEFORE anything recovers or repairs (contracts/diag.md,
"Incidents").

Called in front of `runs.settle_orphan`, the start-failure path and the crash handlers. Structure only
(no content),
a short window, written to `.orch/diag/reports/i-...`. One incident per fingerprint per 15 minutes, at most 20
incidents / 50 MB. Never raises, never uploads, never repairs.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

from orch import diag

COOLDOWN_S = 15 * 60
WINDOW_S = 15 * 60
FAILURES_FOR_INCIDENT = 3
_STATE = "incidents.json"  # in .orch/diag/ (not a log file: the log's retention never touches it)
_KEEP = 200


def _path(root: Path) -> Path:
    return root / ".orch" / "diag" / _STATE


def _load(root: Path) -> dict:
    try:
        v = json.loads(_path(root).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(root: Path, state: dict) -> None:
    p = _path(root)
    if p.is_symlink() or p.parent.is_symlink():
        return
    state = dict(sorted(state.items(), key=lambda kv: -kv[1].get("at", 0))[:_KEEP])
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    try:
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, p)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def capture(
    root: Path | None, reason: str, *, fingerprint: str | None = None, ticket=None, run=None, now=None
) -> str | None:
    """The folder of the incident that was frozen now, else None (off, cooling down, or nothing could be
    made)."""
    try:
        if root is None or not diag.enabled(root):
            return None
        from orch import diag_report

        now = time.time() if now is None else now
        key = f"{reason}:{fingerprint or ticket or run or ''}"[:120]
        state = _load(root)
        if now - state.get(key, {}).get("at", 0) < COOLDOWN_S:
            return None
        state[key] = {"at": now}
        _save(root, state)  # first: a crash while making it must not make a storm
        made = diag_report.make(
            root,
            ticket=ticket,
            run=run,
            content=False,
            kind="i",
            now=now,
            window_s=WINDOW_S,
            timeline_cap=300,
        )
        diag.log("diag.incident", "warn", root=root, reason=reason, ref=made["ref"], ticket=ticket, run=run)
        return made["path"]
    except Exception:  # noqa: BLE001 - an incident that cannot be made never stops the work it was watching
        diag._drop("error")
        return None


def on_crash(root: Path | None, exc: BaseException, argv=()) -> str | None:
    """A command (or dashboard handler) is about to die of an unexpected exception."""
    try:
        fp = diag._err(exc)["fingerprint"]
    except Exception:  # noqa: BLE001
        fp = type(exc).__name__
    return capture(root, "crash", fingerprint=fp, ticket=os.environ.get("ORCH_TICKET") or None)


def note_failure(root: Path | None, what: str, *, ticket=None) -> str | None:
    """The same delivery failure again: the third time within the cooldown freezes an incident."""
    try:
        if root is None:
            return None
        now = time.time()
        key = f"failure:{what}"[:120]
        state = _load(root)
        rec = state.get(key) or {}
        n = (rec.get("n", 0) + 1) if now - rec.get("first", now) < COOLDOWN_S else 1
        state[key] = {"n": n, "first": rec.get("first", now) if n > 1 else now, "at": now}
        _save(root, state)
        if n >= FAILURES_FOR_INCIDENT:
            return capture(root, "delivery_failed", fingerprint=what, ticket=ticket, now=now)
    except Exception:  # noqa: BLE001
        diag._drop("error")
    return None


def on_problems(root: Path, checks: list[dict], *, ticket=None, run=None) -> str | None:
    """A check turned `problem`: freeze one incident named after the first problem."""
    bad = [c["name"] for c in checks if c["verdict"] == "problem"]
    return capture(root, "check_problem", fingerprint=bad[0], ticket=ticket, run=run) if bad else None
