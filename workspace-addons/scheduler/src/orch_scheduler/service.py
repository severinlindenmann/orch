"""Background process: `orch scheduler start|stop`. Runtime files in .orch/run/scheduler/ (gitignored):
scheduler.json {pid, nonce, started} written by the process itself, scheduler.log. A pid from there is signalled only
when the process with that pid started at the recorded moment and runs orch_scheduler for this folder."""
from __future__ import annotations

import os
import re
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import runfiles
from .runfiles import alive, valid_pid

NONCE_ENV = "ORCH_SCHEDULER_NONCE"


def _dir(root: Path) -> Path:
    return runfiles.run_dir(root, "scheduler")


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
        r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None


def _command(pid: int) -> str:
    if os.name == "nt":
        return ""
    try:
        r = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip()


def _verified(root: Path, rec: dict | None) -> int | None:
    if not rec:
        return None
    pid, started, nonce = rec.get("pid"), rec.get("started"), rec.get("nonce")
    if not (valid_pid(pid) and isinstance(started, str) and started and isinstance(nonce, str)
            and re.fullmatch(r"[0-9a-f]{32}", nonce)):
        return None
    if not alive(pid) or proc_start(pid) != started:
        return None
    if os.name != "nt":  # POSIX: it must also be our command for this folder
        cmd = _command(pid)
        if "orch_scheduler" not in cmd or str(root) not in cmd:
            return None
    return pid


def running_pid(root: Path, clean: bool = True) -> int | None:
    try:
        d = _dir(root)
    except RuntimeError:
        return None
    pid = _verified(root, runfiles.read_json(d / "scheduler.json"))
    if pid is None and clean:
        runfiles.remove(d / "scheduler.json")  # stale or not ours: ignored, rewritten on the next start
    return pid


def announce(root: Path) -> str | None:
    """In the background process: record who we are (only when started by `start`, which passed a nonce)."""
    nonce = os.environ.get(NONCE_ENV, "")
    if not re.fullmatch(r"[0-9a-f]{32}", nonce):
        return None
    me = os.getpid()
    runfiles.write_json(_dir(root) / "scheduler.json", {"pid": me, "nonce": nonce, "started": proc_start(me) or ""})
    return nonce


def forget(root: Path, nonce: str | None) -> None:
    """On exit: remove our record (only if it is still ours)."""
    if not nonce:
        return
    p = _dir(root) / "scheduler.json"
    rec = runfiles.read_json(p)
    if rec and rec.get("nonce") == nonce and rec.get("pid") == os.getpid():
        runfiles.remove(p)


def start(root: Path) -> int:
    pid = running_pid(root)
    if pid:
        return pid
    d = _dir(root)
    root = root.resolve()
    nonce = secrets.token_hex(16)
    # -P: the workspace folder is never on the import path (a planted orch_scheduler.py there is not run)
    kw = {"creationflags": 0x00000208} if os.name == "nt" else {"start_new_session": True}
    with runfiles.open_append(d / "scheduler.log") as out:
        proc = subprocess.Popen([sys.executable, "-P", "-m", "orch_scheduler", "--dir", str(root), "run"], cwd=root,
                                stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env={**os.environ, NONCE_ENV: nonce}, **kw)
    end = time.time() + 15
    while time.time() < end:
        rec = runfiles.read_json(d / "scheduler.json")
        if rec and rec.get("nonce") == nonce and _verified(root, rec):
            return rec["pid"]
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    if proc.poll() is None:
        proc.terminate()  # our own child (never a pid read from a file)
    raise RuntimeError("The scheduler did not start. See .orch/run/scheduler/scheduler.log")


def stop(root: Path) -> str:
    """"stopped", "not running", or "not verified" (a pid file that is not our scheduler: nothing is signalled)."""
    try:
        had = runfiles.read_json(_dir(root) / "scheduler.json") is not None
    except RuntimeError:
        return "not verified"
    pid = running_pid(root)
    if not pid:
        return "not verified" if had else "not running"
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    runfiles.remove(_dir(root) / "scheduler.json")
    return "stopped"
