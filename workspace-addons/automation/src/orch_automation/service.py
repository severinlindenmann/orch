"""Background process: `orch automation start|stop`. Runtime files in .orch/run/automation/ (gitignored):
automation.json {pid, nonce, started} written by the process itself, automation.log. A pid from there is signalled only
when the process with that pid started at the recorded moment and runs orch_automation for this folder."""
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
from .runfiles import alive, proc_start, valid_pid  # noqa: F401  (proc_start: tests)

NONCE_ENV = "ORCH_AUTOMATION_NONCE"


def _dir(root: Path) -> Path:
    return runfiles.run_dir(root, "automation")


def _verified(root: Path, rec: dict | None) -> int | None:
    if not rec:
        return None
    pid, started, nonce = rec.get("pid"), rec.get("started"), rec.get("nonce")
    if not (valid_pid(pid) and isinstance(started, str) and started and isinstance(nonce, str)
            and re.fullmatch(r"[0-9a-f]{32}", nonce)):
        return None
    if not alive(pid) or runfiles.proc_start(pid) != started:
        return None
    if os.name != "nt":  # POSIX: it must also be our command for this folder
        cmd = runfiles.command(pid)
        if not runfiles.runs_args(cmd, ["-m", "orch_automation", "--dir", str(root.resolve()), "run"]):
            return None
    return pid


def running_pid(root: Path, clean: bool = True) -> int | None:
    try:
        d = _dir(root)
    except RuntimeError:
        return None
    pid = _verified(root, runfiles.read_json(d / "automation.json"))
    if pid is None and clean:
        runfiles.remove(d / "automation.json")  # stale or not ours: ignored, rewritten on the next start
    return pid


def announce(root: Path) -> str | None:
    """In the background process: record who we are (only when started by `start`, which passed a nonce)."""
    nonce = os.environ.get(NONCE_ENV, "")
    if not re.fullmatch(r"[0-9a-f]{32}", nonce):
        return None
    me = os.getpid()
    runfiles.write_json(_dir(root) / "automation.json", {"pid": me, "nonce": nonce, "started": runfiles.proc_start(me) or ""})
    return nonce


def forget(root: Path, nonce: str | None) -> None:
    """On exit: remove our record (only if it is still ours)."""
    if not nonce:
        return
    p = _dir(root) / "automation.json"
    rec = runfiles.read_json(p)
    if rec and rec.get("nonce") == nonce and rec.get("pid") == os.getpid():
        runfiles.remove(p)


def start(root: Path) -> int:
    root = root.resolve()  # --dir, cwd and ORCH_ROOT name one folder
    pid = running_pid(root)
    if pid:
        return pid
    d = _dir(root)
    root = root.resolve()
    nonce = secrets.token_hex(16)
    # -P: the workspace folder is never on the import path (a planted orch_automation.py there is not run)
    kw = {"creationflags": 0x00000208} if os.name == "nt" else {"start_new_session": True}
    with runfiles.open_append(d / "automation.log") as out:
        proc = subprocess.Popen([sys.executable, "-P", "-m", "orch_automation", "--dir", str(root), "run"], cwd=root,
                                stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env={**os.environ, "ORCH_ROOT": str(root.resolve()), NONCE_ENV: nonce}, **kw)
    end = time.time() + 15
    while time.time() < end:
        rec = runfiles.read_json(d / "automation.json")
        if rec and rec.get("nonce") == nonce and _verified(root, rec):
            return rec["pid"]
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    if proc.poll() is None:
        proc.terminate()  # our own child (never a pid read from a file)
    raise RuntimeError("The scheduler did not start. See .orch/run/automation/automation.log")


def stop(root: Path) -> str:
    """"stopped", "not running", or "not verified" (a pid file that is not our scheduler: nothing is signalled)."""
    try:
        had = runfiles.read_json(_dir(root) / "automation.json") is not None
    except RuntimeError:
        return "not verified"
    pid = running_pid(root)
    if not pid:
        return "not verified" if had else "not running"
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    runfiles.remove(_dir(root) / "automation.json")
    return "stopped"
