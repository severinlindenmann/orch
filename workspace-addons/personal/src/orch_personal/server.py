"""The Personal page: a loopback server behind the dashboard.

Notes are private, so every /api/ request (read or write) must come through the dashboard, which vouches that the
person sent it (`X-Orch-Person`, checked against the core's vouch key), and pass the shared UI origin fence. Opened
any other way, the page says to open Personal from the dashboard. Reads and writes call the same code as the CLI
(api.py), as the person: helpers never reach Personal through this page.
"""

from __future__ import annotations

import getpass
import hashlib
import hmac
import json
import os
import re
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs

from . import api, store
from . import calendar as cal_mod
from .store import Refused

DEFAULT_PORT = 8433
MAX_BODY = 8192
KIT_FILES = (
    "frame.js",
    "tokens.css",
    "components.css",
    "motion.css",
    "interaction.css",
    "widgets.css",
    "icons.js",
    "overlay.js",
    "select.js",
    "components.js",
    "widgets.js",
)
WEB_FILES = ("index.html", "personal.js")
PLAIN = "text/plain; charset=utf-8"
TYPES = {"html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8", "js": "text/javascript"}
PREFIX = re.compile(r"/addon/[a-z][a-z0-9-]{1,31}")
CSP = "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
FROM_DASHBOARD = "Open Personal from the dashboard: orch start, then Add-ons > Personal."
OPS = (
    "add",
    "remove",
    "folder",
    "rules",
    "use",
    "way_on",
    "way_off",
    "way_check",
    "cal_level",
    "cal_moves",
    "cal_allow",
    "cal_check",
    "cal_accept",
    "cal_decline",
)


def _web(name: str) -> bytes:
    return resources.files("orch_personal").joinpath("web", name).read_bytes()


def _kit(name: str) -> bytes | None:
    try:
        import orch_ui

        return (Path(orch_ui.__file__).parent / "static" / name).read_bytes()
    except (ImportError, OSError, TypeError):
        return None


def _vouch_key(root: Path) -> str | None:
    try:
        from orch.pagesession import vouch_key

        return vouch_key(root) or None
    except Exception:  # noqa: BLE001 - no core key: nobody is vouched for
        return None


def _person() -> api.Who:
    try:
        name = getpass.getuser()
    except Exception:  # noqa: BLE001
        name = "user"
    return api.Who(helper=False, by="human:" + (re.sub(r"[^A-Za-z0-9_.@-]", "_", name)[:64] or "user"))


class Handler(BaseHTTPRequestHandler):
    timeout = 10

    def __init__(self, *args, root: Path, vouch=None, **kwargs):
        self.root = root
        self.vouch = vouch if vouch is not None else (lambda: _vouch_key(root))
        self.nonce = os.environ.get("ORCH_PERSONAL_NONCE", "")
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

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def _vouched(self) -> bool:
        sent = self.headers.get("X-Orch-Person") or ""
        key = self.vouch()
        return bool(key and sent) and hmac.compare_digest(sent.encode(), key.encode())

    def _fence(self, method: str, api_call: bool) -> str | None:
        try:
            from orch_ui.origin import check_request
        except ImportError:
            return "Personal is not available in this install."
        port = self.server.server_address[1]
        why = check_request(method, self.headers, port, api=api_call, signed_in=self._vouched())
        if method == "POST" and self.headers.get("Origin") is None:
            return why or "This request was refused (no origin)."
        return why

    def _refuse(self):
        why = self._fence(self.command, True)
        return self._send(403, why.encode()) if why else self._send(405, b"not allowed")

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = do_TRACE = do_CONNECT = _refuse

    def do_GET(self):
        path, _, query = self.path.partition("?")
        is_api = path.startswith("/api/")
        why = self._fence("GET", is_api or path == "/ready")
        if why:
            return self._send(403, why.encode())
        if path == "/ready" and self.nonce:
            challenge = query.partition("c=")[2]
            if not re.fullmatch(r"[0-9a-f]{32,64}", challenge):
                return self._send(404, b"not found")
            mac = hmac.new(self.nonce.encode(), challenge.encode(), hashlib.sha256).hexdigest()
            return self._json({"pid": os.getpid(), "mac": mac})
        if is_api:
            if not self._vouched():
                return self._send(403, FROM_DASHBOARD.encode())
            return self._api_get(path, parse_qs(query))
        if path in (
            "/",
            "/notes",
            "/calendar",
            "/parts",
        ):  # the screens: one page, the path picks the first screen
            prefix = self.headers.get("X-Forwarded-Prefix") or ""
            prefix = prefix if PREFIX.fullmatch(prefix) else ""
            return self._send(200, _web("index.html").replace(b"__P__", prefix.encode()), TYPES["html"])
        if path.startswith("/kit/") and path[5:] in KIT_FILES:
            body = _kit(path[5:])
            return (
                self._send(404, b"not found")
                if body is None
                else self._send(200, body, TYPES[path.rsplit(".", 1)[1]])
            )
        if path.startswith("/web/") and path[5:] in WEB_FILES:
            return self._send(200, _web(path[5:]), TYPES[path.rsplit(".", 1)[1]])
        return self._send(404, b"not found")

    def _api_get(self, path: str, q: dict):
        one = lambda k: (q.get(k) or [""])[0][:300]
        who = _person()
        try:
            if path == "/api/today":
                return self._json(api.today(self.root, who))
            if path == "/api/notes":
                return self._json(api.notes_list(self.root, who, one("group") or None))
            if path == "/api/find":
                return self._json(api.notes_find(self.root, who, one("q")))
            if path == "/api/note":
                return self._json(api.notes_show(self.root, who, one("id")))
            if path == "/api/rules":
                s = store.settings(self.root)["parts"].get("notes")
                return self._json({"notes": s, "read": store.READ_WORDS, "write": store.WRITE_WORDS})
            if path == "/api/calendar":
                p = store.settings(self.root)["parts"].get("calendar")
                if not p or not p["on"]:
                    return self._json({"on": False})
                frm = one("from") or None
                days = 1 if one("days") == "1" else 7
                return self._json(
                    {
                        "on": True,
                        "state": cal_mod.state(self.root),
                        "week": api.calendar_week(self.root, who, frm, days),
                        "levels": cal_mod.LEVEL_WORDS,
                        "moves_words": cal_mod.MOVES_WORDS,
                    }
                )
            if path == "/api/tickets":
                return self._json({"tickets": _open_tickets(self.root)})
        except Refused as e:
            return self._json({"error": str(e)}, 409)
        return self._send(404, b"not found")

    def do_POST(self):
        path = self.path.partition("?")[0]
        if path != "/api/act":
            return self._refuse()
        why = self._fence("POST", True)
        if why:
            return self._send(403, why.encode())
        if self.headers.get("Sec-Fetch-Site") not in ("same-origin", "none"):
            return self._send(403, b"This request came from another website and was refused.")
        if not self._vouched():
            return self._send(403, FROM_DASHBOARD.encode())
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            return self._send(415, b"send JSON")
        try:
            n = int(self.headers.get("Content-Length") or "")
            body = json.loads(self.rfile.read(n)) if 0 < n <= MAX_BODY else None
        except (ValueError, OSError, RecursionError):
            body = None
        if (
            not isinstance(body, dict)
            or body.get("op") not in OPS
            or not isinstance(body.get("args", {}), dict)
        ):
            return self._send(400, b"That request could not be read.")
        try:
            return self._json({"result": _act(self.root, body["op"], body.get("args") or {})})
        except Refused as e:
            return self._json({"error": str(e)}, 409)


