"""Runtime files of a background process in .orch/run/<name>/ (gitignored). A repo can still force-add files there,
so nothing read from them is trusted alone: no symlinks are followed, a pid counts only when > 1, and the caller checks
the process's identity before it signals anything. (Same file in orch_dashboard and orch_automation.)"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def run_dir(root: Path, name: str) -> Path:
    """.orch/run/<name>/ (0700). Refused when .orch, .orch/run or the folder itself is a symlink."""
    orch, run = root / ".orch", root / ".orch" / "run"
    d = run / name
    for p in (orch, run, d):
        if p.is_symlink():
            raise RuntimeError(f"{p} is a symbolic link; orch does not use it. Remove it and try again.")
        if p is not orch:
            p.mkdir(mode=0o700, exist_ok=True)
        if not p.is_dir():
            raise RuntimeError(f"{p} is not a folder.")
    return d


def read_json(p: Path) -> dict | None:
    """The JSON object in p, or None (missing, a symlink, not a regular file, not JSON)."""
    if p.is_symlink():
        return None
    try:
        fd = os.open(p, os.O_RDONLY | NOFOLLOW)
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                return None
            data = json.loads(f.read(4096) or b"null")
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_json(p: Path, data: dict) -> None:
    """Atomic write: a new file in the same folder, then rename over p (a symlink at p is replaced, never followed)."""
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, p)


def open_append(p: Path):
    """Append to a log file; refuses a symlink."""
    if p.is_symlink():
        raise RuntimeError(f"{p} is a symbolic link; orch does not write to it.")
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND | NOFOLLOW, 0o600)
    return os.fdopen(fd, "a", encoding="utf-8")


def remove(p: Path) -> None:
    """Remove a runtime file (a symlink is removed itself, its target never touched)."""
    try:
        p.unlink()
    except OSError:
        pass


def valid_pid(pid: object) -> bool:
    return isinstance(pid, int) and not isinstance(pid, bool) and 1 < pid < 2**31


def alive(pid: object) -> bool:
    """True when pid > 1 names a running process. Never sends a real signal."""
    if not valid_pid(pid):
        return False
    if os.name == "nt":  # os.kill(pid, 0) would end the process; exit code 259 is not proof of life
        import ctypes

        k = ctypes.windll.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
        k.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
        k.WaitForSingleObject.restype = ctypes.c_ulong
        k.CloseHandle.argtypes = (ctypes.c_void_p,)
        h = k.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            return k.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def proc_start(pid: int) -> str | None:
    """When the process started (a stable id with the pid: a reused pid has another start time)."""
    if not valid_pid(pid):
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        k = ctypes.windll.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
        k.GetProcessTimes.argtypes = (ctypes.c_void_p, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
        k.CloseHandle.argtypes = (ctypes.c_void_p,)
        h = k.OpenProcess(0x1000, False, pid)
        if not h:
            return None
        try:
            t = [wintypes.FILETIME() for _ in range(4)]
            if not k.GetProcessTimes(h, *[ctypes.byref(x) for x in t]):
                return None
            return str((t[0].dwHighDateTime << 32) | t[0].dwLowDateTime)
        finally:
            k.CloseHandle(h)
    try:
        r = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None


def command(pid: int) -> str:
    """The command line of pid (POSIX, from ps); '' on Windows or when unknown."""
    if os.name == "nt":
        return ""
    try:
        r = subprocess.run(
            ["ps", "-ww", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip()


def runs_args(cmd: str, args: list[str]) -> bool:
    """True when the command line has exactly these arguments in a row (whole words: --dir /x/ws never
    matches --dir /x/ws2)."""
    s = " " + " ".join(args)
    return cmd.endswith(s) or (s + " ") in cmd
