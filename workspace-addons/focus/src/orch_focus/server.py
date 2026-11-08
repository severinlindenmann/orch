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
from urllib.parse import parse_qs, unquote

from . import actions, adapterdata, chat, proofs, runfiles
from .board import Board, TicketWatcher
from .events import RUN_ID, EventLog, for_display
from .permissions import Permissions
from .revisions import Revisions
from .tail import Tail

DEFAULT_PORT = 8430
MAX_BODY = 16384
TID_RE = re.compile(r"t_[a-z0-9]{6,16}")
TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
}  # fmt: skip
KIT_FILES = ("tokens.css", "components.css", "motion.css", "icons.js", "motion.js", "question-card-state.js",
             "question-card.js", "evidence.js")  # fmt: skip
WEB_FILES = ("index.html", "focus.js", "proof.js", "helpers.js", "focus.css", "logo.svg")
PREFIX = re.compile(
    r"/addon/[a-z][a-z0-9-]{1,31}"
)  # set by the dashboard when it shows this page under its own address
CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'; frame-ancestors 'none'; base-uri 'none'"


def _web(name: str) -> bytes:
    return resources.files("orch_focus").joinpath("web", name).read_bytes()


def _kit(name: str) -> bytes:
    import orch_ui

    return (Path(orch_ui.__file__).parent / "static" / name).read_bytes()


