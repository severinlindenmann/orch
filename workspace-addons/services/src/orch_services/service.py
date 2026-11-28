"""The regular check (`orch services start|stop|status` without a service id, run by `orch start` and when the
add-on is turned on): one background process that runs `orch services check` every EVERY_SECS, so a service that
keeps stopping is noticed without anyone setting up a repeat. No AI call.

One checker per workspace: it holds the lock folder `checker.lock` (owner = pid and start time). stop signals only
the pid in that lock while the lock still names it and that process is alive with the recorded start time. The
checker ends by itself when Services is no longer on in this workspace.

Every check pass (the checker's and a person's `orch services check`) holds `check.lock`, so two passes never run at
the same time and never ask the same question twice.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from . import store
from .store import Refused

EVERY_SECS = 60
START_WAIT = 15.0
CHECK_WAIT = 30.0  # a person's check waits this long for the checker's pass to finish
STALE_SECS = 30.0  # a lock folder this old with no owner file is stale


def _checker_lock(root: Path) -> Path:
    return store.base_dir(root) / "checker.lock"


def _check_lock(root: Path) -> Path:
    return store.base_dir(root) / "check.lock"


def log_path(root: Path) -> Path:
    return store.base_dir(root) / "checker.log"


def _holder(lock: Path) -> str:
    try:
        return (lock / "owner").read_text(encoding="utf-8")
    except OSError:
        return ""


def _drop_lock(lock: Path) -> None:
    with contextlib.suppress(OSError):
        (lock / "owner").unlink()
    with contextlib.suppress(OSError):
        lock.rmdir()


def take_lock(lock: Path) -> bool:
    """Make the lock folder; True when ours. A lock whose owner is verifiably gone (or one with no owner file older
    than STALE_SECS) is moved aside first, by one atomic rename: only one taker wins."""
    from orch import procs

    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock.mkdir()
    except FileExistsError:
        holder = _holder(lock)
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            return False
        dead = procs.owner_dead(holder) if holder else age > STALE_SECS
        if not dead:
            return False
        aside = lock.with_name(f"{lock.name}.stale-{os.getpid()}-{time.monotonic_ns()}")
        try:
            lock.rename(aside)
        except OSError:
            return False  # someone else moved it first
        if _holder(aside) != holder:  # a new owner took it between our look and the rename: give it back
            if not lock.exists():
                with contextlib.suppress(OSError):
                    aside.rename(lock)
            return False
        _drop_lock(aside)
        try:
            lock.mkdir()
        except FileExistsError:
            return False
    (lock / "owner").write_text(procs.own_token(), encoding="utf-8")
    return True


@contextlib.contextmanager
def check_pass(root: Path, wait: float = CHECK_WAIT, sleep=time.sleep):
    """Hold the check lock for one pass; refused when another pass still runs after `wait` seconds."""
    lock = _check_lock(root)
    end = time.monotonic() + wait
    while not take_lock(lock):
        if time.monotonic() >= end:
            raise Refused("Another check runs right now. Try again in a minute.")
        sleep(0.2)
    try:
        yield
    finally:
        _drop_lock(lock)


def running_pid(root: Path) -> int | None:
    """The checker's pid when one verifiably runs for this workspace."""
    from orch import procs

    holder = _holder(_checker_lock(root))
    if not holder or procs.owner_dead(holder):
        return None
    try:
        return int(holder.split()[0])
    except (IndexError, ValueError):
        return None


def still_on(root: Path) -> bool:
    from orch import addons

    try:
        return "services" in addons.active(root)
    except Exception:  # noqa: BLE001 - cannot tell right now: keep going, look again next round
        return True


def start(root: Path) -> int:
    root = root.resolve()
    pid = running_pid(root)
    if pid:
        return pid
    if not still_on(root):
        raise Refused("Services is not on here. Turn it on: orch addon add services")
    from orch import procs

    d = store.base_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    # -I -P: the workspace folder is never on the import path (a planted module there is not run)
    argv = [sys.executable, "-I", "-P", "-m", "orch_services", "--dir", str(root), "watch"]
    from orch.procs import service_start  # ORCH-2409: the one door for a long-running start

    with open(log_path(root), "a", encoding="utf-8") as log:
        proc = service_start(
            root,
            argv,
            start=subprocess.Popen,
            cwd=root,
            stdout=log,
            stderr=log,
            **procs.background_popen_kwargs(),
        )
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
    raise Refused("The regular check did not start. See .orch/addons/services/checker.log")


def stop(root: Path) -> bool:
    """True when a checker was stopped, False when none ran."""
    from orch import procs

    root = root.resolve()
    lock = _checker_lock(root)
    holder = _holder(lock)
    pid = running_pid(root)
    if pid is None:
        return False
    return procs.stop_tree(pid, verified=lambda: _holder(lock) == holder and not procs.owner_dead(holder))


def watch(
    root: Path,
    check: Callable[[], object],
    sleep=time.sleep,
    rounds: int | None = None,
    log=print,
) -> int:
    """Hold the checker lock and run check() every EVERY_SECS until Services is turned off here (or `rounds`
    passes, for tests). Exit 0; 0 too when another checker holds the lock."""
    root = root.resolve()
    lock = _checker_lock(root)
    if not take_lock(lock):
        log("The regular check runs already.")
        return 0
    try:
        log(f"Regular check of the services of {root.name} started (pid {os.getpid()}).")
        n = 0
        while (rounds is None or n < rounds) and (root / ".orch").is_dir() and still_on(root):
            n += 1
            try:
                with check_pass(root, wait=0):
                    check()
            except Refused:
                pass  # a person's check runs right now: this round is theirs
            except Exception as e:  # noqa: BLE001 - one bad round never ends the checker
                log(f"Check: {e.__class__.__name__}: {str(e)[:200]}")
            if rounds is None or n < rounds:
                sleep(EVERY_SECS)
        return 0
    finally:
        _drop_lock(lock)
