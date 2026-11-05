"""Stdlib HTTP server on 127.0.0.1. GET only; every other method is refused."""
from __future__ import annotations

import json
import os
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from .data import load_addons, load_state
from .views import ViewPuller

DEFAULT_PORT = 8420
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}


def web_file(name: str) -> bytes:
    return resources.files("orch_dashboard").joinpath("web", name).read_bytes()


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *a, root: Path, orch_bin: str | None, puller: ViewPuller, **kw):
        self.root, self.orch_bin, self.puller = root, orch_bin, puller
        self.nonce = os.environ.get("ORCH_DASHBOARD_NONCE", "")
        super().__init__(*a, **kw)

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        host = host.rsplit("]", 1)[0] + "]" if host.startswith("[") else host.split(":", 1)[0]
        return host in ("127.0.0.1", "localhost", "[::1]")

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return False
        if origin is None:
            return True
        host = (self.headers.get("Host") or "").strip().lower()
        return origin.lower() in (f"http://{host}",)

    def do_GET(self):
        if not self._host_ok():  # DNS rebinding guard
            return self._send(421, b"misdirected request", "text/plain")
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/") and not self._same_origin():  # a foreign page must not trigger pulls
            return self._send(403, b"forbidden", "text/plain")
        if path == "/ready" and self.nonce:  # background start/stop check they reach their own server
            return self._send(200, json.dumps({"nonce": self.nonce, "pid": os.getpid()}).encode(), "application/json")
        if path == "/api/state":
            return self._send(200, json.dumps(load_state(self.root, orch_bin=self.orch_bin)).encode(),
                              "application/json")
        if path.startswith("/api/addon/"):  # only names that are active here and have a tab
            name = path[len("/api/addon/"):]
            if not any(a["name"] == name and a["dashboard"] for a in load_addons(self.root, self.orch_bin)):
                return self._send(404, b"not found", "text/plain")
            return self._send(200, json.dumps(self.puller.pull(name)).encode(), "application/json")
        name = {"/": "index.html"}.get(path, path.lstrip("/"))
        if name in ("index.html", "app.js", "blocks.js", "style.css", "tokens.css", "logo.svg", "favicon.svg",
                    "apple-touch-icon.png"):
            return self._send(200, web_file(name), TYPES["." + name.rsplit(".", 1)[1]])
        self._send(404, b"not found", "text/plain")

    def _refuse(self):
        self._send(405, b"read only", "text/plain")

    do_POST = do_PUT = do_DELETE = do_PATCH = _refuse


def make_server(root: Path, port: int = DEFAULT_PORT, orch_bin: str | None = None) -> ThreadingHTTPServer:
    orch_bin = orch_bin if orch_bin is not None else os.environ.get("ORCH_BIN") or None
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, root=root, orch_bin=orch_bin,
                                                            puller=ViewPuller(root, orch_bin)))
