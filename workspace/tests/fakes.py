"""In-process fake publish and relay servers that follow contracts/review/*-api.examples.json."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

WS = "ws_pilatus001"


class Fake:
    """Subclass: set `prefix` (orp_/orn_), fill `routes`. Call .start(); .url is the base."""

    prefix = "orp_"
    token = "orp_" + "A" * 43

    def __init__(self):
        self.calls: list[tuple[str, str, dict, bytes]] = []
        self.routes: list = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _do(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                u = urlparse(self.path)
                hdrs = {k: v for k, v in self.headers.items()}
                fake.calls.append((self.command, self.path, hdrs, body))
                if hdrs.get("X-Orch-Workspace") != WS or hdrs.get("Authorization") != f"Bearer {fake.token}":
                    return self._send(
                        401, {"error": "unauthorized", "message": "Workspace ID or token is wrong."}
                    )
                for method, rx, fn in fake.routes:
                    m = re.fullmatch(rx, u.path)
                    if method == self.command and m:
                        res = fn(m, parse_qs(u.query), body)
                        return self._send(*res)
                self._send(404, {"error": "not_found", "message": "No such route."})

            def _send(self, status, obj=None, raw=None):
                data = raw if raw is not None else (b"" if obj is None else json.dumps(obj).encode())
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _do

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def route(self, method, rx, fn):
        self.routes.append((method, rx, fn))

    def start(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def add_profile(f: Fake, extra: dict) -> None:
    """GET /v1/whoami and PATCH /v1/me over one shared profile (description, tags)."""
    f.me = {"id": WS, "name": "Pilatus Workspace", "description": "d", "tags": [], "pending": None, **extra}
    f.route("GET", "/v1/whoami", lambda m, q, b: (200, f.me))

    def patch_me(m, q, body):
        req = json.loads(body)
        d, t = req.get("description"), req.get("tags")
        if d is not None and (not isinstance(d, str) or len(d) > 280):
            return 422, {"error": "invalid", "message": "description must be at most 280 characters."}
        if t is not None and (not isinstance(t, list) or len(t) > 8 or any(len(x) > 24 for x in t)):
            return 422, {"error": "invalid", "message": "tags: up to 8, each up to 24 characters."}
        # Like the real servers: only a proposal; the live values stay until the owner approves.
        if d is None and t is None:
            return 422, {"error": "invalid", "message": "Send a description and/or tags."}
        f.me = {**f.me, "pending": {"description": d, "tags": t, "at": "2026-11-04T13:05:00Z", "rev": "r1"}}
        return 202, {**f.me, "status": "pending"}

    f.route("PATCH", "/v1/me", patch_me)


def make_publish() -> Fake:
    f = Fake()
    f.files, f.apps = {}, {}
    add_profile(
        f,
        {
            "rights": {"files": True, "apps": True, "permanent": False, "public": False},
            "max_file_mb": 100,
            "default_days": 7,
            "max_days": 90,
        },
    )

    def post_file(m, q, body):
        if q.get("permanent"):
            return 403, {"error": "forbidden", "message": "This workspace may not make permanent files."}
        fid = "f_" + hashlib.sha256(body).hexdigest()[:16]
        f.files[fid] = body
        return 201, {
            "id": fid,
            "url": f"{f.url}/f/{fid}",
            "size": len(body),
            "expires_at": "2026-11-11T10:05:00Z",
        }

    f.route("POST", "/v1/files", post_file)
    f.route(
        "GET",
        "/v1/files",
        lambda m, q, b: (
            200,
            {
                "items": [
                    {"id": i, "size": len(v), "created_at": "2026-11-04T10:05:00Z", "expires_at": None}
                    for i, v in f.files.items()
                ],
                "next": None,
            },
        ),
    )

    def del_file(m, q, b):
        if m.group(1) not in f.files:
            return 404, {"error": "not_found", "message": "No such file."}
        del f.files[m.group(1)]
        return 204, None

    f.route("DELETE", r"/v1/files/(f_[a-z0-9]+)", del_file)

    def put_app(m, q, body):
        name = m.group(1)
        if f.fail_test:
            return 422, {"error": "test_failed", "message": "The app's test failed.", "output": "FAILED x"}
        f.apps[name] = {"tar": body, "query": q, "status": "running"}
        return 200, {
            "name": name,
            "url": f"{f.url}/a/{name}",
            "status": "running",
            "expires_at": None if q.get("permanent") else "2026-11-11T09:00:00Z",
            "view_token": "apv_Zx8Cv1Bn3Mq5Wl7Er9Ty2U",
        }

    f.fail_test = False
    f.route("PUT", r"/v1/apps/([a-z0-9-]+)", put_app)
    f.route(
        "GET",
        "/v1/apps",
        lambda m, q, b: (
            200,
            {
                "items": [
                    {
                        "name": n,
                        "stack": "static",
                        "store": "none",
                        "public": False,
                        "status": a["status"],
                        "url": f"{f.url}/a/{n}",
                        "expires_at": None,
                        "updated_at": "2026-11-04T09:00:00Z",
                    }
                    for n, a in f.apps.items()
                ],
                "next": None,
            },
        ),
    )

    def act(m, q, b):
        f.apps[m.group(1)]["status"] = "running" if m.group(2) == "restart" else "stopped"
        return 200, {"name": m.group(1), "status": f.apps[m.group(1)]["status"]}

    f.route("POST", r"/v1/apps/([a-z0-9-]+)/(restart|stop)", act)
    f.route("DELETE", r"/v1/apps/([a-z0-9-]+)", lambda m, q, b: (f.apps.pop(m.group(1)) and 204, None))
    return f.start()


def make_relay() -> Fake:
    f = Fake()
    f.token = "orn_" + "B" * 43
    f.inbox, f.acked, f.sent, f.blobs, f.webhooks = [], [], [], {}, {}
    f.snapshot = {
        "version": 1,
        "skills": [],
        "mcp": {},
        "credentials": {},
        "workspaces": {
            "schema": "orch.workspaces/1",
            "self": WS,
            "updated_at": "2026-11-04T13:00:00Z",
            "workspaces": [],
        },
    }
    add_profile(f, {"phones": 1})

    def post_msg(m, q, body):
        msg = json.loads(body)
        for s in f.sent:
            if s["id"] == msg["id"]:
                return (
                    (200, {"id": msg["id"], "duplicate": True})
                    if s == msg
                    else (409, {"error": "conflict", "message": "This message id was already used."})
                )
        if msg["from"] != WS:
            return 403, {"error": "forbidden", "message": "from must be you"}
        if msg["to"] == "ws_denied0001":
            return 403, {"error": "not_allowed", "message": "Pilatus may not send text to Denied."}
        f.sent.append(msg)
        return 201, {"id": msg["id"]}

    f.route("POST", "/v1/messages", post_msg)
    f.route(
        "GET",
        "/v1/inbox",
        lambda m, q, b: (200, {"items": [x for x in f.inbox if x["id"] not in f.acked], "next": None}),
    )

    def ack(m, q, body):
        f.acked += json.loads(body)["ids"]
        return 204, None

    f.route("POST", "/v1/inbox/ack", ack)

    def post_blob(m, q, body):
        bid = "b_" + hashlib.sha256(body).hexdigest()[:16]
        f.blobs[bid] = body
        return 201, {"blob_id": bid, "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}

    f.route("POST", "/v1/blobs", post_blob)
    f.route(
        "GET",
        r"/v1/blobs/(b_[a-z0-9]+)",
        lambda m, q, b: (
            (200, None, f.blobs[m.group(1)])
            if m.group(1) in f.blobs
            else (404, {"error": "not_found", "message": "no"})
        ),
    )

    def new_hook(m, q, body):
        req = json.loads(body)
        wid = f"wh_{len(f.webhooks):010d}"
        f.webhooks[wid] = {
            "id": wid,
            "mode": req["mode"],
            "ticket": req.get("ticket"),
            "created_at": "2026-11-04T10:00:00Z",
            "last_call_at": None,
        }
        return 201, {"id": wid, "url": f"{f.url}/webhook/{wid}?token=whk_" + "x" * 22}

    f.route("POST", "/v1/webhooks", new_hook)
    f.route("GET", "/v1/webhooks", lambda m, q, b: (200, {"items": list(f.webhooks.values()), "next": None}))
    f.route(
        "DELETE", r"/v1/webhooks/(wh_[a-z0-9]+)", lambda m, q, b: (f.webhooks.pop(m.group(1)) and 204, None)
    )
    f.route("GET", "/v1/refresh", lambda m, q, b: (200, f.snapshot))
    return f.start()
