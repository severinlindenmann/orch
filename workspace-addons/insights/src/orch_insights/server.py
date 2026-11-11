"""Loopback HTTP server, fenced by the shared UI origin checks. Reads go through the CLI; the only writes are the
settings page clicks of POST /api/act (fixed op table in actions.py; the core decides when a human proof is
needed, the server mints one only for a request with the session cookie AND this server's page secret)."""

import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from . import actions
from .lists import KINDS, build_list
from .overview import build_overview
from .settings import build_settings

DEFAULT_PORT = 8431
MAX_BODY = 4096
KIT_FILES = ("tokens.css", "components.css", "icons.js")
WEB_FILES = ("index.html", "insights.css", "insights.js", "settings.js")
PLAIN = "text/plain; charset=utf-8"
RELINK = "This sign-in link can not be used. Open Insights from the dashboard on this computer again."
TYPES = {"html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8", "js": "text/javascript"}
PREFIX = re.compile(r"/addon/[a-z][a-z0-9-]{1,31}")
CSP = "default-src 'self'; frame-ancestors 'none'; base-uri 'none'"


def read_counts(root, orch_bin=None):
    """Read only the CLI answer, using this interpreter's orch unless a test injects an executable."""
    return read_json(root, orch_bin, ["record", "counts", "--days", "30", "--json"])


