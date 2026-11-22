"""Background run: `orch focus start|stop|status`. Runtime files in .orch/run/focus/ (gitignored):
server.json {pid, port, nonce, started}, the ready file, server.log. A pid from there is signalled only when that
process started at the recorded moment, runs `-m orch_focus --dir <root>` (POSIX), and the server on the recorded
port proves it knows the nonce (HMAC of a fresh challenge; the nonce itself is never served) and names that pid."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import runfiles
from .runfiles import alive, valid_pid
from .server import DEFAULT_PORT

NONCE_RE = re.compile(r"^[0-9a-f]{32}$")


def _dir(root: Path) -> Path:
    return runfiles.run_dir(root, "focus")


def url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def mac(nonce: str, challenge: str) -> str:
    return hmac.new(nonce.encode(), challenge.encode(), hashlib.sha256).hexdigest()


def ident(port: int, challenge: str) -> dict | None:
    """The server's answer to a challenge: {"pid", "mac"} from GET /ready?c=<challenge>, or None."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ready?c={challenge}", timeout=2) as r:
            data = json.loads(r.read(1024))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _is_ours(root: Path, pid: int, port: int, nonce: str, started: str | None) -> bool:
    """pid > 1, alive, started when recorded, our command for this folder (POSIX), and the server on `port`
    answers a fresh challenge with HMAC(nonce) and this pid."""
    if not (valid_pid(pid) and alive(pid) and started and runfiles.proc_start(pid) == started):
        return False
    if os.name != "nt":
        cmd = runfiles.command(pid)
        if not runfiles.runs_args(cmd, ["-m", "orch_focus", "--dir", str(root.resolve()), "serve"]):
            return False
    c = secrets.token_hex(16)
    got = ident(port, c)
    if not got or got.get("pid") != pid or not isinstance(got.get("mac"), str):
        return False
    try:
        return hmac.compare_digest(got["mac"], mac(nonce, c))
    except TypeError:
        return False


def _record(root: Path) -> dict | None:
    d = runfiles.read_json(_dir(root) / "server.json")
    if not d:
        return None
    pid, port, nonce, started = d.get("pid"), d.get("port"), d.get("nonce"), d.get("started")
    if not (
        valid_pid(pid)
        and isinstance(port, int)
        and 0 < port < 65536
        and isinstance(nonce, str)
        and NONCE_RE.match(nonce)
        and isinstance(started, str)
    ):
        return None
    return {"pid": pid, "port": port, "nonce": nonce, "started": started}


def running(root: Path) -> dict | None:
    """{pid, port} of THIS workspace's background Focus, verified (see module doc); else None (file dropped)."""
    rec = _record(root)
    if rec and _is_ours(root, rec["pid"], rec["port"], rec["nonce"], rec["started"]):
        return {"pid": rec["pid"], "port": rec["port"]}
    runfiles.remove(_dir(root) / "server.json")  # stale or not ours: ignored, rewritten on the next start
    return None


def write_ready(f: Path, port: int) -> None:
    """Child side: after bind, tell the starter which port and pid this server has (atomic)."""
    runfiles.write_json(f, {"pid": os.getpid(), "port": port})


def _preferred_port() -> int | None:
    """ORCH_PREFERRED_PORT (set by `orch start`: the port this service had last time), only when valid."""
    v = os.environ.get("ORCH_PREFERRED_PORT", "")
    return int(v) if v.isdigit() and 1024 <= int(v) < 65536 else None


