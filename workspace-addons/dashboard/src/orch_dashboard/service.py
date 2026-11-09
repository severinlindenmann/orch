"""Background run: `orch dashboard start|stop|status`. Runtime files in .orch/run/dashboard/ (gitignored):
server.json {pid, port, nonce, started}, the ready file, server.log. A pid from there is signalled only when that
process started at the recorded moment, runs `-m orch_dashboard --dir <root>` (POSIX), and the server on the recorded
port proves it knows the nonce (HMAC of a fresh challenge; the nonce itself is never served) and names that pid."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import signal
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
    return runfiles.run_dir(root, "dashboard")


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
        if not runfiles.runs_args(cmd, ["-m", "orch_dashboard", "--dir", str(root.resolve()), "serve"]):
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
    """{pid, port} of THIS workspace's background dashboard, verified (see module doc); else None (file dropped)."""
    rec = _record(root)
    if rec and _is_ours(root, rec["pid"], rec["port"], rec["nonce"], rec["started"]):
        return {"pid": rec["pid"], "port": rec["port"]}
    runfiles.remove(_dir(root) / "server.json")  # stale or not ours: ignored, rewritten on the next start
    return None


def write_ready(f: Path, port: int) -> None:
    """Child side: after bind, tell the starter which port and pid this server has (atomic)."""
    runfiles.write_json(f, {"pid": os.getpid(), "port": port})


def start(root: Path, port: int | None = None) -> dict:
    """The child binds the port itself (8420, else any free one) and writes the bound port to a ready file;
    the start counts only when that port answers with this start's nonce and the child's pid."""
    cur = running(root)
    if cur:
        return cur
    d = _dir(root)
    nonce = secrets.token_hex(16)
    ready = d / f"ready-{nonce[:12]}.json"
    kw = {"creationflags": 0x00000208} if os.name == "nt" else {"start_new_session": True}
    # -P: the workspace folder is never on the import path (a planted orch_dashboard.py there is not run)
    root = root.resolve()
    cmd = [
        sys.executable,
        "-P",
        "-m",
        "orch_dashboard",
        "--dir",
        str(root),
        "serve",
        "--ready-file",
        str(ready),
        *(["--port", str(port)] if port else ["--port", str(DEFAULT_PORT), "--auto-port"]),
    ]
    with runfiles.open_append(d / "server.log") as out:
        proc = subprocess.Popen(
            cmd,
            cwd=root,
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "ORCH_ROOT": str(root), "ORCH_DASHBOARD_NONCE": nonce},
            **kw,
        )
    try:
        end = time.time() + 15
        info = None
        while info is None:
            info = runfiles.read_json(ready)
            if info is None:
                if proc.poll() is not None:
                    raise RuntimeError("The dashboard did not start. See .orch/run/dashboard/server.log")
                if time.time() > end:
                    raise RuntimeError("The dashboard did not start within 15 seconds.")
                time.sleep(0.1)
        pid, bound = info.get("pid"), info.get("port")
        started = runfiles.proc_start(pid) if valid_pid(pid) else None
        if not isinstance(bound, int) or not _is_ours(root, pid, bound, nonce, started):
            raise RuntimeError(f"Something else answers on port {bound}; the dashboard was not started.")
    except RuntimeError:
        if proc.poll() is None:
            proc.terminate()  # our own child (never a pid read from a file)
        raise
    finally:
        runfiles.remove(ready)
    runfiles.write_json(d / "server.json", {"pid": pid, "port": bound, "nonce": nonce, "started": started})
    return {"pid": pid, "port": bound}


def stop(root: Path) -> str:
    """ "stopped", "not running", or "not verified" (a pid file that is not our dashboard: nothing is signalled)."""
    had = _record(root) is not None
    cur = running(root)
    if not cur:
        return "not verified" if had else "not running"
    try:
        os.kill(cur["pid"], signal.SIGTERM)  # the server itself (on Windows: TerminateProcess of the server)
    except OSError:
        pass
    runfiles.remove(_dir(root) / "server.json")
    return "stopped"
