"""Small process facts shared by the ticket lock and the run lock."""

from __future__ import annotations

import functools
import os
import subprocess
import time
from datetime import UTC, datetime


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


@functools.cache
def own_token() -> str:
    """What a lock file holds: our pid and start time, so a reused pid is not mistaken for the holder."""
    return f"{os.getpid()} {pid_started(os.getpid()) or '-'}"


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
