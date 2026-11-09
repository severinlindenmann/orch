"""The core write gate `.orch/run/sync.gate`: held by the sync step while it applies a merge to the live tree.

Every writer of synced files (ticket lock, ticket counter, General ticket, attach, files/artifacts folders)
calls `wait_clear` and never writes past a live gate. A gate is stale only when its holder is verifiably gone
(pid dead, or the pid now has another start time): never a timer. The holder's own process passes.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import time
from pathlib import Path

from orch import procs
from orch.errors import Refused

WAIT_SECONDS = 30.0  # a writer waits this long, then says "busy" (it never breaks a live gate)
POLL_SECONDS = 0.02
REPLACE_TRIES = 10  # Windows: a file open elsewhere refuses os.replace; retried inside the gate
REPLACE_DELAY = 0.2


def gate_path(root: Path) -> Path:
    return root / ".orch" / "run" / "sync.gate"


def _read(root: Path) -> dict | None:
    try:
        data = json.loads(gate_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _holder_gone(rec: dict) -> bool:
    """True only when the process that wrote this gate is verifiably gone."""
    return procs.owner_dead(f"{rec.get('pid')} {rec.get('start_time') or '-'}")


def _is_me(rec: dict) -> bool:
    return rec.get("pid") == os.getpid() and rec.get("start_time") == (procs.pid_started(os.getpid()) or "-")


def live_holder(root: Path) -> dict | None:
    """The gate record when a live process other than this one holds it, else None (no gate, stale, or ours).
    An unreadable gate file counts as live (a holder may be mid-write): it is never ignored on a guess,
    except that a file that stays unreadable is the writer's `busy`, not a license to write."""
    p = gate_path(root)
    if not p.exists():
        return None
    rec = _read(root)
    if rec is None:
        return {"pid": None, "unreadable": True}
    if _is_me(rec) or _holder_gone(rec):
        return None
    return rec


def wait_clear(root: Path, what: str = "this", *, wait: float | None = None) -> None:
    """Return when no live gate is held; else after `wait` seconds raise Refused (busy). Writes nothing."""
    end = time.monotonic() + (WAIT_SECONDS if wait is None else wait)
    while live_holder(root) is not None:
        if time.monotonic() > end:
            raise Refused(f"orch is syncing, so {what} is busy. Try again in a moment.")
        time.sleep(POLL_SECONDS)


@contextlib.contextmanager
def hold(root: Path, step_id: str = ""):
    """The sync step's gate. Refused (busy) when another live process holds it; a stale gate is taken over."""
    p = gate_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    me = os.getpid()
    rec = json.dumps({"pid": me, "start_time": procs.pid_started(me) or "-", "step_id": step_id})
    while True:
        tmp = p.with_name(f"sync.gate.{secrets.token_hex(4)}.tmp")
        tmp.write_text(rec, encoding="utf-8")
        try:
            os.link(tmp, p)  # atomic create-if-absent with complete content: no reader sees a half gate
            break
        except FileExistsError:
            other = _read(root)
            if other is not None and not _is_me(other) and not _holder_gone(other):
                raise Refused("orch is already syncing. Try again in a moment.") from None
            if other is not None and _is_me(other):
                raise Refused("orch is already syncing in this process.") from None
            _take_stale(p)
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            procs.unlink(p)


def _take_stale(p: Path) -> None:
    """Remove a gate whose holder is gone: rename to a name only we know (atomic, one winner), re-check what
    we took, and put it back if a live holder had made it meanwhile."""
    mine = p.with_name(f"sync.gate.{secrets.token_hex(4)}.old")
    try:
        os.replace(p, mine)
    except OSError:
        return
    try:
        try:
            rec = json.loads(mine.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rec = None
        if isinstance(rec, dict) and _holder_gone(rec):
            return
        with contextlib.suppress(OSError):
            os.link(mine, p)  # live or unverifiable: no-clobber put-back
    finally:
        with contextlib.suppress(OSError):
            mine.unlink()


def replace(src, dst) -> None:
    """os.replace for the sync step: on Windows a file open elsewhere refuses it, so retry 10x / 200 ms,
    then raise (the caller skips the path and retries next tick)."""
    for i in range(REPLACE_TRIES):
        try:
            return os.replace(src, dst)
        except PermissionError:
            if os.name != "nt" or i == REPLACE_TRIES - 1:
                raise
            time.sleep(REPLACE_DELAY)
