"""The browser's network filter: a small proxy inside the broker (wall note ORCH-1156 section 5).

- Listens on 127.0.0.1 at a random port; every connection must carry this run's random user and password
  (Proxy-Authorization), so other programs cannot use the ticket's filter.
- Handles CONNECT (HTTPS, secure WebSockets) and plain-HTTP requests (http://, ws://). Only ports 80/443.
- Checks every connection: name rules, the ticket's site list, then ONE lookup whose every answer must be
  outside the blocked ranges, and connects to exactly the address it checked. Redirect hops and WebSockets are
  new connections and meet the same checks.
- Writes each decision to net.jsonl (host, port, verdict, why), never paths or bodies.
- Closes when it fails: there is no direct way out; a missing or damaged site list means nothing is allowed.
"""

from __future__ import annotations

import base64
import hmac
import ipaddress
import json
import os
import secrets
import socket
import socketserver
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from . import netcheck

HEAD_MAX = 64 * 1024
CONNECT_TIMEOUT = 15
IDLE_TIMEOUT = 120


def test_map() -> dict[str, tuple[str, int]]:
    """Test-only exemption: name=127.0.0.1:port pairs that skip the address check. Read only in a strict test
    home (ORCH_HOME_STRICT=1 and ORCH_BROWSE_TEST_MAP set); a normal install never reads it."""
    raw = os.environ.get("ORCH_BROWSE_TEST_MAP", "")
    if not raw or os.environ.get("ORCH_HOME_STRICT") != "1":
        return {}
    out: dict[str, tuple[str, int]] = {}
    for pair in raw.split(","):
        if "=" not in pair:
            continue
        name, target = pair.strip().split("=", 1)
        host, _, port = target.rpartition(":")
        try:
            addr = ipaddress.ip_address(host.strip("[]"))
            if addr.is_loopback:  # a test site on this computer, nothing else
                out[name.strip().lower()] = (str(addr), int(port))
        except ValueError:
            continue
    return out


class Filter:
    """One filter per broker. sites() is asked on every connection (the person may change the list)."""

    def __init__(
        self,
        sites: Callable[[], list[str]],
        log_path: Path | None = None,
        local_nets: Callable[[], list] | None = None,
        nat64: list | None = None,
    ):
        self.sites = sites
        self.user = "orch-" + secrets.token_hex(6)
        self.password = secrets.token_urlsafe(24)
        self._auth = "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        self.local_nets = local_nets or (list)
        self.nat64 = list(nat64 or [])
        self.mapped = test_map()
        self._log = open(log_path, "a", buffering=1, encoding="utf-8") if log_path else None  # noqa: SIM115
        self._lock = threading.Lock()
        self.blocked_hosts: dict[str, str] = {}
        self.server: _Server | None = None
        self.thread: threading.Thread | None = None

    # ------------------------------------------------------------------ decisions

    def note(self, host: str, port: int, verdict: str, why: str) -> None:
        if verdict == "blocked" and host:
            with self._lock:
                self.blocked_hosts.setdefault(host.lower(), why)
        if self._log:
            line = {
                "t": round(time.time(), 3),
                "host": host[:255],
                "port": port,
                "verdict": verdict,
                "why": why,
            }
            with self._lock:
                self._log.write(json.dumps(line) + "\n")

    def decide(self, host: str, port: int) -> tuple[tuple[str, int] | None, str]:
        """(address to connect to, why). Never raises: anything odd is a refusal."""
        try:
            sites = [s for s in self.sites() if isinstance(s, str)]
        except Exception:  # noqa: BLE001 - a broken site list means nothing is allowed
            return None, "the site list could not be read, so nothing is allowed"
        h = (host or "").strip().lower().rstrip(".")
        why = netcheck.check_target(h, port, sites)
        if why:
            return None, why
        if h in self.mapped:
            return self.mapped[h], "allowed (test site)"
        addr, why = netcheck.resolve_checked(h, port, self.local_nets(), self.nat64)
        if not addr:
            return None, why
        return (addr, port), "allowed"

    def authorized(self, headers: list[str]) -> bool:
        for line in headers:
            name, _, value = line.partition(":")
            if name.strip().lower() == "proxy-authorization":
                return hmac.compare_digest(value.strip().encode(), self._auth.encode())
        return False

    # ------------------------------------------------------------------ server

    def start(self) -> int:
        self.server = _Server(("127.0.0.1", 0), _Handler)
        self.server.filter = self
        self.thread = threading.Thread(
            target=self.server.serve_forever, name="orch-browse-filter", daemon=True
        )
        self.thread.start()
        return self.server.server_address[1]

    @property
    def port(self) -> int:
        return self.server.server_address[1] if self.server else 0

    def alive(self) -> bool:
        """The filter answers on its port (the broker stops the browser when it does not)."""
        if not self.server or not self.thread or not self.thread.is_alive():
            return False
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=2) as s:
                s.sendall(b"OPTIONS * HTTP/1.1\r\nHost: orch-health\r\n\r\n")
                return s.recv(12).startswith(b"HTTP/1.1")
        except OSError:
            return False

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self._log:
            self._log.close()
            self._log = None


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False
    filter: Filter


