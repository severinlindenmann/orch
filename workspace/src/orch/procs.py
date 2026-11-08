"""Small process facts shared by the ticket lock and the run lock."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path


def orch_python_argv(*args: str) -> list[str]:
    """argv that runs this orch again. Always `-P`: Python must not put the current folder on sys.path,
    or a planted orch.py / json.py in a workspace would run as the user. Every `-m orch` spawn uses this."""
    return [sys.executable, "-P", "-m", "orch", *args]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def pid_started(pid: int) -> str | None:
    """Start time of a process as the OS reports it (guards against pid reuse), else None."""
    if not isinstance(pid, int) or pid <= 1:
        return None
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            k = ctypes.windll.kernel32
            k.OpenProcess.restype = wintypes.HANDLE
            h = k.OpenProcess(0x1000, False, pid)
            if not h:
                return None
            try:
                c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
                if not k.GetProcessTimes(h, *(ctypes.byref(x) for x in (c, e, kt, ut))):
                    return None
                ticks = (c.dwHighDateTime << 32) | c.dwLowDateTime
                return _iso(ticks / 1e7 - 11644473600)
            finally:
                k.CloseHandle(h)
        r = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
        text = " ".join(r.stdout.split())
        if not text:
            return None
        return _iso(time.mktime(time.strptime(text, "%a %b %d %H:%M:%S %Y")))
    except Exception:
        return None


# Windows refuses to replace or delete a file another process has open (Python opens files without
# FILE_SHARE_DELETE), and our small JSON files are read lock-free all the time. That refusal is
# momentary, so it is waited out here, in the one place every replace/delete of such a file goes through.
_FILE_BUSY = os.name == "nt"
FILE_BUSY_SECONDS = 5.0


def replace(src, dst) -> None:
    """os.replace that waits out a reader holding the target open (Windows only)."""
    _wait_free(lambda: os.replace(src, dst))


def unlink(path) -> None:
    """Path.unlink(missing_ok=True) that waits out a reader holding the file open (Windows only)."""
    _wait_free(lambda: Path(path).unlink(missing_ok=True))


def _wait_free(op) -> None:
    end = time.monotonic() + FILE_BUSY_SECONDS
    while True:
        try:
            return op()
        except PermissionError:
            if not _FILE_BUSY or time.monotonic() > end:
                raise
            time.sleep(0.005)


_tokens: dict[int, str] = {}


def own_token() -> str:
    """What a lock file holds: our pid and start time, so a reused pid is not mistaken for the holder.
    Cached per pid, so a forked child does not claim its parent's token."""
    pid = os.getpid()
    if pid not in _tokens:
        _tokens[pid] = f"{pid} {pid_started(pid) or '-'}"
    return _tokens[pid]


def owner_dead(text: str) -> bool:
    """True only when the lock's holder is verifiably gone (pid dead, or the pid now has another start time).
    Anything we cannot read or verify counts as alive: never two holders."""
    from orch import services

    parts = text.split()
    try:
        pid = int(parts[0])
    except (IndexError, ValueError):
        return False
    if not services.pid_alive(pid):
        return True
    started = parts[1] if len(parts) > 1 and parts[1] != "-" else None
    now = pid_started(pid) if started else None
    return bool(started and now and now != started)
