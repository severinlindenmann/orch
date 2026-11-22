"""The helper's only way to the broker (wall note section 3).

A Unix socket in the ticket's 0700 run folder (Windows: a named pipe), plus a random key per run that both
sides prove with an HMAC challenge (multiprocessing.connection authkey). Messages are JSON bytes, never
pickle. The command set is fixed by the broker; there is no eval and no pass-through to the browser.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Connection, Listener
from pathlib import Path

MSG_MAX = 1 << 20


class Refusal(Exception):
    """A plain-words refusal the helper sees (exit 2)."""


def _addr_file(run: Path) -> Path:
    return run / "channel.json"


def _address(run: Path) -> tuple[str, str]:
    if sys.platform == "win32":
        return r"\\.\pipe\orch-browse-" + secrets.token_hex(12), "AF_PIPE"
    from . import paths

    return str(paths.socket_path(run)), "AF_UNIX"


def listen(run: Path):
    """Open the channel; returns (listener, wake) where wake() unblocks a waiting accept."""
    address, family = _address(run)
    if family == "AF_UNIX":
        try:
            os.unlink(address)
        except FileNotFoundError:
            pass
    key = secrets.token_bytes(32)
    old = os.umask(0o077)
    try:
        listener = Listener(address, family=family, authkey=key, backlog=8)
    finally:
        os.umask(old)
    if family == "AF_UNIX":
        os.chmod(address, 0o600)
    f = _addr_file(run)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"address": address, "family": family, "key": key.hex()}, fh)

    def wake() -> None:
        try:
            with Client(address, family=family, authkey=key) as c:
                c.send_bytes(b'{"cmd": "wake"}')
        except (OSError, EOFError, AuthenticationError):
            pass

    return listener, wake


def accept(listener: Listener):
    """(conn, cmd, args), or None for a refused or odd caller."""
    try:
        conn = listener.accept()
    except (OSError, EOFError, AuthenticationError):
        return None
    try:
        if not conn.poll(30):
            conn.close()
            return None
        req = json.loads(conn.recv_bytes(MSG_MAX))
        cmd, args = str(req.get("cmd", "")), [str(a) for a in req.get("args", [])][:20]
    except (OSError, EOFError, ValueError, AttributeError, TypeError):
        conn.close()
        return None
    if cmd == "wake":
        conn.close()
        return None
    return conn, cmd, args


def answer(conn: Connection, ok: bool, out: str) -> None:
    try:
        conn.send_bytes(json.dumps({"ok": ok, "out": out}).encode())
    except OSError:
        pass
    finally:
        conn.close()


def close(listener: Listener, run: Path) -> None:
    try:
        listener.close()
    except OSError:
        pass
    for p in (_addr_file(run),):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def call(run: Path, cmd: str, args: list[str], timeout: float = 120) -> dict | None:
    """Send one command; None when no broker answers."""
    try:
        info = json.loads(_addr_file(run).read_text(encoding="utf-8"))
        with Client(info["address"], family=info["family"], authkey=bytes.fromhex(info["key"])) as c:
            c.send_bytes(json.dumps({"cmd": cmd, "args": args}).encode())
            if not c.poll(timeout):
                return {"ok": False, "out": "The browser did not answer in time."}
            return json.loads(c.recv_bytes(MSG_MAX))
    except (OSError, EOFError, ValueError, KeyError, AuthenticationError):
        return None
