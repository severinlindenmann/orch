"""Background run: `orch dashboard start|stop|status`. The pid and port live in .orch/addons/dashboard/server.json."""
from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .server import DEFAULT_PORT


def _file(root: Path) -> Path:
    return root / ".orch" / "addons" / "dashboard" / "server.json"


def alive(pid: int) -> bool:
    if os.name == "nt":  # os.kill(pid, 0) would end the process on Windows
        import ctypes

        k = ctypes.windll.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
        k.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
        k.CloseHandle.argtypes = (ctypes.c_void_p,)
        h = k.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def running(root: Path) -> dict | None:
    """{pid, port} of the background dashboard of this workspace, or None (a stale file is removed)."""
    try:
        d = json.loads(_file(root).read_text(encoding="utf-8"))
        pid, port = int(d["pid"]), int(d["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if alive(pid):
        return {"pid": pid, "port": port}
    _file(root).unlink(missing_ok=True)
    return None


def write_ready(f: Path, port: int) -> None:
    """Child side: after bind, tell the starter which port this process holds (atomic write)."""
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"pid": os.getpid(), "port": port}), encoding="utf-8")
    os.replace(tmp, f)


def _nonce_of(port: int) -> str:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ready", timeout=2) as r:
            return r.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""


def start(root: Path, port: int | None = None) -> dict:
    """The child binds the port itself (8420, else any free one) and writes the bound port to a ready file;
    the start counts only when that port answers with this start's nonce (no other process can pose as it)."""
    cur = running(root)
    if cur:
        return cur
    d = _file(root).parent
    d.mkdir(parents=True, exist_ok=True)
    nonce = secrets.token_hex(16)
    ready = d / f"ready-{nonce[:12]}.json"
    kw = {"creationflags": 0x00000208} if os.name == "nt" else {"start_new_session": True}
    # -P: the workspace folder is never on the import path (a planted orch_dashboard.py there is not run)
    cmd = [sys.executable, "-P", "-m", "orch_dashboard", "--dir", str(root), "serve", "--ready-file", str(ready),
           *(["--port", str(port)] if port else ["--port", str(DEFAULT_PORT), "--auto-port"])]
    with open(d / "server.log", "a") as out:
        proc = subprocess.Popen(cmd, cwd=root, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env={**os.environ, "ORCH_DASHBOARD_NONCE": nonce}, **kw)
    try:
        end = time.time() + 15
        while not ready.exists():
            if proc.poll() is not None:
                raise RuntimeError("The dashboard did not start. See .orch/addons/dashboard/server.log")
            if time.time() > end:
                raise RuntimeError("The dashboard did not start within 15 seconds.")
            time.sleep(0.1)
        info = json.loads(ready.read_text(encoding="utf-8"))
        bound = int(info["port"])
        pid = int(info["pid"])  # the server itself (on Windows a venv launcher may sit in between)
        if not secrets.compare_digest(_nonce_of(bound), nonce):
            raise RuntimeError(f"Something else answers on port {bound}; the dashboard was not started.")
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as e:
        if proc.poll() is None:
            proc.terminate()
        raise RuntimeError(str(e)) from None
    finally:
        ready.unlink(missing_ok=True)
    _file(root).write_text(json.dumps({"pid": pid, "port": bound}), encoding="utf-8")
    return {"pid": pid, "port": bound}


def stop(root: Path) -> bool:
    cur = running(root)
    if not cur:
        return False
    try:
        os.kill(cur["pid"], signal.SIGTERM)
    except OSError:
        pass
    _file(root).unlink(missing_ok=True)
    return True