def _s(args: dict, key: str) -> str:
    v = args.get(key)
    if not isinstance(v, str) or not v.strip() or len(v) > 1000:
        raise Refused("Something is missing in that click. Reload the page and try again.")
    return v


def _act(root: Path, op: str, args: dict):
    who = _person()
    if op == "add":
        return api.add_part(root, who, _s(args, "part"))
    if op == "remove":
        api.remove_part(root, who, _s(args, "part"))
        return {"on": False}
    if op == "folder":
        return api.set_folder(root, who, _s(args, "path"))
    if op == "rules":
        read, write = args.get("read"), args.get("write")
        return api.set_rules(
            root,
            who,
            "notes",
            read if isinstance(read, str) else None,
            write if isinstance(write, str) else None,
        )
    if op in ("way_on", "way_off"):
        return api.way_turn(root, who, _s(args, "way"), op == "way_on")
    if op == "way_check":
        return api.way_check(root, who, _s(args, "way"))
    if op == "cal_level":
        return api.calendar_rule(root, who, _s(args, "id"), _s(args, "level"), None)
    if op == "cal_moves":
        return api.calendar_rule(root, who, None, None, _s(args, "moves"))
    if op == "cal_allow":
        return api.calendar_allow(root, who)
    if op == "cal_check":
        return api.calendar_check(root, who)
    if op in ("cal_accept", "cal_decline"):
        return api.calendar_answer(root, who, _s(args, "id"), op == "cal_accept")
    if op == "use":
        ticket = _s(args, "ticket")
        if (
            not re.fullmatch(r"t_[a-z0-9]{6,16}", ticket)
            or not (root / ".orch" / "tickets" / f"{ticket}.json").is_file()
        ):
            raise Refused("That ticket is not there any more. Reload the page and pick another.")
        return api.use(root, who, ticket, "notes", _s(args, "id"))
    raise Refused("Unknown action.")


def _open_tickets(root: Path) -> list[dict]:
    """Open tickets for Use in a ticket: read straight from the ticket files (plain JSON, R1.3), newest first."""
    rows = []
    for f in (root / ".orch" / "tickets").glob("t_*.json"):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(t, dict) or t.get("status") in ("review", "done", "dropped"):
            continue
        rows.append(
            {
                "id": t.get("id") or f.stem,
                "key": t.get("key") or "",
                "title": str(t.get("title") or "")[:120],
                "status": t.get("status") or "",
                "updated": t.get("updated_at") or t.get("created_at") or "",
            }
        )
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows[:30]


def make_server(root: Path, port: int = DEFAULT_PORT, vouch=None) -> ThreadingHTTPServer:
    root = root.resolve()
    return ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, root=root, vouch=vouch))