def read_json(root, orch_bin, argv):
    """One read-only CLI answer as JSON, or None when it fails. Runs with the same cleaned environment as a
    write (M6); when that environment can not be built the read fails (and so counts as unknown)."""
    command = (
        [str(orch_bin)]
        if orch_bin not in (None, actions.SELF)
        else [sys.executable, "-I", "-P", "-m", "orch"]
    )
    try:
        env = actions.human_env(root, actions.real_bin(orch_bin))
    except actions.Unavailable:
        return None
    try:
        result = subprocess.run(
            [*command, *argv],
            cwd=root,
            env=env,
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

    def __init__(self, *args, root, orch_bin, session=None, **kwargs):
        self.root, self.orch_bin, self.session = root, orch_bin, session
        self.nonce = os.environ.get("ORCH_INSIGHTS_NONCE", "")
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
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, code=200):
        self._send(code, json.dumps(data).encode(), "application/json")

    def _can_act(self):
        """This request carries the person's page session: cookie, loopback Host, no proxy headers (can_mint)
        AND this server's page secret in X-Orch-Page (H2). The cookie name is the core's and is not
        port-scoped, so a cookie set for another page server on this computer reaches us too: the header is
        the real guard, the cookie alone never mints."""
        secret = getattr(self.server, "page_secret", None)
        sent = self.headers.get("X-Orch-Page") or ""
        return (
            self.session is not None
            and secret is not None
            and hmac.compare_digest(sent.encode(), secret.encode())
            and self.session.can_mint(self.headers, self.server.server_address[1])
        )

    def _read(self, *argv):
        return read_json(self.root, self.orch_bin, list(argv))

    def _settings_view(self):
        settings = self._read("record", "settings", "--json")
        counts = read_counts(self.root, self.orch_bin)
        tickets = self._read("ticket", "list", "--all", "--json")
        return build_settings(settings, counts, tickets, self._can_act())

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
        if path == "/api/settings":
            return self._json(self._settings_view())
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

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_TRACE = do_CONNECT = _refuse

    def _session_refusal(self):
        """Why POST /session is refused: the action fence, plus Sec-Fetch-Site same-origin/none (absent is
        refused too) and a JSON body (M5), loopback Host and no proxy headers."""
        why = self._fence("POST", True)
        if why:
            return why
        if self.headers.get("Sec-Fetch-Site") not in ("same-origin", "none"):
            return "This request came from another website and was refused."
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return "forbidden"
        from orch.pageproof import forwarded, host_ok

        if (
            self.session is None
            or forwarded(self.headers)
            or not host_ok(self.headers, self.server.server_address[1])
        ):
            return "forbidden"
        return None

    def _session_post(self):
        """POST /session: the page hands over the one-time launch token from its URL fragment; the server spends
        it, sets the session cookie (H1) and returns this server's page secret in the body (H2). The page keeps
        the secret in memory only and sends it as X-Orch-Page; it is never logged."""
        why = self._session_refusal()
        if why:
            return self._send(403, why.encode())
        try:
            n = int(self.headers.get("Content-Length") or "")
            token = json.loads(self.rfile.read(n)).get("token") if 0 < n <= 200 else None
        except (ValueError, AttributeError, OSError, RecursionError):
            token = None
        cookie = self.session.launch(token)
        if not cookie:
            if getattr(self.session, "revoked", False):
                self.server.page_secret = None  # a reused link ended the session: the secret goes with it
            return self._send(403, RELINK.encode())
        secret = self.server.new_page_secret()
        body = json.dumps({"secret": secret}).encode()
        cookie_header = self.session.set_cookie(self.server.server_address[1], cookie)
        self._send(200, body, "application/json", extra={"Set-Cookie": cookie_header})

    def _body(self):
        """The JSON body {op, args}, or None for anything else (size, type, extra keys)."""
        try:
            n = int(self.headers.get("Content-Length") or "")
            if not 0 < n <= MAX_BODY:
                return None
            body = json.loads(self.rfile.read(n))
        except (ValueError, RecursionError, OSError):
            return None
        if not isinstance(body, dict) or set(body) - {"op", "args"}:
            return None
        return body

    def _act_refusal(self):
        why = self._fence("POST", True)
        if why:
            return 403, why
        if (self.headers.get("Sec-Fetch-Site") or "same-origin") not in ("same-origin", "none"):
            return 403, "This request came from another website and was refused."
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return 415, "send JSON"
        return None

    def _act(self):
        refusal = self._act_refusal()
        if refusal:
            return self._send(refusal[0], refusal[1].encode())
        body = self._body()
        if body is None:
            return self._send(400, b"That request could not be read.")
        mint = self.session.mint if self._can_act() else None  # handed over; called only on needs_person
        try:
            code, text, result = actions.run_op(
                self.root, self.orch_bin, body.get("op"), body.get("args", {}), mint=mint, read=self._read
            )
        except actions.NeedsPerson as e:
            return self._send(403, str(e).encode())
        except actions.BadRequest as e:
            return self._send(400, str(e).encode())
        except actions.Unavailable as e:
            return self._send(503, str(e).encode())
        if code != 200:
            return self._send(code, text.encode())
        return self._json({"result": result})

    def do_POST(self):
        path = self.path.partition("?")[0]
        if path == "/session":
            return self._session_post()
        if path == "/api/act":
            return self._act()
        return self._refuse()


def _page_session(root, orch_bin):
    """The person's page session for the real server; None (watch-only) for a test fake or when the installed
    core does not allow Insights to hold the key yet (PageSession raises ValueError)."""
    if orch_bin not in (None, actions.SELF):
        return None
    try:
        from orch.pageproof import PageSession

        return PageSession(root, "insights")
    except (ImportError, ValueError):
        return None


class InsightsServer(ThreadingHTTPServer):
    """The HTTP server plus this instance's page secret (H2): created only after a launch token was spent,
    kept in memory, never logged."""

    page_secret = None
    _secret_lock = threading.Lock()

    def new_page_secret(self) -> str:
        with self._secret_lock:
            if self.page_secret is None:
                self.page_secret = secrets.token_urlsafe(32)
            return self.page_secret


def make_server(root: Path, port: int = DEFAULT_PORT, orch_bin=None, session=None) -> ThreadingHTTPServer:
    """Construct the server; callers own its lifetime. Tests may inject a fake CLI path and a fake session."""
    root = root.resolve()
    session = session if session is not None else _page_session(root, orch_bin)
    srv = InsightsServer(("127.0.0.1", port), partial(Handler, root=root, orch_bin=orch_bin, session=session))
    srv.session = session
    return srv
