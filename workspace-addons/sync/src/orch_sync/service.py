"""Background process: `orch sync start|stop`, the automation shape. Runtime files in .orch/run/sync/ (never synced):
loop.lock, which the loop holds for its whole life (the one proof that a loop runs: one loop per folder, a second one
ends at once); process.json {pid, nonce, started}, written by the loop after it took the lock; stop, the request to
end after the current pass; loop.log. A pid from process.json is signalled only while the lock is held and that pid
is alive with the recorded start time. The same rule on every OS (fcntl.flock on POSIX, msvcrt.locking on Windows)."""

import json
import os
import re
import secrets
import time
from pathlib import Path

from orch import procs, services

from . import orchcli, repo

NONCE_ENV = "ORCH_SYNC_NONCE"
RECORD = "run/sync/process.json"
LOCK = "run/sync/loop.lock"
STOP = "run/sync/stop"  # `orch sync stop` asks: the loop finishes its pass and ends
LOG = "run/sync/loop.log"
LOG_CAP = 1_000_000  # bytes: a longer loop.log starts empty on the next `orch sync start`
NONCE = re.compile(r"[0-9a-f]{32}")
TAKE = 2.0  # seconds a new loop tries for the lock (a status check holds it for a moment)
STOP_WAIT = 120.0  # seconds stop waits for the pass to finish (a fetch and a push may take 60 s each)


def read(root, relative):
    """A JSON object from .orch/<relative>, or {} (missing, a link on the way, not an object)."""
    try:
        p = repo.safe(root, relative)
        data = json.loads(p.read_bytes()) if p.is_file() else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _open_lock(root, create=False):
    if create:
        repo.local_dir(root)
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | (os.O_CREAT if create else 0)
    return os.open(repo.safe(root, LOCK), flags, 0o600)


def _take(fd):
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _release(fd):
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    finally:
        os.close(fd)  # POSIX: closing the file gives the lock back


def lock_held(root):
    """Does a process hold the loop lock? Probed by taking it and giving it back at once."""
    try:
        fd = _open_lock(root)
    except (OSError, ValueError):
        return False  # no lock file (never started) or a link on the way
    if _take(fd):
        _release(fd)
        return False
    os.close(fd)
    return True


def _verified(root, rec):
    """The recorded pid when the loop lock is held and that pid is alive with the recorded start time, else None."""
    pid, started, nonce = rec.get("pid"), rec.get("started"), rec.get("nonce")
    if not (type(pid) is int and pid > 1 and isinstance(started, str) and started
            and isinstance(nonce, str) and NONCE.fullmatch(nonce)):
        return None
    if not lock_held(root) or not services.pid_alive(pid):
        return None
    return pid if procs.same_start(procs.pid_started(pid) or "", started) else None


def running_pid(root):
    rec = read(root, RECORD)
    return _verified(root, rec) if rec else None


def _drop(root, rec):
    """Remove a stale record, only while no loop holds the lock and the file is still the one that was read
    (a new loop writes its own record right after it took the lock)."""
    if not lock_held(root) and read(root, RECORD) == rec:
        repo.safe(root, RECORD).unlink(missing_ok=True)


def announce(root):
    """In the loop process: take the lock for the life of the process, then record who we are. Returns
    (lock, nonce), or None when another loop holds the lock. The nonce comes from `start` (so it knows its child);
    a foreground `orch sync run` makes its own, so status and stop see it too."""
    nonce = os.environ.pop(NONCE_ENV, "")  # never inherited by git or orch
    fd = _open_lock(root, create=True)
    end = time.monotonic() + TAKE
    while not _take(fd):
        if time.monotonic() >= end:
            os.close(fd)
            return None
        time.sleep(0.05)
    try:
        from .step import encoded, write

        nonce = nonce if NONCE.fullmatch(nonce) else secrets.token_hex(16)
        repo.safe(root, STOP).unlink(missing_ok=True)  # an old request was not for this loop
        me = os.getpid()
        write(root, RECORD, encoded({"pid": me, "nonce": nonce, "started": procs.pid_started(me) or ""}))
    except BaseException:
        _release(fd)
        raise
    return fd, nonce


def forget(root, held):
    """On exit: remove our record (only if it is still ours), then give the lock back."""
    fd, nonce = held
    try:
        rec = read(root, RECORD)
        if rec.get("nonce") == nonce and rec.get("pid") == os.getpid():
            repo.safe(root, RECORD).unlink(missing_ok=True)
    finally:
        _release(fd)


def _log(root):
    """loop.log for appending; over LOG_CAP it starts empty."""
    repo.local_dir(root)
    p = repo.safe(root, LOG)
    try:
        big = p.lstat().st_size > LOG_CAP
    except FileNotFoundError:
        big = False
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0) | (os.O_TRUNC if big else 0)
    return os.fdopen(os.open(p, flags, 0o600), "a", encoding="utf-8")


def start(root, wait=15.0):
    """The pid of the loop for this folder: the running one, or a new one once it holds the lock."""
    root = Path(root).resolve()
    pid = running_pid(root)
    if pid:
        return pid
    nonce = secrets.token_hex(16)
    env = {**os.environ, "ORCH_ROOT": str(root), NONCE_ENV: nonce}
    with _log(root) as out:
        proc = orchcli.spawn(["--dir", str(root), "run"], out, env)
    end = time.monotonic() + wait
    died = None
    while time.monotonic() < end:
        rec = read(root, RECORD)
        if rec.get("nonce") == nonce and _verified(root, rec):
            return rec["pid"]
        if proc.poll() is not None:
            if pid := running_pid(root):
                return pid  # our child found the lock taken: another start (or a foreground run) won
            died = died or time.monotonic()
            if time.monotonic() - died > 3.0:  # gone, and no other loop showed up in time: don't wait the rest
                break
        time.sleep(0.1)
    if proc.poll() is None:
        proc.terminate()  # our own child (never a pid read from a file)
    raise repo.Refused("Sync did not start. See .orch/run/sync/loop.log")


def stop(root, wait=STOP_WAIT):
    """ "stopped", "still running", "not running" (no record, or its pid is gone), or "not verified" (a live
    process that is not our loop). The loop is ASKED to end after its pass (the stop file it polls); nothing is
    ever signalled or killed: a pid comes from a file an agent can write, so it never decides what gets a signal.
    If the loop has not ended after `wait` seconds (a long pass), the answer is "still running"; the stop file
    stays, so the loop still ends after its pass."""
    rec = read(root, RECORD)
    if not rec:
        return "not running"
    pid = _verified(root, rec)
    if pid is None:
        named = rec.get("pid")
        alive = type(named) is int and services.pid_alive(named)
        _drop(root, rec)
        return "not verified" if alive else "not running"
    from .step import write

    write(root, STOP, b"")
    end = time.monotonic() + wait
    while _verified(root, rec) == pid:
        if time.monotonic() >= end:
            return "still running"  # the stop file stays: it ends after its pass
        time.sleep(0.1)
    repo.safe(root, STOP).unlink(missing_ok=True)
    _drop(root, rec)
    return "stopped"
