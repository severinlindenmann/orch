"""Runtime files of a background process in .orch/run/<name>/ (gitignored). A repo can still force-add files there,
so nothing read from them is trusted alone: no symlinks are followed, a pid counts only when > 1, and the caller checks
the process's identity before it signals anything. (Same file in orch_dashboard and orch_scheduler.)"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
WINDOWS = os.name == "nt"


def run_dir(root: Path, name: str) -> Path:
    """.orch/run/<name>/ (0700). Refused when .orch, .orch/run or the folder itself is a symlink."""
    orch, run = root / ".orch", root / ".orch" / "run"
    d = run / name
    for p in (orch, run, d):
        if p.is_symlink():
            raise RuntimeError(f"{p} is a symbolic link; orch does not use it. Remove it and try again.")
        if p is not orch:
            mkdir_private(p)
        if not p.is_dir():
            raise RuntimeError(f"{p} is not a folder.")
    return d


def user_sid() -> str | None:
    """The SID string of the user this process runs as (Windows, from the process token); None elsewhere."""
    if not WINDOWS:
        return None
    import ctypes
    from ctypes import wintypes

    k, adv = ctypes.WinDLL("kernel32"), ctypes.WinDLL("advapi32")
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.LocalFree.argtypes = (ctypes.c_void_p,)
    k.CloseHandle.argtypes = (ctypes.c_void_p,)
    adv.OpenProcessToken.argtypes = (ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))
    adv.GetTokenInformation.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    adv.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    tok = ctypes.c_void_p()
    if not adv.OpenProcessToken(k.GetCurrentProcess(), 0x8, ctypes.byref(tok)):  # TOKEN_QUERY
        return None
    try:
        n = wintypes.DWORD()
        adv.GetTokenInformation(
            tok, 1, None, 0, ctypes.byref(n)
        )  # 1 = TokenUser; the first call gives the size
        buf = ctypes.create_string_buffer(n.value)
        if not adv.GetTokenInformation(tok, 1, buf, n, ctypes.byref(n)):
            return None
        sid = ctypes.c_void_p.from_buffer(buf).value  # TOKEN_USER starts with the SID pointer
        out = ctypes.c_void_p()
        if not sid or not adv.ConvertSidToStringSidW(sid, ctypes.byref(out)):
            return None
        try:
            return ctypes.wstring_at(out.value)
        finally:
            k.LocalFree(out)
    finally:
        k.CloseHandle(tok)


def grant_user(d: Path) -> None:
    """Windows: mkdir(mode=0o700) gives only OWNER RIGHTS, SYSTEM and Administrators. A folder made by an elevated
    process is owned by Administrators, so the same user without elevation is locked out. Also grant the current
    user (inheritable); nobody else (not Users, not Everyone). Best effort: a standard user does not need it."""
    sid = user_sid()
    if not sid:
        return
    icacls = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "icacls.exe"
    try:
        subprocess.run(
            [str(icacls), str(d), "/grant", f"*{sid}:(OI)(CI)F"], capture_output=True, timeout=20, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def mkdir_private(p: Path) -> bool:
    """Create p as 0700 when it is missing; True only when this call created it (an existing folder is not touched)."""
    try:
        p.mkdir(mode=0o700)
    except FileExistsError:
        return False
    if WINDOWS:
        grant_user(p)
    return True


def _denied(p: Path, e: PermissionError) -> RuntimeError:
    if not WINDOWS:
        return RuntimeError(f"{p.parent} is not writable: {e}")
    return RuntimeError(
        f"{p.parent} was made by orch running as administrator. Run the same command once in an administrator "
        f"window, or delete the .orch\\run\\{p.parent.name} folder there."
    )


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
    try:
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
    except PermissionError as e:
        raise _denied(p, e) from e
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, p)


def open_append(p: Path):
    """Append to a log file; refuses a symlink."""
    if p.is_symlink():
        raise RuntimeError(f"{p} is a symbolic link; orch does not write to it.")
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND | NOFOLLOW, 0o600)
    except PermissionError as e:
        raise _denied(p, e) from e
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
