"""Stdlib HTTP server on 127.0.0.1. GET reads; the only POST is /api/act (the fixed op table in actions.py)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import threading
import time
from functools import partial
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, unquote

from . import actions, copychanges, diagapi, framepass, reffiles, selfupdate, ticketfiles
from .data import (
    forget_static,
    load_addons,
    load_chat_day,
    load_chat_days,
    load_links,
    load_services,
    load_state,
    patch_ticket,
)
from .events import Revisions
from .state_cache import StateCache
from .views import ViewPuller

try:  # the core's debug log; a dashboard that cannot import it simply writes none
    from orch import diag
except ImportError:  # pragma: no cover
    diag = None

DEFAULT_PORT = 8420
MAX_BODY = 16384  # every action but the ones below
MAX_BIG_BODY = (
    140 * 1024 * 1024
)  # a new ticket with files: at most 100 MB of files (newticket.js) as base64, plus the text
LEAN_OPS = ("chat.send_ws", "chat.sync_ws", "workspace.propose")
# ops that name a ticket but change more than it (settings, add-ons, the workspace): answered with a full build
WIDE_OPS = ("addon.act", "addon.set", "addon.uninstall", "addon.start", "update.start")
BIG_OPS = ("ticket.new", "ticket.paste", "ticket.attach", "link.share")
_BIG_READS = threading.BoundedSemaphore(1)
KIT_NAME = re.compile(r"(?:samples/)?[A-Za-z0-9][A-Za-z0-9._-]*")  # one file name, or one under samples/
KIT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".csv": "text/csv; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".webm": "video/webm",
    ".wav": "audio/wav",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
}
# The gallery is a fixed static page of the master kit (no data from the workspace): inline styles are allowed there.
GALLERY_CSP = (
    "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self' 'unsafe-inline'; "
    "object-src 'self'; frame-src 'self'; frame-ancestors 'self'"
)


def _traceparent() -> str | None:
    try:
        return diag.traceparent() if diag else None
    except Exception:  # noqa: BLE001 - never stops an answer
        return None


def kit_dir() -> Path | None:
    """The master kit: orch_ui's static folder (the dashboard keeps no copy of it)."""
    try:
        import orch_ui

        return Path(orch_ui.__file__).resolve().parent / "static"
    except (ImportError, OSError, TypeError):
        return None


def kit_file(name: str) -> tuple[bytes, str] | None:
    """(bytes, content type) of a kit file by its name under kit/, or None. Only plain names (and samples/<name>)."""
    root = kit_dir()
    if root is None or not KIT_NAME.fullmatch(name) or name.startswith("demo"):
        return None
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    ctype = TYPES.get(ext) or KIT_TYPES.get(ext)
    top = not name.startswith("samples/")
    if ctype is None or (top and ext not in (".css", ".js", ".html", ".md")):
        return None
    path = (root / name).resolve()
    try:
        path.relative_to(root)
        return path.read_bytes(), ctype
    except (ValueError, OSError):
        return None


TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


PROXY = re.compile(r"/addon/([a-z][a-z0-9-]{1,31})(/(?:[A-Za-z0-9_./-]|%20)*)?")
# An add-on may show an agent's page in a sandboxed frame (no same-origin): the frame and the files it loads come
# with an opaque origin, so their requests are cross-site. Only GET of /page/<ticket>/<key>/<file> is let through for
# that, and only when the add-on answers with its own sandbox Content-Security-Policy, which is then kept, not
# replaced; any other answer to such a request is a 403.
PAGE_PATH = re.compile(r"/page/t_[a-z0-9]{6,16}/[0-9a-f]{16}/.+")  # ticket, key (unguessable), file
LOCAL = re.compile(r"http://(?:127\.0\.0\.1|localhost):(\d{1,5})/?")
PROXY_CSP = "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; frame-ancestors 'self'; base-uri 'none'"
# The page of an add-on orch ships runs sandboxed too (ORCH-186): its own origin is opaque, so it can never read the
# dashboard's page secret or reach into the dashboard page; it acts with a frame pass (framepass.py). The same flags
# are on the dashboard's iframe (settings.js SHIPPED_SANDBOX); the header keeps the page sandboxed when opened alone.
SHIPPED_SANDBOX = (
    "sandbox allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads"
)
FRAME_DEST = ("script", "style", "font", "image")  # what a sandboxed add-on page loads of its own code
PROXY_BODY = 16384


def _sandboxed(csp: str | None) -> bool:
    """A real `sandbox` directive without allow-same-origin/top-navigation/popups/forms (not just the word)."""
    for d in (csp or "").split(";"):
        tok = d.split()
        if tok and tok[0].lower() == "sandbox":
            bad = {
                "allow-same-origin",
                "allow-top-navigation",
                "allow-popups",
                "allow-forms",
                "allow-top-navigation-by-user-activation",
                "allow-popups-to-escape-sandbox",
            }
            return not bad & {t.lower() for t in tok[1:]}
    return False


PROXY_MAX_REPLY = 4 * 1024 * 1024


def web_file(name: str) -> bytes:
    return resources.files("orch_dashboard").joinpath("web", name).read_bytes()


def page_asset(name: str) -> bytes:
    """A file the page links: kit/<file> comes from the master kit (orch_ui), anything else from web/."""
    if name.startswith("kit/"):
        got = kit_file(name[4:])
        if got is None:
            raise FileNotFoundError(name)
        return got[0]
    return web_file(name)


_PORTS: dict[tuple[str, str], tuple[float, int | None, object]] = {}
PORT_KEEP = 60.0  # seconds a running add-on's port is remembered: `orch status` costs about 0.2 s
# Files a browser may keep for a minute: an add-on page's own styles, scripts and pictures (never its pages or data)


def _services_stamp():
    """A fingerprint of orch's own record of what runs (running.json: size and time). It changes whenever an add-on
    starts, stops or restarts, so a remembered port is trusted only while it is the same. None = cannot tell."""
    try:
        from orch import addons

        st = (addons.home() / "running.json").stat()
        return (st.st_mtime_ns, st.st_size)
    except Exception:  # noqa: BLE001 - no orch here, no file, an untrusted home: then nothing is remembered
        return None


STATIC_EXT = (".css", ".js", ".svg", ".png", ".ico", ".woff", ".woff2")


TYPING_OFF = (
    "Typing into the helper's screen is off. "
    "Turn on 'Let me type into the helper's screen' in Settings \u2192 Add-ons, on the page of the add-on that shows this screen."
)


def _typing_allowed(root) -> bool:
    """The session_typing setting, a plain one (off unless the workspace turned it on)."""
    from orch import config

    return bool(config.focus_session_typing(root))  # an unreadable config file counts as off (the default)


