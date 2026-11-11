"""Stdlib-only console entry guard; never import orch until its reinstall finishes."""

import os
import stat
import sys
import time
from pathlib import Path

MAX_AGE = 900


def real_home() -> Path:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        a = ctypes.WinDLL("advapi32", use_last_error=True)
        u = ctypes.WinDLL("userenv", use_last_error=True)
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        a.OpenProcessToken.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
        u.GetUserProfileDirectoryW.argtypes = [
            ctypes.c_void_p,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        token = ctypes.c_void_p()
        if not a.OpenProcessToken(k.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise OSError("could not locate the account profile")
        try:
            size = wintypes.DWORD()
            u.GetUserProfileDirectoryW(token, None, ctypes.byref(size))
            if not 0 < size.value <= 32768:
                raise OSError("could not locate the account profile")
            buf = ctypes.create_unicode_buffer(size.value)
            if not u.GetUserProfileDirectoryW(token, buf, ctypes.byref(size)):
                raise OSError("could not locate the account profile")
            return Path(buf.value)
        finally:
            k.CloseHandle(token)
    try:
        import pwd

        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, KeyError):
        return Path.home()


def marker_path(home: Path) -> Path:
    return home / "finish.updating"


def home_candidates() -> list[Path]:
    # Check both: orch may reject an untrusted ORCH_HOME and use the account home.
    env = os.environ.get("ORCH_HOME")
    return [*([Path(env).resolve()] if env else []), (real_home() / ".orch-tool").resolve()]


def alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = ctypes.c_void_p
        k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = k.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # access denied does not mean dead
        try:
            code = wintypes.DWORD()
            return not k.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            k.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        pass
    return True


def updating(home: Path) -> bool:
    mark = marker_path(home)
    try:
        before = mark.lstat()
        if not stat.S_ISREG(before.st_mode):
            return False
        flags = os.O_RDONLY
        if sys.platform != "win32":
            flags |= os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(mark, flags)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ):
                return False
            if not 0 <= time.time() - opened.st_mtime < MAX_AGE:
                return False
            data = os.read(fd, 64)
        finally:
            os.close(fd)
        if len(data) == 64 or not data.strip().isdigit():
            return False
        pid = int(data.strip())
        return 1 < pid <= 0xFFFFFFFF and alive(pid)
    except (OSError, ValueError, OverflowError):
        return False


def main():
    if any(updating(home) for home in home_candidates()):
        print("orch is still updating, try again in a moment.", file=sys.stderr)
        return 3
    from orch.cli import main as cli_main

    return cli_main()
