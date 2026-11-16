"""The Usage page: a loopback HTTP server inside the background process (`orch usage run`), fenced by the shared
UI origin checks. It only reads. Every change on the page is a click the dashboard runs as the person
(`orch usage act <verb> --by <person> -- <target>`, see acts.py), so this server holds no session and no secret
besides the start nonce it proves itself with (GET /ready)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

DEFAULT_PORT = 8432
NONCE_ENV = "ORCH_USAGE_NONCE"
KIT_FILES = (
    "tokens.css",
    "components.css",
    "motion.css",
    "interaction.css",
    "widgets.css",
    "overlay.js",
    "components.js",
    "date.js",
)
WEB_FILES = ("index.html", "usage.js")
TYPES = {"html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8", "js": "text/javascript"}
PLAIN = "text/plain; charset=utf-8"
PREFIX = re.compile(r"/addon/[a-z][a-z0-9-]{1,31}")
CSP = "default-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'"
FRESH_SECONDS = 20  # the readers are asked at most this often; a click asks again at once (?fresh=1)


def _web(name: str) -> bytes:
    return resources.files("orch_usage").joinpath("web", name).read_bytes()


def _kit(name: str) -> bytes | None:
    """A file of the one master kit (orch_ui's static folder); None when it is not installed."""
    try:
        import orch_ui

        return (Path(orch_ui.__file__).parent / "static" / name).read_bytes()
    except (ImportError, OSError, TypeError):
        return None


class PageData:
    """The page model, asked of the readers at most every FRESH_SECONDS (one at a time)."""

    def __init__(self, root: Path, gather=None):
        self.root = root
        self._gather = gather
        self._lock = threading.Lock()
        self._at = 0.0
        self._data: dict | None = None

    def get(self, fresh: bool = False) -> dict:
        from . import cli, page

        with self._lock:
            if fresh or self._data is None or time.monotonic() - self._at > FRESH_SECONDS:
                self._data = (self._gather or cli.gather)(self.root)
                self._at = time.monotonic()
            data = self._data
        return page.build(data, self.root)


class Handler(BaseHTTPRequestHandler):
    timeout = 10

    def __init__(self, *args, data: PageData, nonce: str, **kwargs):
        self.data, self.nonce = data, nonce
        super().__init__(*args, **kwargs)

    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str = PLAIN) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _fence(self, api: bool) -> str | None:
        try:
            from orch_ui.origin import check_request
        except ImportError:
            return "The Usage page is not available in this install."
        return check_request("GET", self.headers, self.server.server_address[1], api=api)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        why = self._fence(path.startswith("/api/") or path == "/ready")
        if why:
            return self._send(403, why.encode())
        if path == "/ready" and self.nonce:
            challenge = query.partition("c=")[2]
            if not re.fullmatch(r"[0-9a-f]{32,64}", challenge):
                return self._send(404, b"not found")
            mac = hmac.new(self.nonce.encode(), challenge.encode(), hashlib.sha256).hexdigest()
            return self._send(200, json.dumps({"pid": os.getpid(), "mac": mac}).encode(), "application/json")
        if path == "/api/page":
            from .store import Refused

            try:
                body = self.data.get(fresh=query == "fresh=1")
            except (Refused, RuntimeError, OSError) as e:
                return self._send(503, str(e).encode())
            return self._send(200, json.dumps(body, ensure_ascii=False).encode(), "application/json")
        if path == "/":
            prefix = self.headers.get("X-Forwarded-Prefix") or ""
            prefix = prefix if PREFIX.fullmatch(prefix) else ""
            return self._send(200, _web("index.html").replace(b"__P__", prefix.encode()), TYPES["html"])
        if path.startswith("/kit/") and path[5:] in KIT_FILES:
            body = _kit(path[5:])
            if body is None:
                return self._send(404, b"not found")
            return self._send(200, body, TYPES[path.rsplit(".", 1)[1]])
        if path.startswith("/web/") and path[5:] in WEB_FILES:
            return self._send(200, _web(path[5:]), TYPES[path.rsplit(".", 1)[1]])
        return self._send(404, b"not found")

    def _refuse(self):
        return self._send(405, b"not allowed")

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _refuse


def make_server(root: Path, port: int = DEFAULT_PORT, gather=None, nonce: str | None = None):
    """Bind 127.0.0.1:<port>; with port 0 any free port. Callers own its lifetime; tests pass a fake gather."""
    data = PageData(root.resolve(), gather)
    nonce = os.environ.get(NONCE_ENV, "") if nonce is None else nonce
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, data=data, nonce=nonce))


def serve_in_background(root: Path, port: int | None = None) -> ThreadingHTTPServer | None:
    """The page next to the switching loop: the preferred port, else any free one. None when nothing binds
    (the loop still runs; the page then shows the dashboard's 'not running')."""
    for p in (port or DEFAULT_PORT, 0):
        try:
            srv = make_server(root, p)
        except OSError:
            continue
        threading.Thread(target=srv.serve_forever, name="usage-page", daemon=True).start()
        return srv
    return None
