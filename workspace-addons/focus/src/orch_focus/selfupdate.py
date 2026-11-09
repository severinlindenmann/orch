"""After `orch update` replaced this package, a running server restarts itself on the next page request.

The server compares a cheap stamp of its installed files (version, inode and mtime of server.py and the page)
with the one taken at start (cached for 2 s). When it changed, the page request is answered with a short
"orch was updated, restarting" page that reloads itself, and the process is replaced by a fresh one (same pid,
same port, same nonce) once the new code imports. POSIX only (on Windows exec starts a new pid, so `orch update`
restarts the service instead). Own copy per add-on, same as runfiles.py."""

from __future__ import annotations

import contextlib
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
_state: dict = {"restarting": False, "failed": None, "thread": None}

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


def new_argv(orig: list[str], port: int) -> list[str] | None:
    """The command of the new process, rebuilt (not copied): this interpreter with -P (the working folder is never
    on the import path), `-m <package>`, the old arguments after the module name with the same port (no
    auto-port, no ready file: the starter is gone). None when this process was not started as `-m <package>`."""
    try:
        i = orig.index("-m")
    except ValueError:
        return None
    if orig[i + 1 : i + 2] != [PKG]:
        return None
    out, skip = [], False
    for a in orig[i + 2 :]:
        if skip:
            skip = False
        elif a in ("--ready-file", "--port"):
            skip = True
        elif a.startswith(("--ready-file=", "--port=")) or a == "--auto-port":
            continue
        else:
            out.append(a)
    return [sys.executable, "-P", "-m", PKG, *out, "--port", str(port)]


def _runs_new_code() -> bool:
    """The same isolation as the exec: -P, the package's parent folder as cwd, the same environment."""
    try:
        r = subprocess.run(
            [sys.executable, "-P", "-c", f"import {PKG}.server"],
            capture_output=True,
            check=False,
            timeout=30,
            stdin=subprocess.DEVNULL,
            cwd=_HERE.parent,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def restart(port: int, delay: float = 0.3) -> bool:
    """Schedule the exec of a fresh process (once). False when not possible here (Windows, not started as
    `-m <package>`, already restarting, or this very install already failed its import check)."""
    argv = getattr(sys, "orig_argv", None)
    new = new_argv(argv, port) if argv else None
    if os.name == "nt" or not new:
        return False
    with _lock:  # check-and-set is one step: concurrent requests start one restart
        now = stamp()
        if _state["restarting"] or now == _state["failed"]:
            return False
        _state["restarting"] = True

    def run():
        time.sleep(delay)  # the answer is on the wire
        failed = True
        if _runs_new_code():
            cwd = os.getcwd()
            try:
                os.chdir(_HERE.parent)  # never exec from the workspace folder
                os.execv(sys.executable, new)
            except OSError:
                with contextlib.suppress(OSError):
                    os.chdir(cwd)
        with _lock:  # the new build does not run: serve the normal page until the files change again
            _state["failed"] = now if failed else None
            _state["restarting"] = False

    t = threading.Thread(target=run, daemon=True, name="selfupdate")
    _state["thread"] = t
    t.start()
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
