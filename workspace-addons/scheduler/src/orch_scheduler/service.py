"""Background process: `orch scheduler start|stop` with a pidfile in .orch/addons/scheduler/."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from .runner import _alive, sdir


def _pidfile(root: Path) -> Path:
    return root / ".orch" / "addons" / "scheduler" / "scheduler.pid"


def running_pid(root: Path, clean: bool = True) -> int | None:
    p = _pidfile(root)
    try:
        pid = int(p.read_text().strip())
    except (OSError, ValueError):
        return None
    if _alive(pid):
        return pid
    if clean:
        p.unlink(missing_ok=True)
    return None


def start(root: Path) -> int:
    pid = running_pid(root)
    if pid:
        return pid
    sdir(root)
    # -P: the workspace folder is never on the import path (a planted orch_scheduler.py there is not run)
    kw = {"creationflags": 0x00000208} if os.name == "nt" else {"start_new_session": True}
    with open(sdir(root) / "scheduler.log", "a") as out:
        proc = subprocess.Popen([sys.executable, "-P", "-m", "orch_scheduler", "--dir", str(root), "run"], cwd=root,
                                stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
    _pidfile(root).write_text(str(proc.pid))
    return proc.pid


def stop(root: Path) -> bool:
    pid = running_pid(root)
    if not pid:
        return False
    os.kill(pid, signal.SIGTERM)
    _pidfile(root).unlink(missing_ok=True)
    return True