def start(root: Path, port: int | None = None) -> dict:
    """The child binds the port itself (8420, else any free one) and writes the bound port to a ready file;
    the start counts only when that port answers with this start's nonce and the child's pid."""
    root = root.resolve()  # --dir, cwd and ORCH_ROOT name one folder
    from orch import pagesession

    cur = running(root)
    prefer = None
    if cur and not pagesession.restart_watch_only(runfiles.read_json(_dir(root) / "server.json")):
        return cur
    if cur:  # a helper started it (watch-only) and this start is the person's: start it again
        stop(root)
        prefer = cur["port"]  # its old port first, any free one if that is not free yet
    d = _dir(root)
    nonce = secrets.token_hex(16)
    ready = d / f"ready-{nonce[:12]}.json"
    from orch.procs import background_popen_kwargs, wait_port_free

    # sticky: `orch start` passes this service's last port; a watch-only restart tries the old one first
    first = port or prefer or _preferred_port() or DEFAULT_PORT
    if not wait_port_free(first) and port:
        raise RuntimeError(f"Something else answers on port {port}; try again in a moment.")

    # -P: the workspace folder is never on the import path (a planted orch_focus.py there is not run)
    root = root.resolve()
    cmd = [
        sys.executable,
        "-P",
        "-m",
        "orch_focus",
        "--dir",
        str(root),
        "serve",
        "--ready-file",
        str(ready),
        *(["--port", str(port)] if port else ["--port", str(first), "--auto-port"]),
    ]
    with runfiles.open_append(d / "server.log") as out:
        proc = subprocess.Popen(
            cmd,
            cwd=root,
            stdout=out,
            stderr=subprocess.STDOUT,
            env={**os.environ, "ORCH_ROOT": str(root.resolve()), "ORCH_FOCUS_NONCE": nonce},
            **background_popen_kwargs(),
        )
    try:
        end = time.time() + 15
        info = None
        while info is None:
            info = runfiles.read_json(ready)
            if info is None:
                if proc.poll() is not None:
                    raise RuntimeError("Focus did not start. See .orch/run/focus/server.log")
                if time.time() > end:
                    raise RuntimeError("Focus did not start within 15 seconds.")
                time.sleep(0.1)
        pid, bound = info.get("pid"), info.get("port")
        started = runfiles.proc_start(pid) if valid_pid(pid) else None
        if not isinstance(bound, int) or not _is_ours(root, pid, bound, nonce, started):
            raise RuntimeError(f"Something else answers on port {bound}; Focus was not started.")
    except RuntimeError:
        if proc.poll() is None:
            proc.terminate()  # our own child (never a pid read from a file)
        raise
    finally:
        runfiles.remove(ready)
    runfiles.write_json(
        d / "server.json",
        {
            "pid": pid,
            "port": bound,
            "nonce": nonce,
            "started": started,
            "watch_only": pagesession.started_watch_only(dict(os.environ)),  # the child got this environment
        },
    )
    return {"pid": pid, "port": bound}


RESTART_ENV = "ORCH_SERVICE_RESTART"  # core sets "1" when this stop is half of a restart (an add-on changed)
RESTART_MARK_SECONDS = 120  # an older mark is left over from a stop that never reached the server


def _restart_mark(root: Path) -> Path:
    return _dir(root) / "restarting.json"


def take_restart_mark(root: Path, now: float | None = None, pid: int | None = None) -> bool:
    """True when the server ends because core restarts it (owner, ORCH-1443: a restart keeps the runs Focus
    started; only Ctrl+C or a real stop ends them). The mark is used once and removed."""
    p = _restart_mark(root)
    rec = runfiles.read_json(p)
    runfiles.remove(p)
    at = (rec or {}).get("at")
    now = time.time() if now is None else now
    pid = os.getpid() if pid is None else pid
    fresh = (
        isinstance(at, (int, float)) and not isinstance(at, bool) and 0 <= now - at <= RESTART_MARK_SECONDS
    )
    return fresh and (rec or {}).get("pid") == pid  # a mark for another server is not this one's restart


def stop(root: Path, restart: bool | None = None) -> str:
    """ "stopped", "not running", or "not verified" (a pid file that is not our Focus: nothing is signalled).
    restart (default: core's RESTART_ENV): the server is started again right after; it keeps the runs it
    started instead of ending them."""
    from orch.procs import stop_tree

    if restart is None:
        restart = os.environ.get(RESTART_ENV) == "1"
    rec = _record(root)
    if not rec:
        return "not running"
    if restart:
        runfiles.write_json(_restart_mark(root), {"at": time.time(), "pid": rec["pid"]})
    else:
        runfiles.remove(_restart_mark(root))
    try:
        ok = stop_tree(
            rec["pid"],
            verified=lambda: _is_ours(root, rec["pid"], rec["port"], rec["nonce"], rec["started"]),
        )
    except BaseException:
        runfiles.remove(_restart_mark(root))  # the server still runs: a later Ctrl+C is a real end
        raise
    if not ok:
        runfiles.remove(_dir(root) / "server.json")
        runfiles.remove(_restart_mark(root))
        return "not verified"
    runfiles.remove(_dir(root) / "server.json")
    return "stopped"
