"""Stdlib HTTP server on 127.0.0.1. GET reads; the only POST is /api/act (the fixed op table in actions.py)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from . import actions
from .data import load_addons, load_state
from .views import ViewPuller

DEFAULT_PORT = 8420
MAX_BODY = 16384
KIT = ("tokens.css", "components.css", "motion.css", "motion.js", "icons.js", "question-card-state.js",
       "question-card.js", "evidence.js")
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}


def web_file(name: str) -> bytes:
    return resources.files("orch_dashboard").joinpath("web", name).read_bytes()


class Handler(BaseHTTPRequestHandler):
    timeout = 10  # a short body must not hold a thread
    def __init__(self, *a, root: Path, orch_bin: str | None, puller: ViewPuller, **kw):
        self.root, self.orch_bin, self.puller = root, orch_bin, puller
        self.nonce = os.environ.get("ORCH_DASHBOARD_NONCE", "")
        super().__init__(*a, **kw)

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
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
        if path == "/ready" and self.nonce:  # challenge-response for start/stop; the nonce itself is never sent
            c = self.path.partition("?c=")[2]
            if not re.fullmatch(r"[0-9a-f]{32,64}", c):
                return self._send(404, b"not found", "text/plain")
            m = hmac.new(self.nonce.encode(), c.encode(), hashlib.sha256).hexdigest()
            return self._send(200, json.dumps({"pid": os.getpid(), "mac": m}).encode(), "application/json")
        if path == "/api/state":
            return self._send(200, json.dumps(load_state(self.root, orch_bin=self.orch_bin)).encode(),
                              "application/json")
        if path.startswith("/api/addon/"):  # only names that are active here and have a tab
            name = path[len("/api/addon/"):]
            if not any(a["name"] == name and a["dashboard"] for a in load_addons(self.root, self.orch_bin)):
                return self._send(404, b"not found", "text/plain")
            return self._send(200, json.dumps(self.puller.pull(name)).encode(), "application/json")
        name = {"/": "index.html"}.get(path, path.lstrip("/"))
        if name.startswith("kit/") and name[4:] in KIT:  # the orch_ui kit, copied next to the page (a test keeps it in sync)
            return self._send(200, web_file(name), TYPES["." + name.rsplit(".", 1)[1]])
        if name in ("index.html", "app.js", "blocks.js", "helpers.js", "style.css", "logo.svg", "favicon.svg",
                    "apple-touch-icon.png"):
            return self._send(200, web_file(name), TYPES["." + name.rsplit(".", 1)[1]])
        self._send(404, b"not found", "text/plain")

    def _refuse(self):
        self._send(405, b"read only", "text/plain")

    do_PUT = do_DELETE = do_PATCH = _refuse

    def _fence(self) -> str | None:
        """Host + Origin check of orch_ui.origin on every POST. A missing Origin is refused too: the
        dashboard page always sends one, so only a script outside the browser lacks it."""
        try:
            from orch_ui.origin import check_request
        except ImportError:
            return "Actions are not available in this install."
        if self.headers.get("Origin") is None:
            return "This request was refused (no origin)."
        if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return "This request came from another website and was refused."
        return check_request("POST", self.headers, self.server.server_address[1], api=True)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/act":
            return self._refuse()
        why = self._fence()
        if why:
            return self._send(403, why.encode(), "text/plain; charset=utf-8")
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return self._send(415, b"send JSON", "text/plain")
        try:
            n = int(self.headers.get("Content-Length") or "")
            if not 0 < n <= MAX_BODY:
                raise ValueError
            body = json.loads(self.rfile.read(n))
            if not isinstance(body, dict) or set(body) - {"op", "args"}:
                raise ValueError
        except (ValueError, RecursionError, OSError):
            return self._send(400, b"That request could not be read.", "text/plain; charset=utf-8")
        try:
            code, text, extra = actions.run_op(self.root, self.orch_bin, body.get("op"), body.get("args", {}))
        except actions.BadRequest as e:
            return self._send(400, str(e).encode(), "text/plain; charset=utf-8")
        except actions.Unavailable as e:
            return self._send(503, str(e).encode(), "text/plain; charset=utf-8")
        if code != 200:
            hdr = {"X-Revision": str(extra["revision"])} if extra else None
            return self._send(code, text.encode(), "text/plain; charset=utf-8", hdr)
        self._send(200, json.dumps(load_state(self.root, orch_bin=self.orch_bin, fresh=True)).encode(), "application/json")


def make_server(root: Path, port: int = DEFAULT_PORT, orch_bin: str | None = None) -> ThreadingHTTPServer:
    orch_bin = orch_bin if orch_bin is not None else os.environ.get("ORCH_BIN") or None
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, root=root, orch_bin=orch_bin,
                                                            puller=ViewPuller(root, orch_bin)))
