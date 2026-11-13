"""Background process: `orch factory start|stop|status`. Runtime files in .orch/run/factory/ (gitignored):
factory.json {pid, nonce, started} written by the process itself, factory.log. A pid from there is signalled only
when the process with that pid started at the recorded moment and runs orch_factory watch for this folder."""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

from . import runfiles
from .runfiles import alive, valid_pid

NONCE_ENV = "ORCH_FACTORY_NONCE"
RECORD = "factory.json"
LOCK = "start.lock"


def _dir(root: Path) -> Path:
    return runfiles.run_dir(root, "factory")


def _verified(root: Path, rec: dict | None) -> int | None:
    if not rec:
        return None
    pid, started, nonce = rec.get("pid"), rec.get("started"), rec.get("nonce")
    if not (
        valid_pid(pid)
        and isinstance(started, str)
        and started
        and isinstance(nonce, str)
        and re.fullmatch(r"[0-9a-f]{32}", nonce)
    ):
        return None
    if not alive(pid) or runfiles.proc_start(pid) != started:
        return None
    if os.name != "nt":  # POSIX: it must also be our command for this folder
        cmd = runfiles.command(pid)
        if not runfiles.runs_args(cmd, ["-m", "orch_factory", "--dir", str(root.resolve()), "watch"]):
            return None
    return pid


def running_pid(root: Path, clean: bool = True) -> int | None:
    """The verified pid of the watcher, or None. `clean=False`: never creates or removes a file (cheap, for the view)."""
    if clean:
        try:
            d = _dir(root)
        except RuntimeError:
            return None
    else:
        d = Path(root) / ".orch" / "run" / "factory"
    pid = _verified(root, runfiles.read_json(d / RECORD))
    if pid is None and clean:
        runfiles.remove(d / RECORD)  # stale or not ours: ignored, rewritten on the next start
    return pid


def announce(root: Path) -> str | None:
    """In the background process: record who we are (only when started by `start`, which passed a nonce)."""
    nonce = os.environ.get(NONCE_ENV, "")
    if not re.fullmatch(r"[0-9a-f]{32}", nonce):
        return None
    me = os.getpid()
    d = _dir(root)
    other = _verified(root, runfiles.read_json(d / RECORD))
    if other is not None and other != me:
        raise RuntimeError("A Factory watcher is already running for this workspace.")
    runfiles.write_json(d / RECORD, {"pid": me, "nonce": nonce, "started": runfiles.proc_start(me) or ""})
    return nonce


def forget(root: Path, nonce: str | None) -> None:
    """On exit: remove our record (only if it is still ours)."""
    if not nonce:
        return
    p = _dir(root) / RECORD
    rec = runfiles.read_json(p)
    if rec and rec.get("nonce") == nonce and rec.get("pid") == os.getpid():
        runfiles.remove(p)


@contextlib.contextmanager
def _start_lock(d: Path, wait: float):
    """Exclusive lock on start.lock (never follows a link, regular file only) for the pid check plus spawn."""
    p = d / LOCK
    if p.is_symlink():
        raise RuntimeError(f"{p} is a symbolic link; orch does not use it.")
    fd = os.open(p, os.O_RDWR | os.O_CREAT | runfiles.NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RuntimeError(f"{p} is not a regular file.")
        end = time.time() + wait
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() >= end:
                    raise RuntimeError(
                        "Another start of the Factory watcher is in progress. Try again."
                    ) from None
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)  # closing releases the lock


def start(root: Path, wait: float = 20) -> int:
    root = Path(root).resolve()
    d = _dir(root)
    with _start_lock(d, wait):
        pid = running_pid(root)  # a start that held the lock before us may have finished: use its watcher
        if pid:
            return pid
        return _spawn(root, d)


def _spawn(root: Path, d: Path) -> int:
    nonce = secrets.token_hex(16)
    # -P: the workspace folder is never on the import path (a planted orch_factory.py there is not run)
    with runfiles.open_append(d / "factory.log") as out:
        proc = subprocess.Popen(
            [sys.executable, "-P", "-m", "orch_factory", "--dir", str(root), "watch"],
            cwd=root,
            stdout=out,
            stderr=subprocess.STDOUT,
            env={**os.environ, "ORCH_ROOT": str(root), NONCE_ENV: nonce},
            start_new_session=True,
            stdin=subprocess.DEVNULL,
        )
    end = time.time() + 15
    while time.time() < end:
        rec = runfiles.read_json(d / RECORD)
        if rec and rec.get("nonce") == nonce and _verified(root, rec):
            return rec["pid"]
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    if proc.poll() is None:
        proc.terminate()  # our own child (never a pid read from a file)
    raise RuntimeError("The Factory watcher did not start. See .orch/run/factory/factory.log")


def stop(root: Path) -> str:
    """'stopped', 'not running', or 'not verified' (a record that is not our watcher: nothing is signalled)."""
    root = Path(root).resolve()
    try:
        d = _dir(root)
    except RuntimeError:
        return "not verified"
    rec = runfiles.read_json(d / RECORD)
    if not rec:
        return "not running"
    pid = _verified(root, rec)
    if pid is None:
        runfiles.remove(d / RECORD)
        return "not verified"
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    end = time.time() + 2  # let it go first: its own cleanup removes the record, and a new start sees it gone
    while alive(pid) and time.time() < end:
        time.sleep(0.05)
    runfiles.remove(d / RECORD)
    return "stopped"