def _link_msg(session, name: str) -> bytes:
    from orch.pagesession import REVOKED_MSG

    if session.revoked:
        return REVOKED_MSG.encode()
    return f"This link was already used. Open the {name} again from orch.".encode()


# Ops that reinstall orch's tool env and so restart the running services, this server too (an add-on add/remove).
RESTARTING_OPS = ("addon.set", "addon.uninstall")
# What a browser that has not signed in may load under a host name that is not this computer's (a proxy in front):
# the page shell only, no data. Everything else there needs the session cookie of that host name.
_PRIVATE_PREFIXES = ("/api/", "/view/", "/addon/", "/page/", "/ready", "/styleguide")


def _arm_resume(root: Path, session) -> None:
    """Like the Update button: the restarted server adopts this tab's session once (15 min, one use), so the
    open tabs keep working after the add-on change restarts it. Written only for a click with a page session."""
    import contextlib

    with contextlib.suppress(Exception):  # without it the restarted server falls back to the kept session
        from orch import pagelaunch

        pagelaunch.write_resume_cookie(root, session.server, session.cookie, session.secret)
        pagelaunch.arm_restart(root)  # the other page server hands its tabs over too (#705)


class Handler(BaseHTTPRequestHandler):
    timeout = 10  # a short body must not hold a thread

    def __init__(self, *a, root: Path, orch_bin: str | None, puller: ViewPuller, session=None, **kw):
        self.root, self.orch_bin, self.puller, self.session = root, orch_bin, puller, session
        self.nonce = os.environ.get("ORCH_DASHBOARD_NONCE", "")
        if diag:
            diag.bind(root, "dashboard")
        super().__init__(*a, **kw)

    def _trace(self) -> None:
        """One trace per request (an incoming valid traceparent is joined) and one debug-log event (no query string)."""
        if not diag:
            return
        diag.new_trace(self.headers.get("traceparent"))
        if self.path.startswith("/api/diag"):  # the page's own trail is not logged again as a request
            return
        diag.log(
            "dashboard.request",
            "debug",
            method=getattr(self, "command", ""),
            path="/go/<hidden>" if self.path.startswith("/go/") else self.path.split("?", 1)[0][:200],
        )

    def log_message(self, *a):  # quiet
        pass

    def _refused_text(self, text: str) -> str:
        """The words of a 403 for a missing page session: a sign-in link that was used twice, else sign in."""
        from orch.pagesession import REVOKED_MSG

        session = getattr(self, "session", None)
        if session is not None and session.revoked:
            return REVOKED_MSG
        return text

    def _act_log(self, text: str) -> None:
        """One line per /api/act on stderr (op name, status, ms): never the arguments."""
        try:
            print("act " + text, file=sys.stderr, flush=True)
        except (OSError, ValueError):
            pass

    def _send(self, code, body: bytes, ctype: str, extra: dict | None = None, csp: str | None = None):
        act = getattr(self, "_act", None)
        if act is not None:
            self._act = None
            self._act_log(f"{act[0]} end status={code} ms={int((time.monotonic() - act[1]) * 1000)}")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", (extra or {}).get("Cache-Control", "no-store"))
        self.send_header("X-Content-Type-Options", "nosniff")
        tp = _traceparent()  # the request's trace id, so the page can tie a click to its request in the log
        if tp:
            self.send_header("traceparent", tp)
        for k, v in (extra or {}).items():
            if k != "Cache-Control":
                self.send_header(k, v)
        if getattr(
            self, "_frame_cors", False
        ):  # a sandboxed add-on page (origin "null") may read this answer
            self.send_header("Access-Control-Allow-Origin", "null")
            self.send_header("Vary", "Origin")
        self.send_header(
            "Content-Security-Policy",
            csp or "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; frame-ancestors 'self'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self, path: str = "/") -> bool:
        """DNS-rebinding guard. This computer's names always pass. Any other well-formed name (a proxy in front,
        another computer) passes with this server's session cookie, or for the page shell alone (no data):
        after the sign-in it does not matter where the browser is."""
        raw = (self.headers.get("Host") or "").strip().lower()
        host = raw.rsplit("]", 1)[0] + "]" if raw.startswith("[") else raw.split(":", 1)[0]
        if host in ("127.0.0.1", "localhost", "[::1]") and not self._remote():
            return True
        try:
            from orch_ui.origin import any_host_ok
        except ImportError:
            return False
        if not any_host_ok(raw):
            return False
        if self._signed_in() or getattr(self, "_frame", None) or self._frame_static(path):
            return True
        # a sandboxed ticket page's own files: its origin is opaque, so the browser sends no cookie with them
        # (a cross-site load an attacker's page can show but never read); the page document itself needs one
        px = PROXY.fullmatch(path)
        if px and PAGE_PATH.fullmatch(px.group(2) or ""):  # an unguessable key in the address
            return True
        if (
            not self._remote()  # browser headers anyone can forge prove nothing on the port for other computers
            and path.startswith("/view/")
            and self.headers.get("Sec-Fetch-Site") in ("same-site", "cross-site")
            and self.headers.get("Sec-Fetch-Dest") in ticketfiles.PAGE_SUBRESOURCE_DEST
            and not path.lower().endswith((".html", ".htm"))
        ):
            return True
        return path == "/" or (
            not path.startswith(_PRIVATE_PREFIXES) and path.lower().endswith((*STATIC_EXT, ".html"))
        )

    def _refuse_host(self):
        """The answer when _host_ok says no. A well-formed host name (a proxy, another computer) only lacks the
        sign-in: 401 with the sign-in words, so the page can say so. A malformed Host is 421 (misdirected)."""
        try:
            from orch.pagesession import SIGNIN_MSG
            from orch_ui.origin import any_host_ok
        except ImportError:
            return self._send(421, b"misdirected request", "text/plain")
        if not any_host_ok((self.headers.get("Host") or "").strip()):
            return self._send(421, b"misdirected request", "text/plain")
        return self._send(
            401,
            self._refused_text(SIGNIN_MSG).encode(),
            "text/plain; charset=utf-8",
            {"WWW-Authenticate": 'OrchPage realm="orch"', "Cache-Control": "no-store"},
        )

    def _remote(self) -> bool:
        """This request came in on the port for other computers (remote listening, opt-in). There a name of
        this computer in Host proves nothing (any computer can send it), so nothing is trusted for it."""
        return bool(getattr(getattr(self, "server", None), "remote", False))

    def _page_port(self) -> int:
        """The port the session belongs to (cookie name, kept session): the loopback port, also for a request
        on the port for other computers, so one sign-in counts on both."""
        return getattr(self.server, "page_port", None) or self.server.server_address[1]

    def _signed_in(self) -> bool:
        """This server's session cookie (no page secret needed): enough to READ under any host name."""
        if getattr(self, "session", None) is None:  # a server without a page session: nobody signs in
            return False
        return self.session.cookie_ok(self.headers, self._page_port())

    def _can_act(self) -> bool:
        """The person's session (cookie + page secret), wherever the browser is; or a frame pass that may act,
        already checked for this request's add-on (_frame_begin)."""
        frame = getattr(self, "_frame", None)
        if frame is not None:
            return frame[1]
        if getattr(self, "session", None) is None:
            return False
        return self.session.can_act(self.headers, self._page_port())

    def _frame_begin(self, path: str, query: str = "") -> None:
        """Per request (a connection can carry several): the frame pass this request carries, checked for its
        path. `_frame` = (add-on, may act) or None. A pass that is sent but not valid (expired, another add-on,
        another sign-in) answers 401 readable by the frame, so the page asks the dashboard for a new one."""
        self._frame, self._frame_cors, self._frame_bad = None, False, False
        value = self.headers.get(framepass.FRAME_HEADER)
        if value is None and getattr(self, "command", "") == "GET" and query:
            value = (parse_qs(query).get(framepass.FRAME_PARAM) or [None])[0]
        if value is None:
            return
        passes = getattr(getattr(self, "server", None), "frame_passes", None)
        hit = None
        if passes is not None and self.headers.get("Origin") in (None, "null"):
            hit = passes.check(value, framepass.session_tag(getattr(self, "session", None)))
        px = PROXY.fullmatch(path)
        if hit and ((px and px.group(1) == hit[0]) or (not px and path in framepass.FRAME_ROOT_PATHS)):
            self._frame, self._frame_cors = hit, True
        else:
            self._frame_bad = True
            self._frame_cors = self.headers.get("Origin") == "null"

    def _frame_refused(self):
        from orch.pagesession import SIGNIN_MSG

        return self._send(401, SIGNIN_MSG.encode(), "text/plain; charset=utf-8")

    def _frame_static(self, path: str) -> bool:
        """The code of a page orch ships (script, style, font, picture), loaded by that page in its sandboxed
        frame: an opaque origin sends no cookie. Only files with those endings, never under /api/; no data."""
        px = PROXY.fullmatch(path)
        rest = (px.group(2) or "") if px else ""
        return bool(
            px
            and getattr(self, "command", "") == "GET"
            and self.headers.get("Sec-Fetch-Dest") in FRAME_DEST
            and rest.lower().endswith(STATIC_EXT)
            and not rest.startswith(("/api/", "/page/"))
            and ".." not in rest
            and self._shipped(px.group(1))
        )

    def _frame_pass_post(self):
        """POST /api/frame-pass {"addon": name}: the dashboard page asks for a pass for the shipped add-on page
        it is about to show. Only the dashboard page itself (same origin, never a frame); a signed-in page gets
        a pass that acts, a page without sign-in on this computer a read-only one (it could read anyway)."""
        if getattr(self, "_frame", None) or self._frame_bad or self.headers.get(framepass.FRAME_HEADER):
            return self._send(403, b"forbidden", "text/plain")
        why = self._fence()
        if why:
            return self._send(403, why.encode(), "text/plain; charset=utf-8")
        try:
            n = int(self.headers.get("Content-Length") or "")
            body = json.loads(self.rfile.read(n)) if 0 < n <= 200 else None
            name = body.get("addon") if isinstance(body, dict) else None
            if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", name):
                raise ValueError
        except (ValueError, OSError):
            return self._send(400, b"That request could not be read.", "text/plain; charset=utf-8")
        if not any(
            a["name"] == name and a.get("shipped") is True and a.get("page")
            for a in load_addons(self.root, self.orch_bin)
        ):
            return self._send(404, b"not found", "text/plain")
        session = getattr(self, "session", None)
        act = session is not None and session.can_act(self.headers, self._page_port())
        raw = (self.headers.get("Host") or "").strip().lower()
        host = raw.rsplit("]", 1)[0] + "]" if raw.startswith("[") else raw.split(":", 1)[0]
        local_read = host in ("127.0.0.1", "localhost", "[::1]") and not self._remote()
        if not (act or local_read or self._signed_in()):
            from orch.pagesession import SIGNIN_MSG

            return self._send(403, self._refused_text(SIGNIN_MSG).encode(), "text/plain; charset=utf-8")
        passes = getattr(self.server, "frame_passes", None)
        if passes is None:
            return self._send(503, b"Try again in a moment.", "text/plain")
        value = passes.mint(name, act, framepass.session_tag(session))
        self._send(200, json.dumps({"pass": value, "act": act}).encode(), "application/json")

    def do_OPTIONS(self):
        """The preflight of a sandboxed add-on page's call (origin "null", the X-Orch-Frame header). It carries
        no pass; the call itself is checked. Anything else: not allowed."""
        self._trace()
        self._frame, self._frame_cors, self._frame_bad = None, False, False
        path = self.path.split("?", 1)[0]
        px = PROXY.fullmatch(path)
        asked = {
            h.strip().lower()
            for h in (self.headers.get("Access-Control-Request-Headers") or "").split(",")
            if h.strip()
        }
        try:
            from orch_ui.origin import any_host_ok
        except ImportError:
            return self._refuse()
        if (
            self.headers.get("Origin") != "null"
            or self.headers.get("Access-Control-Request-Method") not in ("GET", "POST")
            or "x-orch-frame" not in asked
            or not asked <= {"x-orch-frame", "content-type", "x-orch-op"}
            or not any_host_ok((self.headers.get("Host") or "").strip())
            or not ((px and self._shipped(px.group(1))) or (not px and path in framepass.FRAME_ROOT_PATHS))
        ):
            return self._refuse()
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "X-Orch-Frame, Content-Type, X-Orch-Op")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _shipped(self, name: str) -> bool:
        """True only for an add-on `orch addon list` says is shipped with orch; anything else, or unknown, is not."""
        return any(
            a["name"] == name and a.get("shipped") is True for a in load_addons(self.root, self.orch_bin)
        )

    def _upstream_port(self, name: str) -> int | None:
        """The local port of a running add-on that declares a [page]: both facts come from orch's own add-on data."""
        hit = _PORTS.get((str(self.root), name))
        # a found port is kept (a move is noticed by the failed connection in _proxy); "not running" is looked at again soon
        stamp = _services_stamp()
        if hit and time.monotonic() - hit[0] < (
            PORT_KEEP if hit[1] and stamp is not None and hit[2] == stamp else 3
        ):
            return hit[1]
        port = None
        if any(a["name"] == name and a.get("page") for a in load_addons(self.root, self.orch_bin)):
            for svc in load_services(self.root, self.orch_bin):
                m = LOCAL.fullmatch(str(svc.get("url") or ""))
                if (
                    svc.get("addon") == name
                    and svc.get("running") is True
                    and m
                    and 0 < int(m.group(1)) < 65536
                ):
                    port = int(m.group(1))
        _PORTS[(str(self.root), name)] = (time.monotonic(), port, stamp)
        return port

    def _proxy(self, method: str, name: str, rest: str, query: str, cross: bool = False):
        """Show an add-on's page under this server's address. The dashboard's own fence has already passed; the
        add-on's server runs its own fence on the request we forward (its Host, and for a POST its own Origin)."""
        port = self._upstream_port(name)
        if port is None or ".." in rest or "//" in rest:
            return self._send(404, b"not found", "text/plain")
        if framepass.FRAME_PARAM in query:  # the frame pass is the dashboard's: the add-on never sees it
            query = "&".join(q for q in query.split("&") if q.split("=", 1)[0] != framepass.FRAME_PARAM)
        up = {"Host": f"127.0.0.1:{port}", "X-Forwarded-Prefix": f"/addon/{name}"}
        if self._can_act():  # the person signed in here: vouch for them to the add-on's own page server
            from orch.pagesession import VOUCH_HEADER, vouch_key

            key = vouch_key(self.root, create=True)
            if key:
                up[VOUCH_HEADER] = key
        body = None
        if method == "POST":
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                return self._send(415, b"send JSON", "text/plain")
            try:
                n = int(self.headers.get("Content-Length") or "")
                if not 0 < n <= PROXY_BODY:
                    raise ValueError
                body = self.rfile.read(n)
            except (ValueError, OSError):
                return self._send(400, b"That request could not be read.", "text/plain; charset=utf-8")
            up.update({"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"})
        for attempt in (0, 1):
            try:
                conn = HTTPConnection("127.0.0.1", port, timeout=20)
                conn.request(method, (rest or "/") + (("?" + query) if query else ""), body=body, headers=up)
                r = conn.getresponse()
                data = r.read(PROXY_MAX_REPLY + 1)
                ctype, rev = (
                    r.getheader("Content-Type") or "application/octet-stream",
                    r.getheader("X-Revision"),
                )
                page_csp = r.getheader("Content-Security-Policy")
                conn.close()
                break
            except (OSError, ValueError):
                moved = _PORTS.pop((str(self.root), name), None)
                if attempt or method != "GET" or moved is None:
                    return self._send(502, b"That page is not answering.", "text/plain; charset=utf-8")
                port = self._upstream_port(name)  # the add-on may have restarted on another port: look once
                if port is None:
                    return self._send(404, b"not found", "text/plain")
                up["Host"] = f"127.0.0.1:{port}"
        if len(data) > PROXY_MAX_REPLY:
            return self._send(502, b"That page is too large.", "text/plain; charset=utf-8")
        extra = {"X-Revision": rev} if rev else {}
        if method == "GET" and PAGE_PATH.fullmatch(rest) and _sandboxed(page_csp):
            extra["Cross-Origin-Resource-Policy"] = "cross-origin"
            return self._send(r.status, data, ctype, extra, csp=page_csp)
        if cross:
            return self._send(403, b"forbidden", "text/plain")
        # Every add-on page gets an opaque origin. One orch did not ship: no pass, so it cannot call this server's
        # /api/act or hand-off confirm (the fence refuses an origin of "null"; SameSite withholds the cookie). One
        # orch ships: sandboxed as well, it acts only with the frame pass for that add-on (ORCH-186).
        csp = PROXY_CSP + ("; " + SHIPPED_SANDBOX if self._shipped(name) else "; sandbox allow-scripts")
        extra["Referrer-Policy"] = "no-referrer"  # a picture or file address may carry the frame pass
        if method == "GET" and r.status == 200 and rest.lower().endswith(STATIC_EXT):
            extra = {**extra, "Cache-Control": "private, max-age=60"}
        self._send(r.status, data, ctype, extra or None, csp=csp)

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return False
        if origin is None:
            return True
        host = (self.headers.get("Host") or "").strip().lower()
        return origin.lower() in (f"http://{host}", f"https://{host}")

    def do_GET(self):
        self._trace()
        path, _, query = self.path.partition("?")
        self._frame_begin(path, query)
        if path.startswith("/go/"):
            return self._standing_link(path[len("/go/") :])
        if self._frame_bad:
            return self._frame_refused()
        if not self._host_ok(path):  # DNS rebinding guard
            return self._refuse_host()
        if path == "/" and selfupdate.answer(self):
            return
        px = PROXY.fullmatch(path)
        if (
            px
        ):  # an add-on's page inside this app: same-site requests only (a frame of ours sends same-origin)
            cross = self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none")
            if cross and (
                self._frame or self._frame_static(path)
            ):  # a sandboxed page of ours: its pass or code
                cross = False
            if cross and not PAGE_PATH.fullmatch(px.group(2) or ""):
                return self._send(403, b"forbidden", "text/plain")
            return self._proxy("GET", px.group(1), px.group(2) or "/", query, cross)
        pv = re.fullmatch(r"/view/(t_[a-z0-9]{6,16})/(artifacts|evidence|files)/(.+)", path)
        if (
            pv
        ):  # a ticket's web page and its own assets, only ever inside a sandboxed frame (no cookie, no /api)
            site = self.headers.get("Sec-Fetch-Site")
            if site not in (None, "same-origin", "none"):
                # The page itself and anything a script fetches must come from this app. Only a sandboxed page's own
                # stylesheet, script, picture, font or media arrives as cross-site (its origin is opaque).
                last = pv.group(3).rsplit(".", 1)[-1].lower()
                if self.headers.get("Sec-Fetch-Dest") not in ticketfiles.PAGE_SUBRESOURCE_DEST or last in (
                    "html",
                    "htm",
                ):
                    return self._send(403, b"forbidden", "text/plain")
            code, body, ctype, extra = ticketfiles.read_page(
                self.root, pv.group(1), pv.group(2), unquote(pv.group(3))
            )
            return self._send(code, body, ctype, extra, csp=ticketfiles.PAGE_CSP)
        if path.startswith("/api/") and not (
            self._frame or self._same_origin()
        ):  # no foreign page triggers pulls
            return self._send(403, b"forbidden", "text/plain")
        if (
            path == "/ready" and self.nonce
        ):  # challenge-response for start/stop; the nonce itself is never sent
            c = self.path.partition("?c=")[2]
            if not re.fullmatch(r"[0-9a-f]{32,64}", c):
                return self._send(404, b"not found", "text/plain")
            m = hmac.new(self.nonce.encode(), c.encode(), hashlib.sha256).hexdigest()
            return self._send(200, json.dumps({"pid": os.getpid(), "mac": m}).encode(), "application/json")
        if (
            path == "/api/update-info"
        ):  # versions + what changed: same-origin only (checked above), no secrets
            from . import update

            return self._send(200, json.dumps(update.update_info()).encode(), "application/json")
        if path == "/api/release":  # a finished ticket: is its merged change in the installed release?
            from . import update

            tid = (parse_qs(query).get("ticket") or [""])[0]
            return self._send(
                200, json.dumps(update.ticket_release(self.root, tid)).encode(), "application/json"
            )
        if path == "/api/update-status":  # only a page with a session (a finished result is read once)
            from . import update

            st = update.update_status(self.root) if self._can_act() else None
            return self._send(200, json.dumps(st or {}).encode(), "application/json")
        if path == "/api/term":  # the live helper session's screen (read only; typing is POST /api/term/keys)
            if not (self._frame or self._same_origin()):
                return self._send(403, b"forbidden", "text/plain")
            from . import termsession

            tid = parse_qs(self.path.partition("?")[2]).get("ticket", [""])[0]
            snap = termsession.snapshot(self.root, self.orch_bin, tid)
            snap["typing_allowed"] = _typing_allowed(self.root)
            return self._send(
                200, json.dumps(snap).encode(), "application/json", {"Cache-Control": "no-store"}
            )
        if path == "/api/events":
            return self._events()
        if path == "/api/ref-file":
            q = parse_qs(query)
            code, body, ctype = reffiles.read(
                self.root, (q.get("ticket") or [""])[0], (q.get("n") or [""])[0]
            )
            return self._send(
                code, body, ctype, {"Content-Disposition": "inline"}, csp="default-src 'none'; sandbox"
            )
        if path == "/api/links":
            return self._send(
                200, json.dumps(load_links(self.root, self.orch_bin)).encode(), "application/json"
            )
        if path == "/api/state":
            fresh = "fresh=1" in query.split(
                "&"
            )  # the question card: the ticket as it is now, not a cached copy
            if fresh:
                forget_static()  # the add-on list too: a catalogue opened after a change made in the terminal
            state, age = self.server.state_cache.fresh() if fresh else self.server.state_cache.get()
            return self._send(
                200, json.dumps(state).encode(), "application/json", {"X-State-Age-Ms": str(int(age * 1000))}
            )
        if path == "/api/chat/contacts" or re.fullmatch(r"/api/chat/thread/ws_[a-z0-9]{10}", path):
            from .data import load_chat_contacts, load_chat_thread

            d = (
                load_chat_contacts(self.root, self.orch_bin)
                if path.endswith("/contacts")
                else load_chat_thread(self.root, self.orch_bin, path.rsplit("/", 1)[1])
            )
            if d is None:
                return self._send(404, b"not found", "text/plain")
            return self._send(200, json.dumps(d).encode(), "application/json")
        if path == "/api/chat/days":  # History: the days that have texts, newest first
            d = load_chat_days(self.root, self.orch_bin)
            return self._send(200, json.dumps(d if d is not None else []).encode(), "application/json")
        m = re.fullmatch(r"/api/chat/day/(\d{4}-\d{2}-\d{2})", path)
        if m:  # one day, read only
            d = load_chat_day(self.root, self.orch_bin, m.group(1))
            if d is None:
                return self._send(404, b"not found", "text/plain")
            return self._send(200, json.dumps(d).encode(), "application/json")
        m = re.fullmatch(r"/api/artifacts/(t_[a-z0-9]{6,16})", path)
        if m:  # the file list of one ticket (orch lists them); no file content here
            return self._send(
                200,
                json.dumps(ticketfiles.listing(self.root, self.orch_bin, m.group(1))).encode(),
                "application/json",
            )
        if path == "/api/copy-changes":  # read-only: what a ticket's copy would add to the project
            q = parse_qs(query, keep_blank_values=True)
            one = lambda k: (q.get(k) or [""])[0]
            if one("path"):
                code, data = copychanges.diff(self.root, one("t"), one("path"))
            else:
                code, data = 200, copychanges.listing(self.root, one("t"))
            return self._send(code, json.dumps(data).encode(), "application/json")
        if path == "/api/file-info":
            q = parse_qs(query, keep_blank_values=True)
            one = lambda k: (q.get(k) or [""])[0]
            code, data = ticketfiles.info(
                self.root, one("t"), one("k"), one("n"), int(one("s")) if one("s").isdigit() else 0
            )
            return self._send(code, json.dumps(data).encode(), "application/json")
        if (
            path == "/api/file"
        ):  # one file of a ticket's artifacts or evidence folder: plain text and pictures only
            q = parse_qs(query, keep_blank_values=True)
            one = lambda k: (q.get(k) or [""])[0]
            code, body, ctype, extra = ticketfiles.read_file(
                self.root, one("t"), one("k"), one("n"), one("dl") == "1"
            )
            if one("k") == "reviewed":  # a card's own copy: inert, sandboxed, never sniffed
                return self._send(code, body, ctype, extra, csp=ticketfiles.REVIEWED_CSP)
            rng = re.fullmatch(r"bytes=(\d{0,15})-(\d{0,15})", self.headers.get("Range") or "")
            if (
                code == 200
                and rng
                and ctype.startswith(("audio/", "video/"))
                and body
                and (rng.group(1) or rng.group(2))
            ):  # Safari plays a sound only with byte ranges
                size = len(body)
                if rng.group(1):
                    a = int(rng.group(1))
                    b = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
                else:
                    a, b = max(0, size - int(rng.group(2))), size - 1
                if a >= size:
                    return self._send(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
                if a <= b:
                    return self._send(
                        206,
                        body[a : b + 1],
                        ctype,
                        {**extra, "Content-Range": f"bytes {a}-{b}/{size}"},
                        csp="default-src 'none'; sandbox",
                    )
            return self._send(
                code,
                body,
                ctype,
                {"Accept-Ranges": "bytes", **extra} if ctype.startswith(("audio/", "video/")) else extra,
                csp=(
                    "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; object-src 'self'"
                    if ctype == "application/pdf"
                    else "default-src 'none'; img-src 'self'; media-src 'self'; sandbox"
                ),
            )
        if path.startswith("/api/addon/"):  # only names that are active here and have a tab
            name = path[len("/api/addon/") :]
            if not any(a["name"] == name and a["dashboard"] for a in load_addons(self.root, self.orch_bin)):
                return self._send(404, b"not found", "text/plain")
            return self._send(200, json.dumps(self.puller.pull(name)).encode(), "application/json")
        # the style guide's own address; its files sit next to it under /styleguide/
        if path == "/styleguide":
            return self._send(302, b"", "text/plain", {"Location": "/styleguide/"})
        if path.startswith("/styleguide/"):  # the same master kit as kit/, with the gallery as its front page
            path = "/kit/" + (path[len("/styleguide/") :] or "gallery.html")
        name = {"/": "index.html"}.get(path, path.lstrip("/"))
        if name.startswith("kit/"):  # the master kit, served from orch_ui (no copy next to the page)
            got = kit_file(name[4:])
            if got is None:
                return self._send(404, b"not found", "text/plain")
            static = name == "kit/gallery.html" or name.startswith("kit/samples/")
            return self._send(200, got[0], got[1], csp=GALLERY_CSP if static else None)
        if re.fullmatch(
            r"pages/(home|tickets|ticket|newticket|settings|chat|report|desktop)\.(js|css)|pages/(review|renew)\.js",
            name,
        ):  # the page modules
            return self._send(200, web_file(name), TYPES["." + name.rsplit(".", 1)[1]])
        if name in (
            "index.html",
            "app.js",
            "mobile-mode.js",
            "people.js",
            "look.js",
            "look-icons.js",
            "look-colors.css",
            "switcher.js",
            "blocks.js",
            "helpers.js",
            "session.js",
            "update.js",
            "style.css",
            "logo.svg",
            "favicon.svg",
            "apple-touch-icon.png",
        ):
            return self._send(200, web_file(name), TYPES["." + name.rsplit(".", 1)[1]])
        self._send(404, b"not found", "text/plain")

    def _events(self):
        revisions = self.server.revisions
        if not revisions.join():
            return self._send(503, b"Too many open pages.", "text/plain")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            if getattr(self, "_frame_cors", False):
                self.send_header("Access-Control-Allow-Origin", "null")
                self.send_header("Vary", "Origin")
            self.end_headers()
            last = None
            ping = time.monotonic()
            while not revisions.closed:
                with revisions.condition:
                    rev = revisions.rev
                    if rev == last:
                        revisions.condition.wait(timeout=max(0, 15 - (time.monotonic() - ping)))
                        rev = revisions.rev
                if rev != last:
                    self.wfile.write(f"event: rev\ndata: {rev}\n\n".encode())
                    self.wfile.flush()
                    last = rev
                elif time.monotonic() - ping >= 15:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    ping = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            revisions.leave()

    def _refuse(self):
        self._send(405, b"read only", "text/plain")

    do_PUT = do_DELETE = do_PATCH = _refuse

    def _fence(self, at_login: bool = False) -> str | None:
        """Host + Origin check of orch_ui.origin on every POST. A missing Origin is refused too: the
        dashboard page always sends one, so only a script outside the browser lacks it. Any host name passes
        with the session cookie (or for the sign-in itself, whose one-time token is the proof)."""
        try:
            from orch_ui.origin import check_request
        except ImportError:
            return "Actions are not available in this install."
        if (
            getattr(self, "_frame", None) and not at_login
        ):  # a sandboxed add-on page of ours: its pass, checked
            return None
        if self.headers.get("Origin") is None:
            return "This request was refused (no origin)."
        if self._remote() and not (at_login or self._signed_in()):
            from orch.pagesession import SIGNIN_MSG

            return self._refused_text(SIGNIN_MSG)
        if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return "This request came from another website and was refused."
        return check_request(
            "POST",
            self.headers,
            self._page_port(),
            api=True,
            signed_in=at_login or self._signed_in(),
        )

    def _diag_post(self, path: str):
        """The page's action trail (any page of this app, a fence only) and Report a problem (the person's own
        session: a report holds ticket text)."""
        why = self._fence()
        if why:
            return self._send(403, why.encode(), "text/plain; charset=utf-8")
        report = path != "/api/diag"
        if report and not self._can_act():
            from orch.pagesession import SIGNIN_MSG

            return self._send(403, self._refused_text(SIGNIN_MSG).encode(), "text/plain; charset=utf-8")
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return self._send(415, b"send JSON", "text/plain")
        limit = diagapi.MAX_REPORT if path == "/api/diag/report" else diagapi.MAX_TRAIL
        try:
            n = int(self.headers.get("Content-Length") or "")
            if not 0 < n <= limit:
                raise ValueError
            body = diagapi.parse_json(self.rfile.read(n))
        except (ValueError, OSError):
            return self._send(400, b"That request could not be read.", "text/plain; charset=utf-8")
        if path == "/api/diag":
            return self._send(
                200, json.dumps(diagapi.accept_trail(self.root, body)).encode(), "application/json"
            )
        code, out = (
            diagapi.make_report(self.root, body)
            if path == "/api/diag/report"
            else diagapi.share_report(self.root, body)
            if path == "/api/diag/share"
            else diagapi.open_folder(self.root, body)
        )
        if code != 200:
            return self._send(code, str(out).encode(), "text/plain; charset=utf-8")
        self._send(200, json.dumps(out).encode(), "application/json")

    def _term_keys(self):
        """Type into the live helper session: the person's own dashboard session only (cookie + page secret: the
        same rule as a human-only action, from any computer). A script or an agent has none of it."""
        why = self._fence()
        if why:
            return self._send(403, why.encode(), "text/plain; charset=utf-8")
        if not self._can_act():
            from orch.pagesession import SIGNIN_MSG

            return self._send(403, self._refused_text(SIGNIN_MSG).encode(), "text/plain; charset=utf-8")
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return self._send(415, b"send JSON", "text/plain")
        try:
            n = int(self.headers.get("Content-Length") or "")
            if not 0 < n <= 16384:
                raise ValueError
            body = json.loads(self.rfile.read(n))
            if not isinstance(body, dict) or set(body) != {"ticket", "items"}:
                raise ValueError
        except (ValueError, RecursionError, OSError):
            return self._send(400, b"That request could not be read.", "text/plain; charset=utf-8")
        if not _typing_allowed(self.root):  # the setting is checked here, not only hidden in the page
            return self._send(403, TYPING_OFF.encode(), "text/plain; charset=utf-8")
        from . import termsession

        code, text = termsession.keys(self.root, self.orch_bin, str(body["ticket"]), body["items"])
        self._send(code, text.encode(), "application/json" if code == 200 else "text/plain; charset=utf-8")

    def _standing_link(self, sent: str):
        """GET /go/<secret>: the person's standing sign-in link (a bookmark, see pagelaunch). Right secret: a
        redirect to a fresh one-time launch link, which the page spends as with any sign-in link. Anything else
        is 404, the same answer as an address that does not exist."""
        try:
            from orch import pagelaunch
            from orch_ui.origin import any_host_ok
        except ImportError:
            return self._send(404, b"not found", "text/plain")
        if (
            self.session is None
            or not any_host_ok((self.headers.get("Host") or "").strip())
            or not pagelaunch.standing_link_ok(self.root, sent)
        ):
            return self._send(404, b"not found", "text/plain")
        token = pagelaunch.write_launch_token(self.root, "dashboard")
        if not token:
            return self._send(503, b"Try again in a moment.", "text/plain")
        self._send(
            302, b"", "text/plain", {"Location": "/#launch=" + token, "Referrer-Policy": "no-referrer"}
        )

    def _session_post(self):
        """POST /session: the page hands over the one-time sign-in token it got in the URL fragment; the server
        spends it and sets the session cookie (H1). Same fence as an action, from any computer."""
        why = self._fence(at_login=True)
        if why:
            return self._send(403, why.encode(), "text/plain; charset=utf-8")
        if self.session is None:
            return self._send(403, b"forbidden", "text/plain")
        try:
            n = int(self.headers.get("Content-Length") or "")
            token = json.loads(self.rfile.read(n)).get("token") if 0 < n <= 200 else None
        except (ValueError, AttributeError, OSError):
            token = None
        cookie = self.session.launch(token)
        if not cookie:
            return self._send(403, _link_msg(self.session, "dashboard"), "text/plain; charset=utf-8")
        # the cookie plus the page secret (PAGE_HEADER); the page keeps the secret in its localStorage
        self._send(
            200,
            json.dumps({"secret": self.session.secret}).encode(),
            "application/json",
            {"Set-Cookie": self.session.set_cookie(self._page_port(), cookie)},
        )

    def do_POST(self):
        self._trace()
        path = self.path.split("?", 1)[0]
        self._frame_begin(path)
        if path == "/api/frame-pass":
            return self._frame_pass_post()
        if self._frame_bad:
            return self._frame_refused()
        if path == "/session":
            return self._session_post()
        if path == "/api/term/keys":
            return self._term_keys()
        if path in ("/api/diag", "/api/diag/report", "/api/diag/open", "/api/diag/share"):
            return self._diag_post(path)
        px = PROXY.fullmatch(path)
        if path != "/api/act" and not (px and px.group(2) == "/api/act"):
            return self._refuse()
        why = self._fence()
        if why:
            return self._send(403, why.encode(), "text/plain; charset=utf-8")
        if px:
            return self._proxy("POST", px.group(1), px.group(2), "")
        _PORTS.clear()  # an action may start, stop or restart add-ons: every port is looked up live next time
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return self._send(415, b"send JSON", "text/plain")
        try:
            n = int(self.headers.get("Content-Length") or "")
            # The limit comes from the header (checked before the body is read); the body must say the same op.
            claimed = self.headers.get("X-Orch-Op")
            limit = MAX_BIG_BODY if claimed in BIG_OPS else MAX_BODY
            if not 0 < n <= limit:
                raise ValueError
            if n > MAX_BODY:
                with _BIG_READS:  # one big body in memory at a time
                    raw = self.rfile.read(n)
            else:
                raw = self.rfile.read(n)
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) - {"op", "args"}:
                raise ValueError
            if claimed is not None and body.get("op") != claimed:
                raise ValueError
        except (ValueError, RecursionError, OSError):
            return self._send(400, b"That request could not be read.", "text/plain; charset=utf-8")
        op_name = re.sub(r"[^A-Za-z0-9_.-]", "?", str(body.get("op"))[:40])
        self._act = (op_name, time.monotonic())
        from . import update as _update

        session = self._can_act()
        with _update.click():  # no automatic update starts during a person's click (or right after it)
            return self._act_run(body, op_name, session)

    def _act_run(self, body, op_name, session: bool):
        self._act_log(f"{op_name} start")
        try:
            if body.get("op") == "update.start":  # the Update button in Settings
                from . import update

                if not session:
                    raise actions.NeedsPerson(actions.SIGNIN)
                args = body.get("args") or {}
                to = args.get("to") if isinstance(args, dict) else None
                if to is not None and to not in update.BUILDS:
                    raise actions.BadRequest("Choose release or development build.")
                code, text = update.start_update(
                    self.root,
                    self.orch_bin,
                    actions.human_env(self.root, self.orch_bin),
                    session=self.session,
                    to=to,
                )
                return self._send(code, text.encode(), "text/plain; charset=utf-8")
            if body.get("op") in RESTARTING_OPS and session:
                _arm_resume(self.root, self.session)
            code, text, extra = actions.run_op(
                self.root, self.orch_bin, body.get("op"), body.get("args", {}), session=session
            )
        except actions.NeedsPerson as e:
            msg = self._refused_text(str(e))
            return self._send(403, msg.encode(), "text/plain; charset=utf-8")
        except actions.BadRequest as e:
            return self._send(400, str(e).encode(), "text/plain; charset=utf-8")
        except actions.Unavailable as e:
            return self._send(503, str(e).encode(), "text/plain; charset=utf-8")
        if code != 200:
            hdr = {"X-Revision": str(extra["revision"])} if extra else None
            return self._send(code, text.encode(), "text/plain; charset=utf-8", hdr)
        tid = (body.get("args") or {}).get("ticket") if isinstance(body.get("args"), dict) else None
        if isinstance(extra, dict) and body.get("op") in ("ticket.new", "ticket.paste"):
            tid = extra.get("id")  # the new ticket
        state = None
        renew = _renew_answer(extra) if str(body.get("op")).startswith("logins.") else None
        if renew is not None and renew["state"] not in RENEWED:
            state = dict(
                self.server.state_cache.get()[0]
            )  # polled while the sign-in runs: nothing else changed
        if state is None and body.get("op") in LEAN_OPS:
            # A workspace text changes no ticket: answer with the cached state at once (a full rebuild took 10 s on a
            # big workspace and kept "Sending…" on screen), never as the new cache.
            state = dict(self.server.state_cache.get()[0])
        elif (
            state is None
            and isinstance(tid, str)
            and actions.TID.fullmatch(tid)
            and body.get("op") not in WIDE_OPS
        ):
            # A click on one ticket (accept, answer, save, a task ...): the cached state with that ticket read again,
            # at once; the full build runs in the background (ORCH-102: a click waited seconds for it).
            state = patch_ticket(self.root, self.orch_bin, self.server.state_cache.get()[0], tid)
            if state is not None:
                self.server.state_cache.quick(state)  # before the reply's own keys are added
        if state is None:
            state = load_state(self.root, orch_bin=self.orch_bin, fresh=True, with_settings=True)
            self.server.state_cache.invalidate(state)  # before the reply's own keys are added
        if renew is not None:  # the Renew window's answer (ORCH-46): a few plain facts, never a code or a key
            state["renew_result"] = renew
        if body.get("op") == "chat.send_ws" and isinstance(extra, dict):
            state["chat_dm_result"] = extra
        if body.get("op") == "workspace.propose" and isinstance(extra, dict):
            # a proposal only, shown in the edit fields; the page saves it with workspace.set after the person's Save
            tags = extra.get("tags") if isinstance(extra.get("tags"), list) else []
            state["proposal"] = {
                "name": str(extra.get("name") or "")[:60],
                "description": str(extra.get("description") or "")[:280],
                "tags": [str(t)[:24] for t in tags if isinstance(t, str)][:4],
                "icon": str(extra["icon"])[:32] if isinstance(extra.get("icon"), str) else None,
            }
        if body.get("op") == "config.agent.test" and isinstance(
            extra, dict
        ):  # the answer of the try, plain words only
            state["test"] = {
                "name": str(extra.get("name"))[:40],
                "ok": extra.get("ok") is True,
                "reason": str(extra.get("reason") or "")[:300],
            }
        if (
            body.get("op") == "addon.act"
            and isinstance(extra, dict)
            and isinstance(extra.get("changes"), list)
        ):  # refresh
            state["act_result"] = {"changes": len(extra["changes"]), "say": str(extra.get("say") or "")[:300]}
        if body.get("op") == "addon.act" and isinstance(extra, dict):
            # the add-on's own answer to this click (a Sync card's status, a check): shown as plain text only
            answer = json.dumps(extra)
            if len(answer) <= 32_768:
                state["act_answer"] = {
                    "addon": str((body.get("args") or {}).get("addon"))[:32],
                    "answer": extra,
                }
        if body.get("op") == "run.send" and isinstance(extra, dict):
            # what orch did with the person's message: delivered to the agent now, or queued for it (an id). The
            # embedded Factory page says "Sent" only on one of these, never on a bare 200.
            sid, dlv, st = extra.get("id"), extra.get("delivered"), extra.get("state")
            state["send_result"] = {
                "id": sid[:64] if isinstance(sid, str) and sid else None,
                "delivered": dlv if type(dlv) is int and dlv > 0 else 0,
                "state": st[:20] if isinstance(st, str) else None,
            }
        if body.get("op") == "ticket.new" and isinstance(extra, dict) and isinstance(extra.get("id"), str):
            # the new ticket's id: the New ticket window opens it by id, never by guessing from the title
            state["created"] = {"id": extra["id"][:40]}
        if body.get("op") in BIG_OPS and isinstance(extra, dict) and isinstance(extra.get("attached"), dict):
            att = extra["attached"]  # which files were kept with the new ticket (names are orch's own)
            state["attached"] = {
                "id": str(extra.get("id"))[:40],
                "saved": [str(x)[:100] for x in att.get("saved", [])[:10]],
                "failed": [str(x)[:100] for x in att.get("failed", [])[:10]],
            }
        self._send(200, json.dumps(state).encode(), "application/json")


