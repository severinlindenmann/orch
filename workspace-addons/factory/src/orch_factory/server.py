"""The Factory page server: loopback only, GET only, fenced like the Insights page (Host/Origin checks, no
cookies, no key, no writes). It runs as a daemon thread inside the watcher process. Every JSON answer is built
by pageapi through flow.derive; a slow orch call returns the last good answer with "stale": true."""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import Future
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import unquote

from . import pageapi
from .store import Refused

BUDGET = 2.0  # seconds one API answer may take before the last good one is returned
KIT_FILES = (
    "tokens.css",
    "components.css",
    "interaction.css",
    "motion.css",
    "components.js",
    "icons.js",
    "overlay.js",
    "select.js",
    "widgets.css",
    "widgets.js",
)
WEB_FILES = ("index.html", "factory.css", "factory.js")
PLAIN = "text/plain; charset=utf-8"
TYPES = {
    "html": "text/html; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "js": "text/javascript",
}
PREFIX = re.compile(r"/addon/[a-z][a-z0-9-]{1,31}")
CSP = "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
ORDER_PATH = re.compile(r"/api/order/(t_[a-z0-9]{6,16})(?:/(draft|file)/(.+))?")


def _web(name):
    return resources.files("orch_factory").joinpath("web", name).read_bytes()


def _kit(name):
    """A kit file from orch_ui's static folder (the one master kit); None when it is not installed."""
    try:
        import orch_ui

        return (Path(orch_ui.__file__).parent / "static" / name).read_bytes()
    except (ImportError, OSError, TypeError):
        pass
    return None


def _local_check(  # keep in sync with orch_ui.origin (test_fallback_fence_matches_shared_rules)
    method, headers, port, *, api=False
):
    """The Host/Origin rules of orch_ui.origin, for installs where orch_ui is not importable."""
    one = {}
    for name in ("host", "origin", "sec-fetch-site"):
        vals = headers.get_all(name) or []
        if len(vals) > 1:
            return "This request was refused (repeated header)."
        one[name] = vals[0] if vals else None
    host = one["host"]
    name, sep, hport = (host or "").rpartition(":")
    if not (host and sep and re.fullmatch(r"[1-9][0-9]{0,4}", hport) and int(hport) <= 65535) or name not in (
        "127.0.0.1",
        "localhost",
    ):
        return f"This address is not allowed. Open orch at http://127.0.0.1:{port}"
    safe = method.upper() in ("GET", "HEAD", "OPTIONS")
    if safe and not api:
        return None
    if not safe and one["origin"] is not None:
        return (
            None
            if one["origin"] == f"http://{host}"
            else "This request came from another website and was refused."
        )
    if one["sec-fetch-site"] not in (None, "same-origin", "none"):
        return "This request came from another website and was refused."
    return None


def check_request(method, headers, port, *, api=False):
    try:
        from orch_ui.origin import check_request as shared
    except ImportError:
        shared = _local_check
    return shared(method, headers, port, api=api)


class Answers:
    """Runs one API build per key at a time under a time budget; keeps the last good answer per key."""

    def __init__(self, budget=None):
        self.budget = budget
        self.last, self.running = {}, {}
        self.lock = threading.Lock()

    def _start(self, key, fn):
        future = Future()

        def work():
            try:
                value = fn()
                if value is not None:
                    with self.lock:
                        self.last[key] = value
                future.set_result(value)
            except BaseException as error:  # noqa: BLE001 - handed to the waiting request
                future.set_exception(error)
            finally:
                with self.lock:
                    if self.running.get(key) is future:
                        del self.running[key]

        with self.lock:  # check and register under one hold: two requests never start two builds
            running = self.running.get(key)
            if running is not None:
                return running
            self.running[key] = future
        threading.Thread(target=work, daemon=True).start()
        return future

    def get(self, key, fn):
        """(answer or None, error text or None). A slow or failed build gives the last good answer (stale)."""
        future = self._start(key, fn)
        try:
            return future.result(timeout=self.budget if self.budget is not None else BUDGET), None
        except TimeoutError:
            error = "Orch is slow to answer."
        except (Refused, OSError, ValueError) as e:
            error = " ".join(str(e).split()) or "Orch did not answer."
        except Exception as e:  # noqa: BLE001 - a bad ticket must not end the page server
            error = f"{type(e).__name__}: {' '.join(str(e).split())}"
        with self.lock:
            old = self.last.get(key)
        if isinstance(old, dict):
            return {**old, "stale": True}, None
        return None, error


class Handler(BaseHTTPRequestHandler):
    """Serve a fixed set of assets and the read-only JSON answers."""

    timeout = 10

    def __init__(self, *args, root, answers, **kwargs):
        self.root, self.answers = root, answers
        super().__init__(*args, **kwargs)

    def __getattr__(self, name):
        if name.startswith("do_"):
            return self._refuse
        raise AttributeError(name)

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype=PLAIN, extra=None):
        self.send_response(code)
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code=200):
        self._send(code, json.dumps(data).encode(), "application/json")

    def _fence(self, method, api):
        return check_request(method, self.headers, self.server.server_address[1], api=api)

    def _built(self, key, fn):
        answer, error = self.answers.get(key, fn)
        if error:
            return self._json({"error": error, "stale": True}, 503)
        if answer is None:
            return self._send(404, b"not found")
        return self._json(answer)

    def do_GET(self):
        path = self.path.partition("?")[0]
        why = self._fence("GET", path.startswith("/api/"))
        if why:
            return self._send(403, why.encode())
        root = self.root
        if path == "/api/home":
            return self._built("home", lambda: pageapi.home(root))
        if path == "/api/autopilot":
            return self._built("autopilot", lambda: pageapi.autopilot_view(root))
        m = ORDER_PATH.fullmatch(path)
        if m:
            order, what, rest = m.groups()
            if what is None:
                return self._built(f"order:{order}", lambda: pageapi.order(root, order))
            if what == "draft":
                out = pageapi.draft(root, order, rest)
                return self._json(out) if out else self._send(404, b"not found")
            out = pageapi.image(root, order, unquote(rest))  # the page sends s1%2Fa.png
            if out is None:
                return self._send(404, b"not found")
            return self._send(200, out[0], out[1])
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
        why = self._fence(self.command, True)
        return self._send(403, why.encode()) if why else self._send(405, b"not allowed")

    do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_TRACE = do_CONNECT = _refuse


def make_server(root: Path, port: int = 0, budget: float | None = None) -> ThreadingHTTPServer:
    """Bind 127.0.0.1 (port 0 = any free port); the caller owns the lifetime."""
    srv = ThreadingHTTPServer(
        ("127.0.0.1", port), partial(Handler, root=Path(root).resolve(), answers=Answers(budget))
    )
    srv.daemon_threads = True
    return srv


def serve_in_thread(srv: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    thread.start()
    return thread
