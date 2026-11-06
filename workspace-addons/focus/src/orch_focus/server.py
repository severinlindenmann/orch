"""Focus page server: stdlib HTTP on 127.0.0.1 with its own port. GET reads; the only POST is /api/act
(the fixed op table in actions.py). Host/Origin are checked by orch_ui.origin on every request."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from . import actions
from .board import Board, TicketWatcher
from .events import EventLog

DEFAULT_PORT = 8430
MAX_BODY = 16384
TID_RE = re.compile(r"t_[a-z0-9]{6,16}")
TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
}  # fmt: skip
KIT_FILES = ("tokens.css", "components.css", "motion.css", "icons.js", "motion.js", "question-card-state.js",
             "question-card.js", "evidence.js")  # fmt: skip
WEB_FILES = ("index.html", "focus.js", "focus.css", "logo.svg")
CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'; frame-ancestors 'none'; base-uri 'none'"


def _web(name: str) -> bytes:
    return resources.files("orch_focus").joinpath("web", name).read_bytes()


def _kit(name: str) -> bytes:
    import orch_ui

    return (Path(orch_ui.__file__).parent / "static" / name).read_bytes()


def _read_ticket(root: Path, tid: str) -> dict | None:
    p = root / ".orch" / "tickets" / f"{tid}.json"
    try:
        if p.is_symlink():
            return None
        t = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return t if isinstance(t, dict) else None


class Tracker:
    """Per ticket: turns ticket changes into run events (written to the log) and folds the log into a Board."""

    def __init__(self, root: Path, orch_bin: str | None):
        self.root, self.orch_bin = root, orch_bin
        self.lock = threading.Lock()
        self.tickets: dict[str, dict] = {}
        self.status_cache: dict[str, tuple[float, dict]] = {}
        self.started: set[str] = set()  # tickets whose run Focus started (stopped again when Focus ends)

    def run_status(self, tid: str) -> dict:
        hit = self.status_cache.get(tid)
        if hit and time.time() - hit[0] < 1.0:
            return hit[1]
        data: dict = {"running": False}
        try:
            code, out, _ = actions.orch(
                self.root, self.orch_bin, ["run", "status", tid, "--json"], timeout=15
            )
            if code == 0:
                data = json.loads(out)
        except (actions.Unavailable, ValueError):
            pass
        self.status_cache[tid] = (time.time(), data)
        return data

    def view(self, tid: str) -> dict | None:
        ticket = _read_ticket(self.root, tid)
        if ticket is None:
            return None
        status = self.run_status(tid)
        claim = status.get("claim") or {}
        run = claim.get("run") if isinstance(claim.get("run"), str) else None
        with self.lock:
            tr = self.tickets.get(tid)
            if run and (tr is None or tr["run"] != run):
                log = EventLog(self.root, run)
                tr = {"run": run, "log": log, "offset": 0, "board": Board(), "events": [],
                      "watcher": TicketWatcher(run, tid)}  # fmt: skip
                tr["watcher"].feed(ticket, prime=True)
                self.tickets[tid] = tr
            events: list[dict] = []
            if tr:
                new = tr["watcher"].feed(ticket)
                if new:
                    try:
                        tr["log"].append(*new)
                    except OSError:
                        pass
                got, tr["offset"] = tr["log"].read(tr["offset"])
                for e in got:
                    tr["board"].apply(e)
                tr["events"] = (tr["events"] + got)[-80:]
                tr["board"].resolve_asks(ticket)
                events = tr["events"]
            board = tr["board"].snapshot() if tr else Board().snapshot()
        return self._shape(ticket, status, claim, board, events)

    @staticmethod
    def _shape(ticket: dict, status: dict, claim: dict, board: dict, events: list[dict]) -> dict:
        checks = ticket.get("checklist") or []
        questions = ticket.get("questions") or []
        open_q = [q for q in questions if q.get("answer") is None]
        running = bool(status.get("running"))
        if open_q:
            state = "needs"
        elif running:
            state = "working"
        elif ticket.get("status") == "done":
            state = "done"
        else:
            state = "stopped"
        agent = claim.get("agent") or "agent"
        return {
            "ticket": {
                "id": ticket.get("id"), "title": ticket.get("title"), "status": ticket.get("status"),
                "revision": ticket.get("revision", 0), "checklist": checks, "questions": questions,
                "history": (ticket.get("history") or [])[-80:],
            },
            "run": {
                "running": running, "mode": claim.get("mode"), "agent": agent, "run": claim.get("run"),
                "started_at": claim.get("started_at"), "pending": status.get("pending", 0),
            },
            "state": state,
            "generic": agent != "claude",
            "live": claim.get("mode") == "live",
            "board": board,
            "events": events[-60:],
            "done": sum(1 for c in checks if c.get("done")),
            "total": len(checks),
        }  # fmt: skip

    def tickets_list(self) -> list[dict]:
        d = self.root / ".orch" / "tickets"
        out = []
        for p in sorted(d.glob("t_*.json")) if d.is_dir() else []:
            t = _read_ticket(self.root, p.stem)
            if t and t.get("status") in ("open", "active", "waiting") and TID_RE.fullmatch(p.stem):
                out.append({"id": t["id"], "title": t.get("title", ""), "status": t["status"]})
        return out[:200]


class Handler(BaseHTTPRequestHandler):
    timeout = 10

    def __init__(self, *a, root: Path, orch_bin: str | None, tracker: Tracker, **kw):
        self.root, self.orch_bin, self.tracker = root, orch_bin, tracker
        self.nonce = os.environ.get("ORCH_FOCUS_NONCE", "")
        super().__init__(*a, **kw)

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, data):
        self._send(code, json.dumps(data).encode(), "application/json")

    def _fence(self, method: str, api: bool) -> str | None:
        """Host + Origin check of orch_ui.origin. A POST without Origin is refused too: the page always sends one."""
        try:
            from orch_ui.origin import check_request
        except ImportError:
            return "Focus is not available in this install."
        if method == "POST" and self.headers.get("Origin") is None:
            return "This request was refused (no origin)."
        return check_request(method, self.headers, self.server.server_address[1], api=api)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if (
            path == "/ready" and self.nonce
        ):  # challenge-response for start/stop; the nonce itself is never sent
            c = self.path.partition("?c=")[2]
            if not re.fullmatch(r"[0-9a-f]{32,64}", c):
                return self._send(404, b"not found", "text/plain")
            m = hmac.new(self.nonce.encode(), c.encode(), hashlib.sha256).hexdigest()
            return self._json(200, {"pid": os.getpid(), "mac": m})
        why = self._fence("GET", path.startswith("/api/"))
        if why:
            return self._send(403, why.encode(), "text/plain; charset=utf-8")
        if path == "/api/tickets":
            return self._json(200, self.tracker.tickets_list())
        m = re.fullmatch(r"/api/t/(t_[a-z0-9]{6,16})", path)
        if m:
            v = self.tracker.view(m.group(1))
            return self._json(200, v) if v else self._send(404, b"no such ticket", "text/plain")
        if path == "/" or re.fullmatch(r"/t/t_[a-z0-9]{6,16}", path):
            return self._send(200, _web("index.html"), TYPES[".html"])
        if path.startswith("/kit/") and path[5:] in KIT_FILES:
            return self._send(200, _kit(path[5:]), TYPES["." + path.rsplit(".", 1)[1]])
        if path.startswith("/web/") and path[5:] in WEB_FILES:
            return self._send(200, _web(path[5:]), TYPES["." + path.rsplit(".", 1)[1]])
        self._send(404, b"not found", "text/plain")

    def _refuse(self):
        self._send(405, b"not allowed", "text/plain")

    do_PUT = do_DELETE = do_PATCH = _refuse

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/act":
            return self._refuse()
        why = self._fence("POST", True)
        if why:
            return self._send(403, why.encode(), "text/plain; charset=utf-8")
        if (self.headers.get("Sec-Fetch-Site") or "same-origin") not in ("same-origin", "none"):
            return self._send(403, b"This request came from another website and was refused.", "text/plain")
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
        args = body.get("args", {})
        try:
            code, text, extra = actions.run_op(self.root, self.orch_bin, body.get("op"), args)
        except actions.BadRequest as e:
            return self._send(400, str(e).encode(), "text/plain; charset=utf-8")
        except actions.Unavailable as e:
            return self._send(503, str(e).encode(), "text/plain; charset=utf-8")
        self.tracker.status_cache.clear()
        if code == 200 and body.get("op") == "run.start":
            self.tracker.started.add(args["ticket"])
        if code != 200:
            hdr = {"X-Revision": str(extra["revision"])} if extra else None
            return self._send(code, text.encode(), "text/plain; charset=utf-8", hdr)
        tid = args.get("ticket") if isinstance(args, dict) else None
        view = self.tracker.view(tid) if isinstance(tid, str) and TID_RE.fullmatch(tid) else None
        self._json(200, {"result": extra, "view": view})


def stop_started(srv) -> None:
    """Focus ends: every run it started ends through core `orch run stop` (FO-07 a)."""
    tracker = srv.RequestHandlerClass.keywords["tracker"]
    for tid in sorted(tracker.started):
        try:
            actions.orch(tracker.root, tracker.orch_bin, ["run", "stop", tid, "--by", "focus"], timeout=20)
        except actions.Unavailable:
            pass
    tracker.started.clear()


def make_server(root: Path, port: int = DEFAULT_PORT, orch_bin: str | None = None) -> ThreadingHTTPServer:
    orch_bin = orch_bin if orch_bin is not None else os.environ.get("ORCH_BIN") or None
    tracker = Tracker(root, orch_bin)
    return ThreadingHTTPServer(
        ("127.0.0.1", port), partial(Handler, root=root, orch_bin=orch_bin, tracker=tracker)
    )
