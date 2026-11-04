"""Stdlib HTTP server on 127.0.0.1. GET only; every other method is refused."""
from __future__ import annotations

import json
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from .data import load_state

DEFAULT_PORT = 8420
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}


def web_file(name: str) -> bytes:
    return resources.files("orch_dashboard").joinpath("web", name).read_bytes()


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *a, root: Path, **kw):
        self.root = root
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

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            return self._send(200, json.dumps(load_state(self.root)).encode(), "application/json")
        name = {"/": "index.html"}.get(path, path.lstrip("/"))
        if name in ("index.html", "app.js", "style.css", "tokens.css", "logo.svg"):
            return self._send(200, web_file(name), TYPES["." + name.rsplit(".", 1)[1]])
        self._send(404, b"not found", "text/plain")

    def _refuse(self):
        self._send(405, b"read only", "text/plain")

    do_POST = do_PUT = do_DELETE = do_PATCH = _refuse


def make_server(root: Path, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, root=root))
