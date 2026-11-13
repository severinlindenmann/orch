"""Stdlib HTTP server on 127.0.0.1. GET reads; the only POST is /api/act (the fixed op table in actions.py)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
import time
from functools import partial
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs

from . import actions, reffiles, selfupdate, ticketfiles
from .data import load_addons, load_chat_day, load_chat_days, load_links, load_services, load_state
from .events import Revisions
from .state_cache import StateCache
from .views import ViewPuller

DEFAULT_PORT = 8420
MAX_BODY = 16384  # every action but the ones below
MAX_BIG_BODY = 5 * 1024 * 1024  # a new ticket with a long text and up to 5 attached files
BIG_OPS = ("ticket.new", "ticket.paste")
_BIG_READS = threading.BoundedSemaphore(1)
KIT = (
    "tokens.css",
    "components.css",
    "motion.css",
    "motion.js",
    "icons.js",
    "question-card-state.js",
    "question-card.js",
    "evidence.js",
    "blocks.js",
    "blocks.css",
)
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
PROXY_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; frame-ancestors 'self'; base-uri 'none'"
)
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


_PORTS: dict[tuple[str, str], tuple[float, int | None]] = {}


def _link_msg(session, name: str) -> bytes:
    from orch.pageproof import REVOKED_MSG

    if session.revoked:
        return REVOKED_MSG.encode()
    return f"This link was already used. Open the {name} again from orch.".encode()


class Handler(BaseHTTPRequestHandler):
    timeout = 10  # a short body must not hold a thread

    def __init__(self, *a, root: Path, orch_bin: str | None, puller: ViewPuller, session=None, **kw):
        self.root, self.orch_bin, self.puller, self.session = root, orch_bin, puller, session
        self.nonce = os.environ.get("ORCH_DASHBOARD_NONCE", "")
        super().__init__(*a, **kw)

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body: bytes, ctype: str, extra: dict | None = None, csp: str | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header(
            "Content-Security-Policy",
            csp or "default-src 'self'; img-src 'self' data:; style-src 'self'; frame-ancestors 'self'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        host = host.rsplit("]", 1)[0] + "]" if host.startswith("[") else host.split(":", 1)[0]
        return host in ("127.0.0.1", "localhost", "[::1]")

    def _shipped(self, name: str) -> bool:
        """True only for an add-on `orch addon list` says is shipped with orch; anything else, or unknown, is not."""
        return any(
            a["name"] == name and a.get("shipped") is True for a in load_addons(self.root, self.orch_bin)
        )

    def _upstream_port(self, name: str) -> int | None:
        """The local port of a running add-on that declares a [page]: both facts come from orch's own add-on data."""
        hit = _PORTS.get((str(self.root), name))
        if hit and time.monotonic() - hit[0] < 3:
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
        _PORTS[(str(self.root), name)] = (time.monotonic(), port)
        return port

    def _proxy(self, method: str, name: str, rest: str, query: str, cross: bool = False):
        """Show an add-on's page under this server's address. The dashboard's own fence has already passed; the
        add-on's server runs its own fence on the request we forward (its Host, and for a POST its own Origin)."""
        port = self._upstream_port(name)
        if port is None or ".." in rest or "//" in rest:
            return self._send(404, b"not found", "text/plain")
        up = {"Host": f"127.0.0.1:{port}", "X-Forwarded-Prefix": f"/addon/{name}"}
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
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=20)
            conn.request(method, (rest or "/") + (("?" + query) if query else ""), body=body, headers=up)
            r = conn.getresponse()
            data = r.read(PROXY_MAX_REPLY + 1)
            ctype, rev = r.getheader("Content-Type") or "application/octet-stream", r.getheader("X-Revision")
            page_csp = r.getheader("Content-Security-Policy")
            conn.close()
        except (OSError, ValueError):
            return self._send(502, b"That page is not answering.", "text/plain; charset=utf-8")
        if len(data) > PROXY_MAX_REPLY:
            return self._send(502, b"That page is too large.", "text/plain; charset=utf-8")
        extra = {"X-Revision": rev} if rev else {}
        if method == "GET" and PAGE_PATH.fullmatch(rest) and _sandboxed(page_csp):
            extra["Cross-Origin-Resource-Policy"] = "cross-origin"
            return self._send(r.status, data, ctype, extra, csp=page_csp)
        if cross:
            return self._send(403, b"forbidden", "text/plain")
        # a page that orch did not ship gets an opaque origin: it cannot call this server's /api/act or hand-off
        # confirm with the person's cookie (the fence refuses an origin of "null"; SameSite withholds the cookie)
        csp = PROXY_CSP if self._shipped(name) else PROXY_CSP + "; sandbox allow-scripts"
        self._send(r.status, data, ctype, extra or None, csp=csp)

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
        path, _, query = self.path.partition("?")
        if path == "/" and selfupdate.answer(self):
            return
        px = PROXY.fullmatch(path)
        if (
            px
        ):  # an add-on's page inside this app: same-site requests only (a frame of ours sends same-origin)
            cross = self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none")
            if cross and not PAGE_PATH.fullmatch(px.group(2) or ""):
                return self._send(403, b"forbidden", "text/plain")
            return self._proxy("GET", px.group(1), px.group(2) or "/", query, cross)
        if path.startswith("/api/") and not self._same_origin():  # a foreign page must not trigger pulls
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
            path == "/api/notices"
        ):  # read once, and only by a page with a session (a curl must not consume it)
            from . import handoff

            ok = self.session is not None and self.session.authed(self.headers, self.server.server_address[1])
            items = handoff.notices(self.root) if ok else []
            return self._send(200, json.dumps(items).encode(), "application/json")
        if path == "/api/update-status":  # only a page with a session (a finished result is read once)
            from . import handoff

            ok = self.session is not None and self.session.authed(self.headers, self.server.server_address[1])
            st = handoff.update_status(self.root) if ok else None
            return self._send(200, json.dumps(st or {}).encode(), "application/json")
        if path == "/api/handoffs":  # pending requests from a terminal; same-origin only (checked above)
            from . import handoff

            return self._send(200, json.dumps(handoff.listing(self.root)).encode(), "application/json")
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
            state, age = self.server.state_cache.get()
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
        if (
            path == "/api/file"
        ):  # one file of a ticket's artifacts or evidence folder: plain text and pictures only
            q = parse_qs(query, keep_blank_values=True)
            one = lambda k: (q.get(k) or [""])[0]
            code, body, ctype, extra = ticketfiles.read_file(
                self.root, one("t"), one("k"), one("n"), one("dl") == "1"
            )
            rng = re.fullmatch(r"bytes=(\d{0,15})-(\d{0,15})", self.headers.get("Range") or "")
            if (
                code == 200 and rng and ctype.startswith("audio/") and body and (rng.group(1) or rng.group(2))
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
                {"Accept-Ranges": "bytes", **extra} if ctype.startswith("audio/") else extra,
                csp="default-src 'none'; img-src 'self'; sandbox",
            )
        if path.startswith("/api/addon/"):  # only names that are active here and have a tab
            name = path[len("/api/addon/") :]
            if not any(a["name"] == name and a["dashboard"] for a in load_addons(self.root, self.orch_bin)):
                return self._send(404, b"not found", "text/plain")
            return self._send(200, json.dumps(self.puller.pull(name)).encode(), "application/json")
        name = {"/": "index.html"}.get(path, path.lstrip("/"))
        if (
            name.startswith("kit/") and name[4:] in KIT
        ):  # the orch_ui kit, copied next to the page (a test keeps it in sync)
            return self._send(200, web_file(name), TYPES["." + name.rsplit(".", 1)[1]])
        if re.fullmatch(
            r"pages/(home|tickets|ticket|newticket|settings|chat|notes)\.(js|css)", name
        ):  # the page modules
            return self._send(200, web_file(name), TYPES["." + name.rsplit(".", 1)[1]])
        if name in (
            "index.html",
            "app.js",
            "mobile-mode.js",
            "look.js",
            "look-icons.js",
            "look.css",
            "look-colors.css",
            "switcher.js",
            "blocks.js",
            "helpers.js",
            "session.js",
            "handoff.js",
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

    def _session_post(self):
        """POST /session: the page hands over the one-time launch token it got in the URL fragment; the server
        spends it and sets the session cookie (H1). Same fence as an action; loopback Host, no proxy headers."""
        why = self._fence()
        if why:
            return self._send(403, why.encode(), "text/plain; charset=utf-8")
        from orch.pageproof import forwarded, host_ok

        if (
            self.session is None
            or forwarded(self.headers)
            or not host_ok(self.headers, self.server.server_address[1])
        ):
            return self._send(403, b"forbidden", "text/plain")
        try:
            n = int(self.headers.get("Content-Length") or "")
            token = json.loads(self.rfile.read(n)).get("token") if 0 < n <= 200 else None
        except (ValueError, AttributeError, OSError):
            token = None
        cookie = self.session.launch(token)
        if not cookie:
            return self._send(403, _link_msg(self.session, "dashboard"), "text/plain; charset=utf-8")
        # the cookie plus the page secret (PAGE_HEADER); the page keeps the secret in its sessionStorage
        self._send(
            200,
            json.dumps({"secret": self.session.secret}).encode(),
            "application/json",
            {"Set-Cookie": self.session.set_cookie(self.server.server_address[1], cookie)},
        )

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/session":
            return self._session_post()
        px = PROXY.fullmatch(path)
        if path != "/api/act" and not (px and px.group(2) == "/api/act"):
            return self._refuse()
        why = self._fence()
        if why:
            return self._send(403, why.encode(), "text/plain; charset=utf-8")
        if px:
            return self._proxy("POST", px.group(1), px.group(2), "")
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
        try:
            mint = None
            if self.session is not None and self.session.can_mint(
                self.headers, self.server.server_address[1]
            ):
                mint = self.session.mint
            if body.get("op") == "notice.ack":
                if mint is None:  # only a page with a session may clear a notice
                    raise actions.NeedsPerson("Open the dashboard from this computer to do this.")
                from . import handoff

                handoff.ack_notice(self.root, (body.get("args") or {}).get("id"))
                return self._send(200, b"{}", "application/json")
            if body.get("op") in ("handoff.confirm", "handoff.dismiss"):
                from . import handoff

                hid = (body.get("args") or {}).get("id")
                if body["op"] == "handoff.dismiss":
                    if mint is None:  # only a page with a session may dismiss the person's requests
                        raise actions.NeedsPerson("Open the dashboard from this computer to do this.")
                    handoff.dismiss(self.root, hid)
                    return self._send(200, b"{}", "application/json")
                code, text = handoff.confirm(
                    self.root,
                    self.orch_bin,
                    mint,
                    hid,
                    actions.human_env(self.root, self.orch_bin),
                    session=self.session,
                )  # 202 = started in the background (an update): the answer is sent below as it is
                if code != 200:
                    return self._send(code, text.encode(), "text/plain; charset=utf-8")
                state = load_state(self.root, orch_bin=self.orch_bin, fresh=True, with_settings=True)
                self.server.state_cache.invalidate(state)
                return self._send(200, json.dumps(state).encode(), "application/json")
            code, text, extra = actions.run_op(
                self.root, self.orch_bin, body.get("op"), body.get("args", {}), mint=mint
            )
        except actions.NeedsPerson as e:
            from orch.pageproof import REVOKED_MSG

            msg = REVOKED_MSG if self.session is not None and self.session.revoked else str(e)
            return self._send(403, msg.encode(), "text/plain; charset=utf-8")
        except actions.BadRequest as e:
            return self._send(400, str(e).encode(), "text/plain; charset=utf-8")
        except actions.Unavailable as e:
            return self._send(503, str(e).encode(), "text/plain; charset=utf-8")
        if code != 200:
            hdr = {"X-Revision": str(extra["revision"])} if extra else None
            return self._send(code, text.encode(), "text/plain; charset=utf-8", hdr)
        state = load_state(self.root, orch_bin=self.orch_bin, fresh=True, with_settings=True)
        self.server.state_cache.invalidate(state)  # before the reply's own keys are added
        if body.get("op") == "chat.send_ws" and isinstance(extra, dict):
            state["chat_dm_result"] = extra
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
        if body.get("op") in BIG_OPS and isinstance(extra, dict) and isinstance(extra.get("attached"), dict):
            att = extra["attached"]  # which files were kept with the new ticket (names are orch's own)
            state["attached"] = {
                "id": str(extra.get("id"))[:40],
                "saved": [str(x)[:100] for x in att.get("saved", [])[:10]],
                "failed": [str(x)[:100] for x in att.get("failed", [])[:10]],
            }
        self._send(200, json.dumps(state).encode(), "application/json")


class _Server(ThreadingHTTPServer):
    def server_close(self):
        if hasattr(self, "revisions"):
            self.revisions.close()
        if hasattr(self, "state_cache"):
            self.state_cache.close()
        super().server_close()

    request_queue_size = (
        128  # the page loads a dozen files at once; the default of 5 resets connections (seen on macOS)
    )


def make_server(root: Path, port: int = DEFAULT_PORT, orch_bin: str | None = None) -> ThreadingHTTPServer:
    # No ORCH_BIN from the environment (H1): the real server passes SELF (`sys.executable -I -m orch`); only a
    # test harness passes a fake path. None = standalone, reads files only.
    session = None
    if orch_bin == actions.SELF:
        from orch.pageproof import PageSession

        session = PageSession(root, "dashboard")
    srv = _Server(
        ("127.0.0.1", port),
        partial(Handler, root=root, orch_bin=orch_bin, puller=ViewPuller(root, orch_bin), session=session),
    )
    srv.revisions = Revisions(root)
    srv.state_cache = StateCache(root, orch_bin, srv.revisions)
    return srv
