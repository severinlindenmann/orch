"""Background run: `orch dashboard start|stop|status`. The pid and port live in .orch/addons/dashboard/server.json."""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from .server import DEFAULT_PORT


def _file(root: Path) -> Path:
    return root / ".orch" / "addons" / "dashboard" / "server.json"


def alive(pid: int) -> bool:
    if os.name == "nt":  # os.kill(pid, 0) would end the process on Windows
        import ctypes

        k = ctypes.windll.kernel32
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


def _free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _pick_port() -> int:
    if _free(DEFAULT_PORT):
        return DEFAULT_PORT
    with socket.socket() as s:  # another workspace has 8420: let the system pick one
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def start(root: Path, port: int | None = None) -> dict:
    cur = running(root)
    if cur:
        return cur
    port = port or _pick_port()
    _file(root).parent.mkdir(parents=True, exist_ok=True)
    kw = {"creationflags": 0x00000208} if os.name == "nt" else {"start_new_session": True}
    with open(_file(root).parent / "server.log", "a") as out:
        proc = subprocess.Popen([sys.executable, "-m", "orch_dashboard", "--dir", str(root), "serve", "--port", str(port)],
                                cwd=root, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
    end = time.time() + 15
    while time.time() < end:
        if proc.poll() is not None:
            raise RuntimeError(f"The dashboard did not start (port {port} busy?). See .orch/addons/dashboard/server.log")
        if _listening(port):
            break
        time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError("The dashboard did not start within 15 seconds.")
    _file(root).write_text(json.dumps({"pid": proc.pid, "port": port}), encoding="utf-8")
    return {"pid": proc.pid, "port": port}


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
