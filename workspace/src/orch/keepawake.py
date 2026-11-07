"""Keep this computer awake while a process runs. Generic: knows nothing about relay or phones.

macOS   caffeinate -dimsu -w <owner pid>             (ends by itself when the owner is gone)
Windows SetThreadExecutionState(CONTINUOUS|SYSTEM_REQUIRED) in the calling thread (standard user is fine)
Linux   systemd-inhibit --what=sleep:idle:handle-lid-switch ... tail --pid=<owner pid> -f /dev/null
        (ends by itself when the owner is gone)
none    acquire() returns None: the caller says "could not keep awake"

Only the child process this module started is ever stopped. Closing a laptop lid still sleeps macOS/Windows.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def command(platform: str, owner_pid: int, seconds: int, which=shutil.which) -> list[str] | None:
    """The helper command to run as a child on this platform, or None (Windows uses ctypes, no child)."""
    if platform == "darwin" and which("caffeinate"):
        return ["caffeinate", "-dimsu", "-w", str(owner_pid)]
    if platform.startswith("linux") and which("systemd-inhibit"):
        return [
            "systemd-inhibit",
            "--what=sleep:idle:handle-lid-switch",
            "--who=orch",
            "--why=Mobile mode",
            "--mode=block",
            "tail",
            f"--pid={owner_pid}",
            "-f",
            "/dev/null",
        ]
    return None


class Hold:
    """A running assertion. release() is safe to call twice."""

    def __init__(self, method: str, proc=None, win=None):
        self.method, self._proc, self._win = method, proc, win

    def alive(self) -> bool:
        return self._proc is None or self._proc.poll() is None

    def release(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()  # our own child only
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        win, self._win = self._win, None
        if win is not None:
            win(ES_CONTINUOUS)


def _windows_setter():
    import ctypes

    f = ctypes.windll.kernel32.SetThreadExecutionState
    return lambda flags: f(flags)


def acquire(
    seconds: int,
    owner_pid: int | None = None,
    platform: str | None = None,
    popen=subprocess.Popen,
    which=shutil.which,
    win=None,
) -> Hold | None:
    """Start holding the computer awake until released or the owner exits. None if unavailable.
    On Windows call it from the thread that stays alive (the assertion belongs to the thread)."""
    platform = platform or sys.platform
    owner_pid = owner_pid or os.getpid()
    if platform in ("win32", "cygwin"):
        try:
            setter = win or _windows_setter()
            if not setter(ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
                return None
            return Hold("SetThreadExecutionState", win=setter)
        except Exception:
            return None
    cmd = command(platform, owner_pid, seconds, which)
    if cmd is None:
        return None
    try:
        proc = popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    return Hold(cmd[0], proc=proc)
