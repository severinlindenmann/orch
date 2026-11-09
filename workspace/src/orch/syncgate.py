"""The core write gate `.orch/run/sync.gate`: held by the sync step while it applies a merge to the live tree.

Lock order is GATE -> ticket lock. A writer of synced files waits for the gate BEFORE it takes the ticket lock
and checks again after taking it (tickets._locked); the sync step, while holding the gate, takes each ticket's
lock for every file it writes (its own thread passes the gate). So a writer is either finished before the step
touches the file, or refused/waiting: nothing is written into a merge.

A gate is stale only when its holder is verifiably not a live sync step: the process is gone, the pid has
another start time, the pid is not an orch process, or no step record (`.orch/run/sync/step-<id>.json`,
written by `hold` for the same pid) backs it; an unreadable or garbled gate file is stale too (a live holder
publishes the file whole, so it never shows a partial one; a very recent empty one, from the no-links
fallback, still counts as live). Never a timer.

The sync step must do all its writes on the thread that holds the gate: a worker thread is another thread and
is refused like any writer.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import subprocess
import threading
import time
from pathlib import Path

from orch import procs
from orch.errors import Refused

WAIT_SECONDS = 30.0  # a writer waits this long, then says "busy" (it never breaks a live gate)
POLL_SECONDS = 0.02
FRESH_SECONDS = 2.0  # an unreadable gate younger than this may be a holder mid-write (no-links fallback)
REREAD_SECONDS = 0.05  # an unreadable gate is read once more after this, then counts as stale
REPLACE_TRIES = 10  # Windows: a file open elsewhere refuses os.replace; retried inside the gate
REPLACE_DELAY = 0.2

_NONCE = secrets.token_hex(8)  # per process (a forked child inherits it, but has another pid)
_STEP_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def gate_path(root: Path) -> Path:
    return root / ".orch" / "run" / "sync.gate"


def step_path(root: Path, step_id: str) -> Path:
    return root / ".orch" / "run" / "sync" / f"step-{step_id}.json"


def _read_file(p: Path) -> dict | None:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # Windows: PermissionError during a replace is an OSError too
        return None
    return data if isinstance(data, dict) else None


def _read(root: Path) -> dict | None:
    """The gate record, read once more after a short pause when it is unreadable. None = unreadable."""
    rec = _read_file(gate_path(root))
    if rec is None and gate_path(root).exists():
        time.sleep(REREAD_SECONDS)
        rec = _read_file(gate_path(root))
    return rec


def _is_me(rec: dict) -> bool:
    """This very thread of this process holds it (not just this process: other threads must not pass)."""
    return (
        rec.get("pid") == os.getpid()
        and rec.get("nonce") == _NONCE
        and rec.get("thread") == threading.get_ident()
    )


def _looks_like_orch(pid: int) -> bool:
    if os.name == "nt":
        return True  # no cheap command line here: the step record and the start time have to do
    try:
        r = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
    except Exception:
        return True  # cannot tell: do not call a holder stale on a guess about ps
    cmd = r.stdout.strip()
    if not cmd:
        return True
    toks = cmd.split()
    names = {"orch", "orch.exe"}
    if any(re.split(r"[\\/]", t)[-1] in names for t in toks):
        return True  # the orch program itself (tool script or pipx/uv shim)
    return any(a == "-m" and b.split(".")[0] == "orch" for a, b in zip(toks, toks[1:], strict=False))


def _stale(root: Path, rec: dict) -> bool:
    """True when no live sync step stands behind this record."""
    pid, sid = rec.get("pid"), rec.get("step_id")
    if not isinstance(pid, int) or not isinstance(sid, str) or not _STEP_RE.fullmatch(sid):
        return True
    start = rec.get("start_time")
    if not isinstance(start, str) or not start:
        return True
    if procs.owner_dead(f"{pid} {start}"):
        return True
    step = _read_file(step_path(root, sid))
    if step is None or step.get("pid") != pid:
        return True  # a gate with no step record is a fake or a leftover
    return not _looks_like_orch(pid)


def _fresh_unreadable(root: Path) -> bool:
    try:
        return time.time() - gate_path(root).stat().st_mtime < FRESH_SECONDS
    except OSError:
        return False


def live_holder(root: Path) -> dict | None:
    """The gate record when a live sync step of another thread/process holds it, else None."""
    if not gate_path(root).exists():
        return None
    rec = _read(root)
    if rec is None:
        return {"unreadable": True} if _fresh_unreadable(root) else None
    if _is_me(rec) or _stale(root, rec):
        return None
    return rec


def wait_clear(root: Path, what: str = "this", *, wait: float | None = None) -> None:
    """Return when no live gate is held; else after `wait` seconds raise Refused (busy). Writes nothing."""
    end = time.monotonic() + (WAIT_SECONDS if wait is None else wait)
    while live_holder(root) is not None:
        if time.monotonic() > end:
            raise busy(what)
        time.sleep(POLL_SECONDS)


def busy(what: str) -> Refused:
    return Refused(f"orch is syncing, so {what} is busy. Try again in a moment.")


def _write_whole(p: Path, text: str) -> None:
    fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def _publish(p: Path, text: str) -> bool:
    """Create the gate with its whole content; False when one exists. No reader sees a half file: write and
    fsync a temp file, then link it (atomic create-if-absent); no links on this filesystem: O_EXCL instead."""
    tmp = p.with_name(f"sync.gate.{secrets.token_hex(4)}.tmp")
    try:
        _write_whole(tmp, text)
        try:
            os.link(tmp, p)
            return True
        except FileExistsError:
            return False
        except OSError:
            try:
                _write_whole(p, text)
                return True
            except FileExistsError:
                return False
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


@contextlib.contextmanager
def hold(root: Path, step_id: str = "sync"):
    """The sync step's gate. Refused (busy) when another live step holds it; a stale gate is taken over.
    The step record has a name of its own per hold (id + random suffix), written before the gate is published
    (a gate without its record would look stale) and removed only by the hold that wrote it, so a refused
    second hold can never touch the live step's record."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,50}", step_id):
        raise Refused("A sync step id has 1 to 50 letters, digits, dots, dashes or underscores.")
    p = gate_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    me = os.getpid()
    sid = f"{step_id}-{secrets.token_hex(4)}"
    sp = step_path(root, sid)
    sp.parent.mkdir(parents=True, exist_ok=True)
    step_text = json.dumps({"pid": me, "step_id": sid})
    text = json.dumps(
        {
            "pid": me,
            "start_time": procs.pid_started(me) or "-",
            "nonce": _NONCE,
            "thread": threading.get_ident(),
            "step_id": sid,
        }
    )
    stmp = sp.with_name(f"{sp.name}.tmp")
    stmp.write_text(step_text, encoding="utf-8")
    os.replace(stmp, sp)  # atomic: a reader never sees half a record
    try:
        for _ in range(5):
            if _publish(p, text):
                break
            other = _read(root)
            if other is None:
                live = _fresh_unreadable(root)
            else:
                live = _is_me(other) or not _stale(root, other)
            if live:
                raise Refused("orch is already syncing. Try again in a moment.")
            _take_stale(root)
        else:
            raise Refused("orch could not take the sync gate. Try again in a moment.")
        try:
            yield
        finally:
            with contextlib.suppress(OSError):  # only a gate that is ours
                if p.read_text(encoding="utf-8") == text:
                    procs.unlink(p)
    finally:
        with contextlib.suppress(OSError):
            if sp.read_text(encoding="utf-8") == step_text:
                sp.unlink()


def _take_stale(root: Path) -> bool:
    """Remove a stale gate: rename it to a name only we know (atomic, one winner), re-check what we took,
    put it back (no clobber) if a live holder had made it meanwhile."""
    p = gate_path(root)
    mine = p.with_name(f"sync.gate.{secrets.token_hex(4)}.old")
    try:
        os.replace(p, mine)
    except OSError:
        return False
    try:
        rec = _read_file(mine)
        if rec is None:
            if time.time() - mine.stat().st_mtime >= FRESH_SECONDS:
                return True  # unreadable and not fresh: nobody is mid-write
        elif _stale(root, rec):
            return True
        with contextlib.suppress(OSError):
            os.link(mine, p)
        return False
    finally:
        with contextlib.suppress(OSError):
            mine.unlink()


def clear_stale(root: Path) -> bool:
    """For a doctor-style repair: remove a gate no live sync step stands behind. True when one was removed."""
    return gate_path(root).exists() and live_holder(root) is None and _take_stale(root)


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
