"""The background service (`orch pull-requests start|stop|status`, run by `orch start`): the Merge when green
watcher. Every EVERY_SECS it runs switch.tend once. No AI call.

One watcher per workspace: it holds the lock folder `watch.lock` (owner = pid and start time, as the queue's
locks). stop signals only the pid in that lock while the lock still names it and that process is alive with the
recorded start time. The watcher ends by itself when the add-on is no longer on in this workspace.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from . import store

EVERY_SECS = 60
START_WAIT = 15.0


def _lock(root: Path) -> Path:
    return store.folder(root) / "watch.lock"


def _holder(root: Path) -> str:
    try:
        return (_lock(root) / "owner").read_text(encoding="utf-8")
    except OSError:
        return ""


def running_pid(root: Path) -> int | None:
    """The watcher's pid when one verifiably runs for this workspace."""
    from orch import procs

    holder = _holder(root)
    if not holder or procs.owner_dead(holder):
        return None
    try:
        return int(holder.split()[0])
    except (IndexError, ValueError):
        return None


def start(root: Path) -> int:
    root = root.resolve()
    pid = running_pid(root)
    if pid:
        return pid
    if not still_on(root):
        raise store.Refused(
            "The pull-requests add-on is not on here. Turn it on: orch addon add pull-requests"
        )
    from orch import procs

    d = store.folder(root)
    d.mkdir(parents=True, exist_ok=True)
    # -I -P: the workspace folder is never on the import path (a planted module there is not run)
    argv = [sys.executable, "-I", "-P", "-m", "orch_pull_requests", "watch", "--root", str(root)]
    with open(d / "watch.log", "a", encoding="utf-8") as log:
        proc = subprocess.Popen(argv, cwd=root, stdout=log, stderr=log, **procs.background_popen_kwargs())
    end = time.monotonic() + START_WAIT
    while time.monotonic() < end:
        pid = running_pid(root)
        if pid:
            return pid
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    if proc.poll() is None:
        proc.terminate()  # our own child (never a pid read from a file)
    raise store.Refused(
        "The Merge when green watcher did not start. See .orch/addons/pull-requests/watch.log"
    )


def stop(root: Path) -> bool:
    """True when a watcher was stopped, False when none ran."""
    from orch import procs

    root = root.resolve()
    holder = _holder(root)
    pid = running_pid(root)
    if pid is None:
        return False
    return procs.stop_tree(pid, verified=lambda: _holder(root) == holder and not procs.owner_dead(holder))


def still_on(root: Path) -> bool:
    from orch import addons

    try:
        return "pull-requests" in addons.active(root)
    except Exception:  # noqa: BLE001 - cannot tell right now: keep going, look again next round
        return True


def watch(root: Path, tend, sleep=time.sleep, rounds: int | None = None, log=print) -> int:
    """Hold the watcher lock and run tend() every EVERY_SECS until the add-on is turned off here (or `rounds`
    passes, for tests). Exit 0; 0 too when another watcher holds the lock."""
    root = root.resolve()
    lock = _lock(root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    if not store.take_lock(lock, store.STALE_SECS):
        log("The Merge when green watcher runs already.")
        return 0
    try:
        log(f"Merge when green watcher for {root.name} started (pid {os.getpid()}).")
        n = 0
        while (rounds is None or n < rounds) and (root / ".orch").is_dir() and still_on(root):
            n += 1
            try:
                tend()
            except Exception as e:  # noqa: BLE001 - one bad round never ends the watcher
                log(f"Merge when green: {e.__class__.__name__}: {str(e)[:200]}")
            if rounds is None or n < rounds:
                sleep(EVERY_SECS)
        return 0
    finally:
        store._drop_lock(lock)