class Tracker:
    """Per ticket: turns ticket changes into run events (written to the log) and folds the log into a Board."""

    def __init__(self, root: Path, orch_bin: str | None):
        self.root, self.orch_bin = root, orch_bin
        self.lock = threading.Lock()
        self.seen_sig = ""
        self.tickets: dict[str, dict] = {}
        self.status_cache: dict[str, tuple[float, dict]] = {}
        # ticket -> run id, for the runs Focus started (kept in .orch/run/focus/ so a crash is recoverable)
        self.started: dict[str, str] = self._load_started()
        self.perms = Permissions(root, orch_bin)
        self.last_agent: dict[str, tuple[str, str]] = {}  # ticket -> (agent, mode) of its latest run
        self.ticket_cache: dict[str, tuple[float, dict | None]] = {}
        self.lookup_cache = {}
        self.session_cache: dict[str, tuple[float, str, str | None]] = {}

    def lookup(self, key, argv, ttl=30):
        hit = self.lookup_cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        data = None
        try:
            code, out, _ = actions.orch(self.root, self.orch_bin, argv, timeout=5)
            if code == 0:
                data = json.loads(out)
        except (actions.Unavailable, ValueError, RecursionError):
            pass
        self.lookup_cache[key] = (time.monotonic(), data)
        return data

    def agents(self):
        data = self.lookup("agents", ["agents", "--json"])
        return [a for a in data if isinstance(a, dict)] if isinstance(data, list) else []

    def mobile(self):
        data = self.lookup("mobile", ["relay", "mobile", "status", "--json"], ttl=1)
        available = isinstance(data, dict) and isinstance(data.get("on"), bool)
        return {"available": available, "on": data["on"] if available else False}

    def workspace(self):
        data = self.lookup("workspace", ["status", "--json"])
        if isinstance(data, list):
            data = next((w for w in data if isinstance(w, dict) and w.get("workspace") == str(self.root.resolve())), {})
        name = (data.get("name") or data.get("workspace")) if isinstance(data, dict) else None
        if isinstance(name, dict):
            name = name.get("name")
        return Path(name).name if isinstance(name, str) and name else self.root.name

    def _started_file(self) -> Path:
        return runfiles.run_dir(self.root, "focus") / "started.json"

    def _load_started(self) -> dict[str, str]:
        try:
            d = runfiles.read_json(self._started_file()) or {}
        except RuntimeError:
            return {}
        return {
            t: r
            for t, r in d.items()
            if TID_RE.fullmatch(str(t)) and isinstance(r, str) and RUN_ID.fullmatch(r)
        }

    def _save_started(self) -> None:
        try:
            runfiles.write_json(self._started_file(), self.started)
        except (RuntimeError, OSError):
            pass

    def note_started(self, tid: str, run) -> None:
        if isinstance(run, str) and RUN_ID.fullmatch(run):
            self.started[tid] = run
            self._save_started()

    def mark_page(self, tid: str) -> None:
        """Once per ticket: ext.focus.page = t/<id>, so the ticket page can show 'Open live page'."""
        want = f"t/{tid}"
        cur = ((self.ticket(tid) or {}).get("ext") or {}).get("focus") or {}
        if cur.get("page") == want:
            return
        try:
            actions.orch(
                self.root,
                self.orch_bin,
                ["ext", "set", tid, "focus", json.dumps({"page": want}), "--by", "agent:focus", "--json"],
                timeout=20,
            )
        except actions.Unavailable:
            pass
        self.ticket_cache.pop(tid, None)

    def forget_started(self, tid: str) -> None:
        if self.started.pop(tid, None) is not None:
            self._save_started()

    def ticket(self, tid: str) -> dict | None:
        """The ticket, as `orch ticket show --json` says it (core owns the file; one answer a second)."""
        hit = self.ticket_cache.get(tid)
        if hit and time.time() - hit[0] < 1.0:
            return hit[1]
        doc = None
        try:
            code, out, _ = actions.orch(
                self.root, self.orch_bin, ["ticket", "show", tid, "--json"], timeout=15
            )
            if code == 0:
                doc = json.loads(out)
        except (actions.Unavailable, ValueError, RecursionError):
            pass
        doc = doc if isinstance(doc, dict) and doc.get("id") == tid else None
        self.ticket_cache[tid] = (time.time(), doc)
        return doc

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
        if not TID_RE.fullmatch(tid):
            return None
        ticket = self.ticket(tid)
        if ticket is None:
            return None
        status = self.run_status(tid)
        claim = status.get("claim") or {}
        run = (
            claim.get("run") if isinstance(claim.get("run"), str) and RUN_ID.fullmatch(claim["run"]) else None
        )
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
                mode, agent = claim.get("mode"), claim.get("agent")
                if isinstance(mode, str) and isinstance(agent, str):
                    self.last_agent[tid] = (agent, mode)
                    if tr.get("tail") is None:
                        tr["tail"] = Tail(
                            self.root, tid, run, agent, mode, session=lambda: self.session(tid, agent)
                        )
                if tr.get("tail") is not None:
                    tr["tail"].poll()
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
        if tr:
            last = self.last_agent.get(tid, (None, None))[0]
            label = str(claim.get("agent") or last or "The agent").capitalize()
            if self.perms.sync(
                tid, claim, bool(status.get("running")), tr["run"], board["denials"], ticket, label
            ):
                self.status_cache.pop(tid, None)
                self.ticket_cache.pop(tid, None)
        if run is None and claim.get("run") is not None:
            claim = {**claim, "run": None}  # an id that is not a run id is unknown
        v = self._shape(ticket, status, claim, board, events, self.is_generic(claim, tid), self.agents())
        mobile = self.mobile()
        v["capabilities"] = {"phone_mode": mobile["available"]}
        v["phone_mode"] = mobile["on"]
        v["page_key"] = proofs.page_key(tid)
        v["retry_error"] = None if v["run"]["running"] else self.perms.failed.get(tid)
        return v

    @staticmethod
    def _shape(
        ticket: dict, status: dict, claim: dict, board: dict, events: list[dict], generic: bool, agents: list[dict] | None = None
    ) -> dict:
        checks = ticket.get("checklist") or []
        questions = ticket.get("questions") or []
        open_q = [q for q in questions if q.get("answer") is None]
        running = bool(status.get("running"))
        attention = running and (claim.get("live") or {}).get("state") == "attention"
        if open_q or attention:
            state = "needs"
        elif running and (claim.get("live") or {}).get("state") == "idle":
            state = "waiting"  # a live session that waits for a message: not working
        elif running:
            state = "working"
        elif ticket.get("status") == "done":
            state = "done"
        else:
            state = "stopped"
        agent = claim.get("agent") or "agent"
        agents = agents or []
        label = (claim.get("label")
                 or next((a.get("label") for a in agents if a.get("name") == claim.get("agent")), None)
                 or (str(claim["agent"])[:1].upper() + str(claim["agent"])[1:] if claim.get("agent") else None)
                 or next((a.get("label") for a in agents if a.get("chosen")), None)
                 or "agent")
        return {
            "ticket": {
                "id": ticket.get("id"), "key": ticket.get("key"), "title": ticket.get("title"),
                "status": ticket.get("status"), "closed_at": ticket.get("closed_at"),
                "started": bool(ticket.get("started") or (ticket.get("ticket_view") or {}).get("started") or claim.get("run")),
                "revision": ticket.get("revision", 0), "checklist": checks, "questions": questions,
                "history": (ticket.get("history") or [])[-80:],
            },
            "run": {
                "running": running, "mode": claim.get("mode"), "agent": agent, "label": label, "run": claim.get("run"),
                "started_at": claim.get("started_at"), "pending": status.get("pending", 0),
            },
            "state": state,
            "generic": generic,
            "attention": bool(attention),
            "why": str((claim.get("live") or {}).get("why") or "")[:400] if attention else "",
            "live": claim.get("mode") == "live",
            "board": board,
            "events": for_display(events[-60:]),
            "done": sum(1 for c in checks if c.get("done")),
            "total": len(checks),
        }  # fmt: skip

    def session(self, tid: str, agent: str) -> str | None:
        hit = self.session_cache.get(tid)
        if hit and time.time() - hit[0] < 5.0 and hit[1] == agent:
            return hit[2]
        found = self._session(tid, agent)
        self.session_cache[tid] = (time.time(), agent, found)
        return found

    def _session(self, tid: str, agent: str) -> str | None:
        try:
            code, out, _ = actions.orch(
                self.root, self.orch_bin, ["run", "session", tid, "--agent", agent, "--json"], timeout=15
            )
            return json.loads(out).get("session") if code == 0 else None
        except (actions.Unavailable, ValueError, AttributeError):
            return None

    def is_generic(self, claim: dict, tid: str) -> bool:
        """Generic = the agent's adapter names no live-steps mapper (adapter data, not the agent's name)."""
        agent, mode = claim.get("agent"), claim.get("mode")
        if not (isinstance(agent, str) and isinstance(mode, str)):
            agent, mode = self.last_agent.get(tid, (None, None))
        if not agent:
            return True
        return adapterdata.events_kind(self.root, agent, mode or "oneshot") is None

    def tickets_list(self) -> list[dict]:
        try:
            code, out, _ = actions.orch(
                self.root, self.orch_bin, ["ticket", "list", "--all", "--json"], timeout=15
            )
            rows = json.loads(out) if code == 0 else []
        except (actions.Unavailable, ValueError, RecursionError):
            rows = []
        out = []
        for t in rows if isinstance(rows, list) else []:
            if (
                isinstance(t, dict)
                and TID_RE.fullmatch(str(t.get("id")))
                and t.get("status")
                in (
                    "open",
                    "ready",
                    "active",
                    "waiting",
                    "review",
                    "done",
                )  # a done ticket opens as a read-only board
            ):
                questions = [q for q in t.get("questions", []) if q.get("answer") is None]
                started = bool(t.get("started") or (t.get("ticket_view") or {}).get("started"))
                next_step = ("Done" if t["status"] == "done" else "Answer" if questions
                             else "Check the result" if t["status"] == "review"
                             else "Working…" if t["status"] == "active"
                             else "Paused" if started or t["status"] == "waiting" else "Start")
                out.append(
                    {
                        "id": t["id"], "next_step": next_step, "question_count": len(questions),
                        "key": t.get("key"),
                        "title": str(t.get("title", ""))[:200],
                        "status": t["status"],
                        "started": bool(t.get("started") or (t.get("ticket_view") or {}).get("started")),
                    }
                )
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
        if "Content-Security-Policy" not in (extra or {}):
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
        path = re.sub(r"^/{2,}", "/", path)  # a surface may join the page path and the value with an extra /
        why = self._fence("GET", path.startswith("/api/"))
        if why:
            return self._send(403, why.encode(), "text/plain; charset=utf-8")
        if path == "/api/tickets":
            return self._json(200, {"workspace": self.tracker.workspace(), "tickets": self.tracker.tickets_list()})
        if path == "/api/mobile":
            return self._json(200, self.tracker.mobile())
        if path == "/api/events":
            return self._events()
        m = re.fullmatch(r"/api/t/(t_[a-z0-9]{6,16})", path)
        if m:
            if "fresh=1" in self.path.partition("?")[2].split("&"):
                # a pushed change: drop the 1 s caches once per change of the workspace files (one `orch` call
                # per change, not per request), however old the cached answer is
                sig = self.server.revisions.signature()
                if sig != self.tracker.seen_sig:
                    self.tracker.seen_sig = sig
                    self.tracker.ticket_cache.clear()
                    self.tracker.lookup_cache.pop("mobile", None)
                    self.tracker.status_cache.clear()
            v = self.tracker.view(m.group(1))
            return self._json(200, v) if v else self._send(404, b"no such ticket", "text/plain")
        if path == "/api/file":  # one proof file of a ticket, read by orch.safefile only (proofs.py)
            q = parse_qs(self.path.partition("?")[2], keep_blank_values=True)
            one = lambda k: (q.get(k) or [""])[0]
            code, body, ctype, extra = proofs.read(self.root, one("t"), one("n"), one("m") or "view")
            return self._send(code, body, ctype, {"Cross-Origin-Resource-Policy": "same-origin", **extra})
        m = re.fullmatch(r"/page/(t_[a-z0-9]{6,16})/([0-9a-f]{16})/(.+)", path)
        if m:  # a page of a ticket and the files it loads, by path so relative links resolve (proofs.read_page)
            code, body, ctype, extra = proofs.read_page(self.root, m.group(1), m.group(2), unquote(m.group(3)))
            return self._send(code, body, ctype, {"Cross-Origin-Resource-Policy": "same-origin", **extra})
        if path == "/" or re.fullmatch(r"(/t)?/t/t_[a-z0-9]{6,16}", path):
            pre = self.headers.get("X-Forwarded-Prefix") or ""
            pre = pre if PREFIX.fullmatch(pre) else ""
            return self._send(200, _web("index.html").replace(b"__P__", pre.encode()), TYPES[".html"])
        if path.startswith("/kit/") and path[5:] in KIT_FILES:
            return self._send(200, _kit(path[5:]), TYPES["." + path.rsplit(".", 1)[1]])
        if path.startswith("/web/") and path[5:] in WEB_FILES:
            return self._send(200, _web(path[5:]), TYPES["." + path.rsplit(".", 1)[1]])
        self._send(404, b"not found", "text/plain")

    def _events(self):
        """Server-sent events: one `rev` event whenever a ticket or run file changes (same stream as the dashboard's)."""
        origin, host = self.headers.get("Origin"), (self.headers.get("Host") or "").strip().lower()
        if (
            origin is not None and origin.lower() != f"http://{host}"
        ):  # as the dashboard's stream: a foreign page may not listen
            return self._send(403, b"forbidden", "text/plain")
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
        except OSError:
            pass
        finally:
            revisions.leave()

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
        self.tracker.lookup_cache.pop("mobile", None)
        self.tracker.status_cache.clear()
        self.tracker.ticket_cache.clear()  # the view sent back must show what this action just did
        if code == 200 and body.get("op") == "run.start":
            self.tracker.note_started(args["ticket"], (extra or {}).get("run"))
            self.tracker.mark_page(args["ticket"])
        elif code == 200 and body.get("op") == "run.stop":
            self.tracker.forget_started(args["ticket"])
        if code != 200:
            hdr = {"X-Revision": str(extra["revision"])} if extra else None
            return self._send(code, text.encode(), "text/plain; charset=utf-8", hdr)
        tid = args.get("ticket") if isinstance(args, dict) else None
        view = self.tracker.view(tid) if isinstance(tid, str) and TID_RE.fullmatch(tid) else None
        note = None
        if body.get("op") == "run.send":
            note = chat.note(extra, bool(view and view["run"]["running"]), bool(view and view["live"]), any(q.get("answer") is None for q in view["ticket"].get("questions", [])) if view else False)
        self._json(200, {"result": extra, "view": view, "note": note})


