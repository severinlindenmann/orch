"""Read-only loopback HTTP server, fenced by the shared UI origin checks."""

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from .lists import KINDS, build_list
from .overview import build_overview

DEFAULT_PORT = 8431
KIT_FILES = ("tokens.css", "components.css", "icons.js")
WEB_FILES = ("index.html", "insights.css", "insights.js")
TYPES = {"html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8", "js": "text/javascript"}
PREFIX = re.compile(r"/addon/[a-z][a-z0-9-]{1,31}")
CSP = "default-src 'self'; frame-ancestors 'none'; base-uri 'none'"


def read_counts(root, orch_bin=None):
    """Read only the CLI answer, using this interpreter's orch unless a test injects an executable."""
    command = [str(orch_bin)] if orch_bin is not None else [sys.executable, "-I", "-P", "-m", "orch"]
    try:
        result = subprocess.run(
            [*command, "record", "counts", "--days", "30", "--json"],
            cwd=root,
            env={**os.environ, "ORCH_ROOT": str(root)},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=10,
            check=False,
        )
        return json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError, RecursionError, subprocess.TimeoutExpired):
        return None


def _web(name):
    return resources.files("orch_insights").joinpath("web", name).read_bytes()


def _kit(name):
    import orch_ui

    return (Path(orch_ui.__file__).parent / "static" / name).read_bytes()


class Handler(BaseHTTPRequestHandler):
    """Serve a fixed set of assets and one counts projection."""

    timeout = 10

    def __init__(self, *args, root, orch_bin, **kwargs):
        self.root, self.orch_bin = root, orch_bin
        self.nonce = os.environ.get("ORCH_INSIGHTS_NONCE", "")
        super().__init__(*args, **kwargs)

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self._refuse
        raise AttributeError(name)

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data):
        self._send(200, json.dumps(data).encode(), "application/json")

    def _fence(self, method, api):
        try:
            from orch_ui.origin import check_request
        except ImportError:
            return "Insights is not available in this install."
        why = check_request(method, self.headers, self.server.server_address[1], api=api)
        if method == "POST" and self.headers.get("Origin") is None:
            return why or "This request was refused (no origin)."
        return why

    def do_GET(self):
        path = self.path.partition("?")[0]
        why = self._fence("GET", path.startswith("/api/") or path == "/ready")
        if why:
            return self._send(403, why.encode())
        if path == "/ready" and self.nonce:
            challenge = self.path.partition("?c=")[2]
            if not re.fullmatch(r"[0-9a-f]{32,64}", challenge):
                return self._send(404, b"not found")
            mac = hmac.new(self.nonce.encode(), challenge.encode(), hashlib.sha256).hexdigest()
            return self._json({"pid": os.getpid(), "mac": mac})
        if path == "/api/overview":
            return self._json(build_overview(read_counts(self.root, self.orch_bin)))
        if path.startswith("/api/list/") and path[10:] in KINDS:
            return self._json(build_list(read_counts(self.root, self.orch_bin), path[10:]))
        if path == "/":
            prefix = self.headers.get("X-Forwarded-Prefix") or ""
            prefix = prefix if PREFIX.fullmatch(prefix) else ""
            return self._send(200, _web("index.html").replace(b"__P__", prefix.encode()), TYPES["html"])
        if path.startswith("/kit/") and path[5:] in KIT_FILES:
            return self._send(200, _kit(path[5:]), TYPES[path.rsplit(".", 1)[1]])
        if path.startswith("/web/") and path[5:] in WEB_FILES:
            return self._send(200, _web(path[5:]), TYPES[path.rsplit(".", 1)[1]])
        return self._send(404, b"not found")

    def _refuse(self):
        why = self._fence(self.command, True)
        return self._send(403, why.encode()) if why else self._send(405, b"not allowed")

    do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_TRACE = do_CONNECT = _refuse


def make_server(root: Path, port: int = DEFAULT_PORT, orch_bin=None) -> ThreadingHTTPServer:
    """Construct the server; callers own its lifetime, and tests may inject a fake CLI path."""
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, root=root.resolve(), orch_bin=orch_bin))
