"""Loopback HTTP server, fenced by the shared UI origin checks. Reads go through the CLI; the only writes are the
settings page clicks of POST /api/act (fixed op table in actions.py; a write needs the session cookie AND this
server's page secret)."""

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from . import actions
from .checkup import build_checkup, build_show
from .lists import KINDS, build_list
from .models import build_models, build_week
from .overview import build_overview, retries_view
from .settings import build_settings

DEFAULT_PORT = 8431
MAX_BODY = 4096
KIT_FILES = (
    "frame.js",
    "tokens.css",
    "components.css",
    "motion.css",
    "interaction.css",
    "icons.js",
    "overlay.js",
    "select.js",
    "components.js",
    "widgets.css",
    "widgets.js",
    "date.js",
)
WEB_FILES = ("index.html", "insights.css", "insights.js", "settings.js", "checkup.js")
PLAIN = "text/plain; charset=utf-8"
RELINK = "This sign-in link can not be used. Open Insights again from the dashboard."
SIGNIN = "Sign in to do this: open the dashboard with a sign-in link from orch."  # the page shows the sign-in notice
TYPES = {
    "html": "text/html; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "js": "text/javascript",
}
PREFIX = re.compile(r"/addon/[a-z][a-z0-9-]{1,31}")
CSP = "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"


def chosen_person(root):
    """The name picked as "You" in the dashboard (ORCH-410), kept in the orch home keyed by this workspace; None
    when nobody is chosen or it cannot be read. Tickets without an owner are shown under it."""
    try:
        from orch import addons
        from orch.config import _perm_key

        d = json.loads((addons.home() / "people.json").read_text(encoding="utf-8"))
        name = d.get(_perm_key(root)) if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001 - no usable orch home: nobody chosen
        return None
    return " ".join(name.split())[:40] if isinstance(name, str) and name.strip() else None


COUNTS_FRESH = 5.0  # seconds one counts answer serves every read of it (the page asks up to four at once)
_COUNTS: dict[tuple, tuple[float, object]] = {}
_COUNTS_LOCK = threading.Lock()
_COUNTS_ASKING: dict[tuple, threading.Lock] = {}
_FORGOTTEN = [0]  # how many times a click forgot the counts


def read_counts(root, orch_bin=None):
    """Read only the CLI answer, using this interpreter's orch unless a test injects an executable. The page asks
    for it up to four times at once when it opens (overview, skills, connections, keys): one read answers them
    all, and stays the answer for a few seconds (ORCH-2288: four commands side by side at 10,000 tickets)."""
    key = (str(root), str(orch_bin))
    with _COUNTS_LOCK:
        asking = _COUNTS_ASKING.setdefault(key, threading.Lock())
    with asking:  # a read already on its way: wait for its answer instead of starting another
        hit = _COUNTS.get(key)
        if hit and time.monotonic() - hit[0] < COUNTS_FRESH:
            return hit[1]
        generation = _FORGOTTEN[0]
        got = read_json(root, orch_bin, ["record", "counts", "--days", "30", "--json"])
        with _COUNTS_LOCK:
            if got is None or generation != _FORGOTTEN[0]:
                # a failed read is never kept, nor one that began before a click forgot the counts
                _COUNTS.pop(key, None)
            else:
                _COUNTS[key] = (time.monotonic(), got)
        return got


def forget_counts():
    """A click may change what the counts say (a setting, a proposal): the next read asks again, and a read
    already on its way when the click ended is not kept."""
    with _COUNTS_LOCK:
        _FORGOTTEN[0] += 1
        _COUNTS.clear()


def read_ticket_titles(root, orch_bin=None):
    """Every ticket's id and title. From the core's ticket index (ORCH-521) in this interpreter when there is
    one (ORCH-522: `orch ticket list --all --json` reads every ticket in full, 11 s at 10,000); else the CLI."""
    if orch_bin in (None, actions.SELF):
        try:
            from orch import ticketindex

            return [{"id": r.get("id"), "title": r.get("title")} for r in ticketindex.rows(Path(root))]
        except Exception:  # noqa: BLE001, S110 - no index (an older core) or a broken one: the command answers
            pass
    return read_json(root, orch_bin, ["ticket", "list", "--all", "--json"])


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
    if orch_bin in (None, actions.SELF):
        got = _by_worker(root, argv, env)
        if got is not _MISS:
            return got
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


_MISS = object()


def _by_worker(root, argv, env):
    """The read answered by this interpreter's orch (orch.reads.call: in this process or by one long-lived read
    worker), with the same cleaned environment, instead of a new Python process per read (ORCH-2288: the page
    started six at once when it opened). _MISS: the worker could not answer; the command runs as before."""
    try:
        from orch import reads
    except ImportError:
        return _MISS
    if not hasattr(reads, "call"):
        return _MISS
    try:
        got = reads.call(Path(root), list(argv), timeout=10, environ=env)
    except Exception:  # noqa: BLE001 - whatever went wrong: the command gets its chance
        return _MISS
    if got is None:
        return _MISS
    code, value = got
    return value if code == 0 else None


def _web(name):
    return resources.files("orch_insights").joinpath("web", name).read_bytes()


