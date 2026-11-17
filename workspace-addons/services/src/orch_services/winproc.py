"""Process helpers for the Windows driver and its keeper, with plain fallbacks so the tests run on every computer.

A process is named by its pid AND its start time: a pid alone can belong to another program later. Never
os.kill(pid, 0) on Windows: there it ends the process instead of asking about it."""

from __future__ import annotations

import os
import signal
import sys

WIN = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000
STILL_ACTIVE = 259

if WIN:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    _k32.GetProcessTimes.argtypes = (wintypes.HANDLE, *(ctypes.POINTER(wintypes.FILETIME),) * 4)
    _k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _k32.GetCurrentProcess.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    _k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    _k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)

    QUERY = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
    TERMINATE = 0x0001

    class _Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _Extended(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _Basic),
            ("IoInfo", ctypes.c_uint64 * 6),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


def _start_of(h) -> int | None:  # pragma: no cover - Windows only
    """Start time of the process behind an open handle, or None when it has ended."""
    code = wintypes.DWORD()
    if not _k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != STILL_ACTIVE:
        return None
    t = [wintypes.FILETIME() for _ in range(4)]
    if not _k32.GetProcessTimes(h, *(ctypes.byref(x) for x in t)):
        return None
    return (t[0].dwHighDateTime << 32) | t[0].dwLowDateTime


def started(pid: int) -> int | None:
    """A number for when the process started (same process = same number), or None when it is not running."""
    if type(pid) is not int or pid <= 0:
        return None
    if not WIN:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except PermissionError:
            pass
        return _posix_start(pid)
    h = _k32.OpenProcess(QUERY, False, pid)  # pragma: no cover - Windows only
    if not h:  # pragma: no cover
        return None
    try:  # pragma: no cover
        return _start_of(h)
    finally:  # pragma: no cover
        _k32.CloseHandle(h)


def _posix_start(pid: int) -> int:
    """Linux: the start tick from /proc; elsewhere 1 (alive is all the tests need there)."""
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as f:
            return int(f.read().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return 1


def is_same(pid: object, start: object) -> bool:
    return type(pid) is int and type(start) is int and started(pid) == start


def end(pid: object, start: object) -> bool:
    """End this one process, only when it is still the one that started at `start`. True when it was ended.
    Windows: the check and the end go through one handle, so a pid used again in between is never hit."""
    if type(pid) is not int or type(start) is not int or pid <= 0:
        return False
    if not WIN:
        if started(pid) != start:
            return False
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return False
        return True
    h = _k32.OpenProcess(TERMINATE | QUERY, False, pid)  # pragma: no cover - Windows only
    if not h:  # pragma: no cover
        return False
    try:  # pragma: no cover
        return _start_of(h) == start and bool(_k32.TerminateProcess(h, 1))
    finally:  # pragma: no cover
        _k32.CloseHandle(h)


def keep_children_with_me() -> None:
    """Windows: put this process in a job that ends every process it starts when this one ends (also when it is
    ended from outside). Elsewhere nothing: there the driver ends the program itself."""
    if not WIN:
        return
    job = _k32.CreateJobObjectW(None, None)  # pragma: no cover - Windows only
    if not job:  # pragma: no cover
        return
    info = _Extended()  # pragma: no cover
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if _k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):  # pragma: no cover
        _k32.AssignProcessToJobObject(job, _k32.GetCurrentProcess())
    # the handle stays open on purpose: it closes when this process ends, and that ends the children
