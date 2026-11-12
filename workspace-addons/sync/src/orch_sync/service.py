"""Background process: `orch sync start|stop`, the automation shape. Runtime files in .orch/run/sync/ (never synced):
process.json {pid, nonce, started} written by the process itself, loop.log. A pid from there is signalled only when
the process with that pid started at the recorded moment and runs the orch_sync loop for this folder."""

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
NONCE = re.compile(r"[0-9a-f]{32}")


def read(root, relative):
    """A JSON object from .orch/<relative>, or {} (missing, a link on the way, not an object)."""
    try:
        p = repo.safe(root, relative)
        data = json.loads(p.read_bytes()) if p.is_file() else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _verified(root, rec):
    pid, started, nonce = rec.get("pid"), rec.get("started"), rec.get("nonce")
    if not (type(pid) is int and pid > 1 and isinstance(started, str) and started
            and isinstance(nonce, str) and NONCE.fullmatch(nonce)):
        return None
    if not services.pid_alive(pid) or not procs.same_start(procs.pid_started(pid) or "", started):
        return None
    if os.name != "nt":  # POSIX: it must also be our loop for this folder
        tail = f" -m orch_sync --dir {Path(root).resolve()} run"
        cmd = orchcli.command(pid)
        if not (cmd.endswith(tail) or tail + " " in cmd):
            return None
    return pid


def running_pid(root, clean=True):
    rec = read(root, RECORD)
    pid = _verified(root, rec) if rec else None
    if pid is None and rec and clean:
        repo.safe(root, RECORD).unlink(missing_ok=True)  # stale or not ours: rewritten on the next start
    return pid


def announce(root):
    """In the background process: record who we are (only when started by `start`, which passed a nonce)."""
    from .step import encoded, write

    nonce = os.environ.get(NONCE_ENV, "")
    if not NONCE.fullmatch(nonce):
        return None
    me = os.getpid()
    write(root, RECORD, encoded({"pid": me, "nonce": nonce, "started": procs.pid_started(me) or ""}))
    return nonce


def forget(root, nonce):
    """On exit: remove our record (only if it is still ours)."""
    rec = read(root, RECORD)
    if nonce and rec.get("nonce") == nonce and rec.get("pid") == os.getpid():
        repo.safe(root, RECORD).unlink(missing_ok=True)


def start(root):
    root = Path(root).resolve()
    pid = running_pid(root)
    if pid:
        return pid
    log = repo.local_dir(root) / "loop.log"
    nonce = secrets.token_hex(16)
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as out:
        env = {**os.environ, "ORCH_ROOT": str(root), NONCE_ENV: nonce}
        proc = orchcli.spawn(root, ["--dir", str(root), "run"], out, env)
    end = time.time() + 15
    while time.time() < end:
        rec = read(root, RECORD)
        if rec.get("nonce") == nonce and _verified(root, rec):
            return rec["pid"]
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    if proc.poll() is None:
        proc.terminate()  # our own child (never a pid read from a file)
    raise repo.Refused("Sync did not start. See .orch/run/sync/loop.log")


def stop(root):
    """ "stopped", "not running", or "not verified" (a record that is not our loop: nothing is signalled)."""
    rec = read(root, RECORD)
    if not rec:
        return "not running"
    done = procs.stop_tree(rec.get("pid"), verified=lambda: _verified(root, rec) is not None)
    repo.safe(root, RECORD).unlink(missing_ok=True)
    return "stopped" if done else "not verified"