RENEWED = (
    "done",
    "works",
    "soon",
)  # the login works again: the page reads the whole state (the warning goes)
_RENEW_STATES = (
    "none",
    "starting",
    "link",
    "checking",
    "done",
    "failed",
    "stopped",
    "works",
    "soon",
    "renew",
)


def _renew_answer(extra) -> dict | None:
    """`orch logins renew|replace --json` reduced to what the Renew window shows."""
    if not isinstance(extra, dict):
        return None
    st = extra.get("state")
    out: dict = {"state": st if st in _RENEW_STATES else "failed"}
    link = extra.get("link")
    if isinstance(link, str) and link.startswith("https://") and len(link) <= 2048:
        out["link"] = link
    if isinstance(extra.get("name"), str):
        out["name"] = extra["name"][:32]
    if extra.get("again") is True:  # the tool did not take the last code and waits for it once more
        out["again"] = True
    if isinstance(extra.get("ends_at"), str):
        out["ends_at"] = extra["ends_at"][:20]
    went = extra.get("went_on")
    out["went_on"] = [str(x)[:40] for x in went[:20]] if isinstance(went, list) else []
    return out


class _Server(ThreadingHTTPServer):
    def server_close(self):
        other = getattr(self, "remote_server", None)
        if other is not None:
            other.server_close()
        if hasattr(self, "revisions"):
            self.revisions.close()
        if hasattr(self, "state_cache"):
            self.state_cache.close()
        super().server_close()

    request_queue_size = (
        128  # the page loads a dozen files at once; the default of 5 resets connections (seen on macOS)
    )


