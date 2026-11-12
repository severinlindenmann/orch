"""Stdlib-only console entry guard; never import orch until its reinstall finishes."""

import os
import stat
import sys
import time
from pathlib import Path

# above humanproof.UPDATE_TIMEOUT (1800 s): a long reinstall stays protected; a dead owner clears it sooner
MAX_AGE = 2100


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


def strict() -> bool:
    """ORCH_HOME_STRICT (anything but empty or 0), the same test as orch.addons.home()."""
    return os.environ.get("ORCH_HOME_STRICT", "") not in ("", "0")


def home_candidates() -> list[Path]:
    """ORCH_HOME (when a usable folder), then the account's ~/.orch-tool. With ORCH_HOME set and strict
    (tests, e2e lanes), only ORCH_HOME: the real home is never looked at (empty if ORCH_HOME is bad)."""
    homes = []
    env = os.environ.get("ORCH_HOME")
    if env:
        try:
            home = Path(env).resolve()
            info = home.stat()
            # Detect replacements independently of core's rules for choosing a home.
            if stat.S_ISDIR(info.st_mode) and (sys.platform == "win32" or info.st_uid == os.getuid()):
                homes.append(home)
        except (OSError, ValueError, RuntimeError):
            pass
    if env and strict():
        return homes
    return [*homes, (real_home() / ".orch-tool").resolve()]


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
        if sys.platform != "win32" and before.st_uid != os.getuid():
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
            if sys.platform != "win32" and opened.st_uid != os.getuid():
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


def is_record_hook(argv: list[str]) -> bool:
    """`orch record [flags] hook ...`: a tool's hook call, which must end with exit 0 whatever happens (only
    --strict refuses). The first word after `record` that is not a flag (nor the value of `--by`) is `hook`.
    A global flag before `record` (`orch --json record hook`) or another flag that takes a value before `hook`
    is not seen here: that form goes to the parser. Stdlib only: checked before orch is imported. The same
    rule as orch.is_record_hook (a copy, never an import of orch; tests/test_record_hook.py checks they
    agree)."""
    if argv[:1] != ["record"]:
        return False
    rest = iter(argv[1:])
    for word in rest:
        if word == "--by":
            next(rest, None)
        elif not word.startswith("-"):
            return word == "hook"
    return False


def _record_hook(argv: list[str]) -> int:
    """The console script's `orch record hook`: a watchdog (exit 0 after 4 s) runs before orch is imported,
    and whatever fails (an update in progress, a broken install, an import that hangs or raises, a SystemExit)
    ends with nothing on stdout, at most one stderr line and exit 0 (2 only with --strict): a tool's hook exit
    2 would block the tool call. orch.cli replaces the watchdog with its own before it writes anything."""
    import threading

    dog = threading.Timer(4.0, lambda: os._exit(0))
    dog.daemon = True
    dog.start()
    try:
        if any(updating(home) for home in home_candidates()):
            raise RuntimeError("orch is still updating")  # never import a half-installed orch
        from orch.cli import main as cli_main

        return cli_main(argv, watchdog=dog)
    except BaseException:  # noqa: BLE001 - a tool's hook
        code = 2 if "--strict" in argv else 0
        try:
            sys.stderr.write(("Refused: " if code else "orch: ") + "nothing was recorded.\n")
        except BaseException:  # noqa: BLE001 - not even a closed stderr may change the exit code
            pass
        return code
    finally:
        dog.cancel()


def main():
    argv = sys.argv[1:]
    if is_record_hook(argv):
        return _record_hook(argv)
    if any(updating(home) for home in home_candidates()):
        print("orch is still updating, try again in a moment.", file=sys.stderr)
        return 3
    from orch.cli import main as cli_main

    return cli_main()
