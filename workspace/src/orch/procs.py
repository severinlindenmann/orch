"""Small process facts shared by the ticket lock and the run lock."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

_run = subprocess.run  # module-local seam: tests must not patch subprocess.run for other threads


def orch_python_argv(*args: str) -> list[str]:
    """argv that runs this orch again. Always `-I -P`: Python must not put the current folder on sys.path
    (and ignores PYTHON* variables), or a planted orch.py / json.py in a workspace would run as the user.
    Every `-m orch` spawn uses this."""
    return [sys.executable, "-I", "-P", "-m", "orch", *args]


def background_popen_kwargs() -> dict[str, int | bool]:
    """Start a background process without a visible Windows console; callers supply log streams.

    Windows: CREATE_NO_WINDOW gives the process a hidden console that its children inherit. Not
    DETACHED_PROCESS: Windows ignores CREATE_NO_WINDOW next to it, and a venv's python.exe is a launcher
    whose real-python child then allocates a NEW (visible) console, which is the stray terminal window."""
    if sys.platform == "win32":
        return {
            "creationflags": 0x00000200 | 0x08000000,  # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
            "stdin": subprocess.DEVNULL,
            "close_fds": True,
        }
    return {"start_new_session": True, "stdin": subprocess.DEVNULL}


def _win_processes() -> list[tuple[int, int, str]]:
    """(pid, parent pid, exe file name) of every process, from a Toolhelp snapshot (Windows only)."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    out: list[tuple[int, int, str]] = []
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        more = k32.Process32FirstW(snap, ctypes.byref(entry))
        while more:
            out.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            more = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return out


def _win_launcher_children(pid: int, table: list[tuple[int, int, str]]) -> list[int]:
    """The real-python child a venv launcher starts for itself: a direct child with the launcher's own image
    name (python.exe) and nothing else. Only when pid has exactly one such child; with more, which one is the
    launcher's is not certain and none is taken."""
    own = next((exe for p, _, exe in table if p == pid), None)
    if not own:
        return []
    same = [p for p, parent, exe in table if parent == pid and exe.lower() == own.lower()]
    return same if len(same) == 1 else []


def _win_taskkill(pid: int) -> None:
    _run(
        ["taskkill", "/PID", str(pid), "/F"],  # no /T: it would also end helpers the service started detached
        capture_output=True,
        timeout=5,
        check=True,
        creationflags=0x08000000,  # CREATE_NO_WINDOW
    )


def stop_tree(pid: int, *, verified: Callable[[], bool]) -> bool:
    """Stop only a recorded service, after its caller's full identity check.

    Windows: the service and the real-python child its venv launcher starts, never the rest of the tree
    (taskkill /T would end merge queue runners and helpers the service started, which must keep working).
    Never walk up to a parent (which may not be ours). POSIX retains single-pid SIGTERM.
    A taskkill failure is surfaced so callers keep the record for a later stop attempt.
    """
    if type(pid) is not int or pid <= 1 or not verified():
        return False
    if sys.platform == "win32":
        try:
            try:
                targets = [pid, *_win_launcher_children(pid, _win_processes())]
            except (OSError, ValueError, AttributeError):
                targets = [pid]  # no process list: the recorded pid alone
            for target in reversed(targets):  # the child first, so the launcher does not start another
                _win_taskkill(target)
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("The service could not be stopped. Try again in a moment.") from exc
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    return True


def wait_port_free(port: int, timeout: float = 5.0) -> bool:
    """Allow an exiting local server time to release its listening port before starting another."""
    end = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                pass
        except ConnectionRefusedError:
            return True
        except OSError:
            pass  # an inconclusive probe does not establish that the port is free
        remaining = end - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.1, remaining))


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
        try:
            r = subprocess.run(
                ["ps", "-o", "lstart=", "-p", str(pid)],
                capture_output=True,
                text=True,
                timeout=5,
                env={**os.environ, "LC_ALL": "C", "LANG": "C"},
            )
            text = " ".join(r.stdout.split())
        except (OSError, subprocess.SubprocessError):  # no ps here (minimal Linux container)
            text = ""
        if not text:
            return _proc_started(pid)  # Linux /proc; None elsewhere or when the process is gone
        return _iso(time.mktime(time.strptime(text, "%a %b %d %H:%M:%S %Y")))
    except Exception:
        return None


_btime: int | None = None
APPROX_SECONDS = 2  # start times of one pid compare within this (boot time drifts a second; ps has 1 s steps)


def _proc_started(pid: int) -> str | None:
    """Linux: start time from /proc (no ps, no locale: minimal containers have no procps), else None.
    Plain ISO like every stored start time; the boot time is read once per process so one process always
    sees one value."""
    global _btime
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        ticks = int(fields[19])  # field 22 (starttime), after pid and comm
        if _btime is None:
            with open("/proc/stat", encoding="utf-8") as f:
                _btime = next(int(line.split()[1]) for line in f if line.startswith("btime "))
        return _iso(_btime + ticks // os.sysconf("SC_CLK_TCK"))
    except (OSError, IndexError, ValueError, StopIteration, AttributeError):
        return None


def same_start(a: str, b: str) -> bool:
    """Two start times of one pid are the same process: equal within APPROX_SECONDS.
    (A reused pid that close in time would need a full pid wraparound within 2 s.)"""
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    if a == b:
        return True
    try:
        fa, fb = (datetime.strptime(x, "%Y-%m-%dT%H:%M:%SZ") for x in (a, b))
    except ValueError:
        return False
    return abs((fa - fb).total_seconds()) <= APPROX_SECONDS


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
    return bool(started and now and not same_start(now, started))
