"""Tiny fake of `orch review` for browser checks of review.html (not used by pytest).
Usage: python3 fake_review_server.py PORT   -> / = review.html, /kit/<file> = orch_ui/static, /api/* fake data."""

import json, sys, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "static"
PAGE = lambda t, b: (
    f"<!doctype html><title>{t}</title><body style='font:16px system-ui;padding:24px'>{b}</body>"
)
FILES = {
    "before.html": PAGE("Before", "<h1>Home</h1><p>Cards for questions and work.</p>"),
    "after.html": PAGE("After", "<h1>Home</h1><p>New: what changed today.</p>"),
    "a.html": PAGE("A", "<h1>A</h1>"),
    "b.html": PAGE("B", "<h1>B</h1>"),
}
CARDS = [
    {
        "id": "core:q:T-1:q1",
        "ticket": "T-1",
        "key": "DT-41",
        "digest": "d1",
        "since": "2026-11-15T09:12:00",
        "card": {
            "kind": "draft",
            "title": "Home: What changed today block",
            "why": "The helper drew a new block for the top of Home.",
            "need": "Blocks the Home update",
            "then": "The helper builds it. You check it again before anyone sees it.",
            "ok_label": "Build it",
            "preview": {
                "type": "compare",
                "before": {"type": "page", "src": "reviewed/aaaaaaaaaaaa/before.html"},
                "after": {"type": "page", "src": "reviewed/aaaaaaaaaaaa/after.html"},
            },
        },
    },
    {
        "id": "core:q:T-2:q1",
        "ticket": "T-2",
        "key": "DT-45",
        "digest": "d2",
        "since": "2026-11-15T10:20:00",
        "card": {
            "kind": "choice",
            "title": "Home: which layout?",
            "why": "Tap the one you want.",
            "then": "The helper builds the one you pick.",
            "preview": {
                "type": "options",
                "options": [
                    {
                        "id": "A",
                        "title": "As today",
                        "preview": {"type": "page", "src": "reviewed/bbbbbbbbbbbb/a.html"},
                        "text": "Cards.",
                    },
                    {
                        "id": "B",
                        "title": "Recent changes first",
                        "suggested": True,
                        "preview": {"type": "page", "src": "reviewed/bbbbbbbbbbbb/b.html"},
                        "text": "A list.",
                    },
                ],
            },
        },
    },
    {
        "id": "core:q:T-3:q1",
        "ticket": "T-3",
        "key": "DT-35",
        "digest": "d3",
        "since": "2026-11-14T17:05:00",
        "card": {
            "kind": "plan",
            "title": "Start the work on the new start page",
            "why": "Four steps.",
            "then": "The helper starts now.",
            "ok_label": "Start work",
            "preview": {
                "type": "doc",
                "heading": "Plan",
                "steps": ["Draw ideas", "You pick", "Build it", "You check"],
            },
        },
    },
]
ANSWERED = [
    {
        "id": "core:q:T-9:q2",
        "ticket": "T-9",
        "by": "Severin",
        "via": "page",
        "at": "2026-11-15T09:30:00",
        "card": CARDS[1]["card"],
        "shown": {"copy": "reviewed/bbbbbbbbbbbb/", "files": {"b.html": "x"}},
        "decision": {
            "action": "use_with_changes",
            "picked": "B",
            "changes": ["Dates on the left"],
            "summary": "Use B with 1 change",
            "words": {"text": "Take B, but dates on the left."},
            "pins": [{"n": 1, "on": "option B", "x": 40, "y": 55, "text": "Dates here"}],
        },
    }
]
STATE = {"signed": False, "gone": set(), "fail": None}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        b = (
            body
            if isinstance(body, bytes)
            else (body if isinstance(body, str) else json.dumps(body)).encode()
        )
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            return self.send(200, (STATIC / "review.html").read_bytes(), "text/html")
        if u.path.startswith("/kit/"):
            return self.send(
                200,
                (STATIC / u.path[5:]).read_bytes(),
                "text/css" if u.path.endswith(".css") else "application/javascript",
            )
        if u.path.startswith("/api/") and not STATE["signed"]:
            return self.send(401, {"error": "sign in"})
        if u.path == "/api/stack":
            return self.send(
                200,
                {"workspace": "Demo workspace", "cards": [c for c in CARDS if c["id"] not in STATE["gone"]]},
            )
        if u.path == "/api/answered":
            return self.send(200, ANSWERED)
        if u.path == "/api/file":
            return self.send(200, FILES.get(q["n"][0], "x"), "text/html")
        self.send(404, {})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/session":
            STATE["signed"] = bool(body.get("token"))
            return self.send(200, {"ok": True})
        if self.path == "/api/answer":
            if STATE["fail"]:
                return self.send(409, {"ok": False, "error": {"code": STATE["fail"], "message": "x"}})
            STATE["gone"].add(body["id"])
            return self.send(200, {"ok": True})
        self.send(404, {})


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