def stop_started(srv) -> None:
    """Focus ends: a run Focus started ends through core `orch run stop` (FO-07 a), but only when the claim
    on that ticket is still that run, started by Focus. A run someone else started later is never touched."""
    tracker = srv.RequestHandlerClass.keywords["tracker"]
    for tid, run in sorted(tracker.started.items()):
        tracker.status_cache.pop(tid, None)
        claim = tracker.run_status(tid).get("claim") or {}
        if claim.get("run") == run and claim.get("by") == "focus":
            try:
                actions.orch(
                    tracker.root, tracker.orch_bin, ["run", "stop", tid, "--by", "focus"], timeout=20
                )
            except actions.Unavailable:
                pass
    tracker.started.clear()
    tracker._save_started()


class _Server(ThreadingHTTPServer):
    def server_close(self):
        if hasattr(self, "revisions"):  # not yet set when the bind failed
            self.revisions.close()
        super().server_close()


def make_server(root: Path, port: int = DEFAULT_PORT, orch_bin: str | None = None) -> ThreadingHTTPServer:
    orch_bin = orch_bin if orch_bin is not None else os.environ.get("ORCH_BIN") or None
    tracker = Tracker(root, orch_bin)
    srv = _Server(("127.0.0.1", port), partial(Handler, root=root, orch_bin=orch_bin, tracker=tracker))
    srv.revisions = Revisions(root)
    return srv
