"""After `orch update` replaced this package, a running server restarts itself on the next page request.

The server compares a cheap stamp of its installed files (version, inode and mtime of server.py and the page)
with the one taken at start (cached for 2 s). When it changed, the page request is answered with a short
"orch was updated, restarting" page that reloads itself, and the process is replaced by a fresh one (same pid,
same port, same nonce) once the new code imports. POSIX only (on Windows exec starts a new pid, so `orch update`
restarts the service instead). Own copy per add-on, same as runfiles.py."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

PKG = "orch_" + Path(__file__).resolve().parent.name.removeprefix("orch_")
_HERE = Path(__file__).resolve().parent
_TTL = 2.0
_lock = threading.Lock()
_cache: dict = {"at": -1e9, "stamp": None}
_state = {"restarting": False}

PAGE = (
    b'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="2">'
    b"<title>orch</title><p>orch was updated - restarting...</p>"
)


def _sig(p: Path):
    try:
        st = p.stat()
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _version() -> str | None:
    try:
        from importlib.metadata import version

        return version(PKG.replace("_", "-"))
    except Exception:  # noqa: BLE001 - not installed as a distribution (a source checkout)
        return None


def stamp() -> tuple:
    return (_version(), _sig(_HERE / "server.py"), _sig(_HERE / "web" / "index.html"))


_START = stamp()


def changed(now: float | None = None) -> bool:
    """True when the installed files are no longer the ones this process started with (cheap, cached)."""
    t = time.monotonic() if now is None else now
    with _lock:
        if t - _cache["at"] >= _TTL:
            _cache.update(at=t, stamp=stamp())
        return _cache["stamp"] != _START


def new_argv(orig: list[str], port: int) -> list[str]:
    """The same command for the new process: same port (no auto-port), no ready file (the starter is gone)."""
    out, skip = [], False
    for a in orig:
        if skip:
            skip = False
        elif a in ("--ready-file", "--port"):
            skip = True
        elif a.startswith(("--ready-file=", "--port=")) or a == "--auto-port":
            continue
        else:
            out.append(a)
    return [*out, "--port", str(port)]


def _runs_new_code() -> bool:
    try:
        r = subprocess.run(
            [sys.executable, "-P", "-c", f"import {PKG}.server"],
            capture_output=True,
            check=False,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def restart(port: int, delay: float = 0.3) -> bool:
    """Schedule the exec of a fresh process (once). False when not possible here (Windows, no orig_argv, already
    restarting)."""
    argv = getattr(sys, "orig_argv", None)
    if os.name == "nt" or not argv or _state["restarting"]:
        return False
    _state["restarting"] = True

    def run():
        time.sleep(delay)  # the answer is on the wire
        if _runs_new_code():
            try:
                os.execv(sys.executable, new_argv(argv, port))
            except OSError:
                pass
        _state["restarting"] = False
        with _lock:  # try again at the next request, not in a loop
            _cache["at"] = time.monotonic() + 30

    threading.Thread(target=run, daemon=True, name="selfupdate").start()
    return True


def answer(handler) -> bool:
    """At the top of a page request: when the install changed, send the 'restarting' page and restart.
    True = answered (the caller returns)."""
    if not changed():
        return False
    if not restart(handler.server.server_address[1]):
        return False
    handler._send(200, PAGE, "text/html; charset=utf-8")
    return True