class _RemoteServer(ThreadingHTTPServer):
    """The second socket of remote listening: same handler, session, state cache and change feed as the
    loopback server (which owns and closes them). `remote` makes the handler trust no name of this computer."""

    remote = True
    request_queue_size = 128


def make_server(
    root: Path,
    port: int = DEFAULT_PORT,
    orch_bin: str | None = None,
    remote: tuple[str, int] | None = None,
) -> ThreadingHTTPServer:
    """`remote`: (address, port) to listen on for other computers as well (the [dashboard] setting, see
    remote.py). It shares this server's sign-in; a port that cannot be had leaves the dashboard local only
    (`remote_error` says why) instead of not starting at all."""
    # No ORCH_BIN from the environment (H1): the real server passes SELF (`sys.executable -I -m orch`); only a
    # test harness passes a fake path. None = standalone, reads files only.
    handler = partial(Handler, root=root, orch_bin=orch_bin, puller=ViewPuller(root, orch_bin), session=None)
    # The session is made AFTER the port is bound. A restarted server adopts the open tab's session ONCE
    # (PageSession reads and removes the resume file): made before the bind, a port that is still busy right
    # after the restart (Windows) would spend the file and the auto-port retry would start without it.
    srv = _Server(("127.0.0.1", port), handler)
    if orch_bin == actions.SELF:
        from orch.pagesession import PageSession

        try:
            handler.keywords["session"] = PageSession(root, "dashboard", srv.server_address[1])
        except BaseException:
            srv.server_close()
            raise
    srv.page_port = srv.server_address[1]
    srv.frame_passes = framepass.FramePasses()
    srv.revisions = Revisions(root)
    srv.state_cache = StateCache(root, orch_bin, srv.revisions)
    srv.remote_server, srv.remote_error = None, None
    if remote is not None:
        try:
            other = _RemoteServer(remote, handler)
        except OSError as e:
            srv.remote_error = f"could not listen on {remote[0]} port {remote[1]} ({e.strerror or e})"
        else:
            other.page_port = srv.page_port
            other.frame_passes = srv.frame_passes
            other.revisions, other.state_cache = srv.revisions, srv.state_cache
            srv.remote_server = other
    if orch_bin == actions.SELF:  # the real server: the automatic update looks once a minute (off by default)
        from . import update

        update.start_ticker(root, orch_bin, lambda: actions.human_env(root, orch_bin))
    return srv