def _reply(c: socket.socket, status: str, text: str = "", extra: str = "") -> None:
    body = (text + "\n").encode() if text else b""
    head = (
        f"HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {len(body)}\r\n"
        f"{extra}Connection: close\r\n\r\n"
    )
    try:
        c.sendall(head.encode() + body)
    except OSError:
        pass


def _pipe(a: socket.socket, b: socket.socket) -> None:
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        f: Filter = self.server.filter  # type: ignore[attr-defined]
        c: socket.socket = self.request
        c.settimeout(IDLE_TIMEOUT)
        buf = b""
        try:
            while b"\r\n\r\n" not in buf:
                chunk = c.recv(65536)
                if not chunk:
                    return
                buf += chunk
                if len(buf) > HEAD_MAX:
                    _reply(c, "431 Request Header Fields Too Large")
                    return
        except OSError:
            return
        head, body = buf.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, ver = lines[0].split(" ", 2)
        except ValueError:
            _reply(c, "400 Bad Request")
            return
        if method == "OPTIONS" and target == "*":
            _reply(c, "204 No Content")  # the broker's health check
            return
        if not f.authorized(lines[1:]):
            _reply(c, "407 Proxy Authentication Required", "", 'Proxy-Authenticate: Basic realm="orch"\r\n')
            return
        if method == "CONNECT":
            host, _, port_s = target.rpartition(":")
            path = ""
        else:
            u = urlsplit(target)
            if u.scheme not in ("http", "ws") or not u.hostname:
                f.note(u.hostname or "", 0, "blocked", "not a web address")
                _reply(c, "403 Forbidden", "Blocked by the orch browser: not a web address.")
                return
            host, port_s = u.hostname, str(u.port or 80)
            path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        if method != "CONNECT":
            heads = [ln.split(":", 1)[0].strip().lower() for ln in lines[1:]]
            if "upgrade" in heads:
                f.note(host, 0, "blocked", "live connections are off")
                _reply(c, "403 Forbidden", "Blocked by the orch browser: live connections are off.")
                return
            clen = next(
                (ln.split(":", 1)[1].strip() for ln in lines[1:] if ln.lower().startswith("content-length:")),
                "0",
            )
            if body or "transfer-encoding" in heads or clen not in ("", "0"):
                f.note(host, 0, "blocked", "this browser sends nothing")
                _reply(c, "403 Forbidden", "Blocked by the orch browser: it sends nothing.")
                return
        host = host.strip("[]")
        try:
            port = int(port_s)
        except ValueError:
            _reply(c, "400 Bad Request")
            return
        to, why = f.decide(host, port)
        f.note(host, port, "allowed" if to else "blocked", why)
        if not to:
            _reply(c, "403 Forbidden", f"Blocked by the orch browser: {why}.")
            return
        try:
            up = socket.create_connection(to, timeout=CONNECT_TIMEOUT)
        except OSError:
            _reply(c, "502 Bad Gateway", "The site did not answer.")
            return
        up.settimeout(IDLE_TIMEOUT)
        try:
            if method == "CONNECT":
                c.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                if body:
                    up.sendall(body)
            else:
                keep = [
                    ln
                    for ln in lines[1:]
                    if not ln.lower().startswith(("proxy-connection:", "connection:", "proxy-authorization:"))
                ]
                hdr = [f"{method} {path} {ver}", *keep, "Connection: close"]
                up.sendall("\r\n".join(hdr).encode("latin-1") + b"\r\n\r\n")
        except OSError:
            up.close()
            return
        if method != "CONNECT":
            # Plain HTTP: exactly one checked request per connection. The answer goes back, then both close;
            # nothing more the browser writes on this connection is read (a second request could name another
            # site and would skip every check).
            _pipe(up, c)
            up.close()
            return
        t = threading.Thread(target=_pipe, args=(c, up), daemon=True)
        t.start()
        _pipe(up, c)
        t.join(2)
        up.close()
