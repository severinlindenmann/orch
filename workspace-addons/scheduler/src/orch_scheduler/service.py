"""Background process: `orch scheduler start|stop|status` with a pidfile in .orch/scheduler/."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

from .runner import _alive, sdir


def _pidfile(root: Path) -> Path:
    return sdir(root) / "scheduler.pid"


def running_pid(root: Path) -> int | None:
    p = _pidfile(root)
    try:
        pid = int(p.read_text().strip())
    except (OSError, ValueError):
        return None
    if _alive(pid):
        return pid
    p.unlink(missing_ok=True)
    return None


def start(root: Path) -> int:
    pid = running_pid(root)
    if pid:
        return pid
    kw = {"creationflags": 0x00000208} if os.name == "nt" else {"start_new_session": True}
    with open(sdir(root) / "scheduler.log", "a") as out:
        proc = subprocess.Popen([sys.executable, "-m", "orch_scheduler.cli", "--dir", str(root), "run"], cwd=root,
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