def _kit(name):
    """A kit file from orch_ui's static folder (the one master kit); None when it is not installed."""
    try:
        import orch_ui

        return (Path(orch_ui.__file__).parent / "static" / name).read_bytes()
    except (ImportError, OSError, TypeError):
        pass
    return None


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

    def _marked(self, data):
        """The overview and the lists carry a short mark of this workspace (a hash, never the path): a page that
        sees the mark change drops what it read before (another workspace answers on this address now)."""
        if isinstance(data, dict) and "error" not in data:  # an error answer holds nothing to drop
            data["ws"] = hashlib.sha256(str(Path(self.root).resolve()).encode()).hexdigest()[:12]
        return data

    def _can_act(self):
        """This request is the person's, from any computer: the dashboard in front vouches for it, or it carries
        this server's own page session (cookie AND page secret, once handed out by a sign-in). The rule lives
        in PageSession (the cookie alone never counts: every port of the host receives it)."""
        if self.session is None or not self.session.active:
            return False
        if self.session.vouched(self.headers):
            return True
        return getattr(self.server, "page_secret", None) is not None and self.session.can_act(
            self.headers, self.server.server_address[1]
        )

    def _may_read(self):
        """Every data read needs the sign-in: this server's session cookie, or the dashboard's word for the person
        in front of it. This computer's own address is no sign-in (ORCH-481, owner 18 Nov): ticket files are
        private on disk and any local user or process reaches 127.0.0.1. Only the page shell and its program
        files open without it."""
        return self.session is not None and self.session.may_read(self.headers, self.server.server_address[1])

    def _read(self, *argv):
        return read_json(self.root, self.orch_bin, list(argv))

    def _settings_view(self):
        settings = self._read("record", "settings", "--json")
        counts = read_counts(self.root, self.orch_bin)
        tickets = read_ticket_titles(self.root, self.orch_bin)
        return build_settings(settings, counts, tickets, self._can_act())

    def _fence(self, method, api, at_login=False):
        try:
            from orch_ui.origin import check_request
        except ImportError:
            return "Insights is not available in this install."
        port = self.server.server_address[1]
        signed_in = at_login or bool(self.session is not None and self.session.cookie_ok(self.headers, port))
        why = check_request(method, self.headers, port, api=api, signed_in=signed_in)
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
        if path.startswith("/api/") and not self._may_read():
            return self._send(401, SIGNIN.encode(), extra={"WWW-Authenticate": 'OrchPage realm="orch"'})
        if path == "/api/overview":
            # the two reads side by side: each is a process of its own (ORCH-1621: one after the other)
            with ThreadPoolExecutor(max_workers=2) as pool:
                retries = pool.submit(
                    read_json, self.root, self.orch_bin, ["github", "retries", "--days", "30", "--json"]
                )
                view = build_overview(read_counts(self.root, self.orch_bin))
                if "error" not in view:
                    view["retries"] = retries_view(retries.result())
            return self._json(self._marked(view))
        if path == "/api/week":
            return self._json({"week": build_week(self._read("usage", "list", "--json"))})
        if path == "/api/models":
            return self._json(
                build_models(self._read("tokens", "--days", "30", "--json"), chosen_person(self.root))
            )
        if path.startswith("/api/list/") and path[10:] in KINDS:
            return self._json(self._marked(build_list(read_counts(self.root, self.orch_bin), path[10:])))
        if path == "/api/checkup":
            return self._json(build_checkup(self._read("insights", "checkup", "list", "--json")))
        if path.startswith("/api/checkup/") and actions.PROPOSAL.fullmatch(path[13:]):
            shown = build_show(self._read("insights", "checkup", "show", path[13:], "--json"))
            return self._json(shown) if shown else self._send(404, b"not found")
        if path == "/api/settings":
            return self._json(self._settings_view())
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

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_TRACE = do_CONNECT = _refuse

    def _site_refusal(self):
        """The one Sec-Fetch-Site rule of every POST: same-origin or none; an absent header is refused too."""
        if self.headers.get("Sec-Fetch-Site") not in ("same-origin", "none"):
            return "This request came from another website and was refused."
        return None

    def _session_refusal(self):
        """Why POST /session is refused: the action fence, plus Sec-Fetch-Site same-origin/none (absent is
        refused too) and a JSON body (M5). From any computer: the one-time token is the proof."""
        why = self._fence("POST", True, at_login=True)
        if why:
            return why
        why = self._site_refusal()
        if why:
            return why
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return "forbidden"
        if self.session is None:
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
            if getattr(self.session, "active", True) is False:  # a helper started this server: watch-only
                from orch.pagesession import WATCH_ONLY_MSG

                return self._send(403, WATCH_ONLY_MSG.encode())
            return self._send(403, RELINK.encode())
        secret = self.session.secret  # the core's page secret (PageSession); one rule, one place
        self.server.page_secret = secret
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
        why = self._site_refusal()
        if why:
            return 403, why
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
        session = self._can_act()
        try:
            code, text, result = actions.run_op(
                self.root,
                self.orch_bin,
                body.get("op"),
                body.get("args", {}),
                session=session,
                read=self._read,
            )
        except actions.NeedsPerson as e:
            return self._send(403, str(e).encode())
        except actions.BadRequest as e:
            return self._send(400, str(e).encode())
        except actions.Unavailable as e:
            return self._send(503, str(e).encode())
        forget_counts()
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
        from orch.pagesession import PageSession

        return PageSession(root, "insights")
    except (ImportError, ValueError):
        return None


class InsightsServer(ThreadingHTTPServer):
    """The HTTP server; `page_secret` is set once a launch token was spent (it is the PageSession's secret) and
    reset when a reused link ends the session."""

    page_secret = None
    # the page loads a dozen files at once; the default queue of 5 resets connections on macOS (as the dashboard)
    request_queue_size = 128


def make_server(root: Path, port: int = DEFAULT_PORT, orch_bin=None, session=None) -> ThreadingHTTPServer:
    """Construct the server; callers own its lifetime. Tests may inject a fake CLI path and a fake session."""
    root = root.resolve()
    session = session if session is not None else _page_session(root, orch_bin)
    srv = InsightsServer(("127.0.0.1", port), partial(Handler, root=root, orch_bin=orch_bin, session=session))
    srv.session = session
    return srv
