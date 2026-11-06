#!/usr/bin/env python3
"""Local harness for the relay admin network map (visual checks only, not part of `cargo test`).

Starts one real relay per scenario (seeded through the admin and public APIs, plus a few direct
`last_seen` / phone pairing updates in its SQLite file) and serves them behind one small proxy:

    python3 relay/tests/map-harness/harness.py --port 8790 --bin <orch-relay> [--web relay/web]

Open http://127.0.0.1:<port>/ for the index. A scenario link sets a cookie, so `/admin` and
`/admin/api/*` go to that scenario's relay. With `--web`, portal.html, style.css and kit.js are read
from disk on every request, so web edits show without a rebuild.

Everything lives in one temp folder (`--dir`, made with mktemp by the caller); delete it by its exact path.
"""

import argparse
import http.client
import http.server
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ADMIN_TOKEN = "harness-admin-" + "x" * 24  # throwaway, local only

PHONE = "Severin's iPhone"


def ws_names(n):
    base = [
        "Pilatus Workspace", "Reports", "Website", "Finance", "Design Studio", "Customer Support",
        "Research Lab", "Marketing", "Operations", "Mobile App", "Data Pipeline", "Legal",
        "Hiring", "Sales Desk", "Infrastructure", "Docs", "Partners", "Billing", "QA Team",
        "Analytics", "Security Review", "Events", "Content Team", "Product Planning", "Archive",
    ]
    return base[:n]


def r(a, b, mf=True, tasks=False, start=False):
    return (a, b, mf, tasks, start)


# Scenario: workspaces, rules (index pairs), phones (name, [workspace idx], paired), offline idx -> hours ago,
# never-connected idx, unread per idx, pending-review idx.
SCENARIOS = {
    "empty": dict(title="Empty: no workspaces yet", n=0, rules=[], phones=[]),
    "s1": dict(title="S1: 1 workspace + 1 phone", n=1, rules=[], phones=[(PHONE, [0], True)]),
    "s2": dict(
        title="S2: 3 workspaces + 1 phone (like the owner's)", n=3,
        rules=[r(0, 1, tasks=True), r(1, 0), r(2, 0)],
        phones=[(PHONE, [0, 1, 2], True)], offline={1: 9}, unread={0: 2},
        groups=[("Work", [0, 1], True), ("Private", [2], False)],
    ),
    "s3": dict(
        title="S3: 6 workspaces + 2 phones, mixed rules both ways", n=6,
        rules=[r(0, 1, tasks=True), r(1, 0), r(0, 2, tasks=True, start=True), r(2, 0, tasks=True, start=True),
               r(3, 0), r(4, 1, mf=False, tasks=True), r(5, 4), r(4, 5, tasks=True), r(2, 3)],
        phones=[(PHONE, [0, 1, 2, 3], True), ("Office iPad", [4, 5], False)],
        offline={1: 9, 5: 50}, never=[3], unread={0: 3, 4: 12}, pending=[2],
        groups=[("Work", [0, 1, 2], True), ("Marketing team", [3, 4], False)],
    ),
    "s4": dict(
        title="S4: 12 workspaces + 1 phone", n=12,
        rules=[r(0, i, tasks=i % 2 == 0) for i in range(1, 8)] + [r(i, 0) for i in (1, 3, 5)]
        + [r(8, 9), r(9, 8, tasks=True), r(10, 11), r(2, 8)],
        phones=[(PHONE, list(range(0, 12, 2)), True)], offline={3: 9, 7: 30}, unread={0: 1, 9: 4},
        groups=[("Work", [0, 1, 2, 3, 4], True), ("Private", [5, 6, 7], False), ("Marketing team", [8, 9], True)],
    ),
    "s5": dict(
        title="S5: 25 workspaces + 3 phones", n=25,
        rules=[r(0, i, tasks=i % 3 == 0) for i in range(1, 12)] + [r(i, 0) for i in range(1, 6)]
        + [r(12, i) for i in range(13, 20)] + [r(20, 21, tasks=True, start=True), r(21, 20), r(22, 23), r(23, 24),
                                               r(5, 12), r(18, 3, tasks=True)],
        phones=[(PHONE, list(range(25)), True), ("Office iPad", [0, 12, 20], True), ("Spare phone", [5], False)],
        offline={2: 9, 7: 26, 14: 3, 19: 72}, never=[24], unread={0: 5, 12: 1, 20: 9}, pending=[6],
        groups=[("Work", list(range(0, 10)), True), ("Marketing team", list(range(10, 18)), False),
                ("Private", [18, 19, 20, 21], True)],
    ),
}


def free_port():
    while True:
        p = 18000 + secrets.randbelow(1000)
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p


def call(base, method, path, body=None, token=None, ws=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    if token:
        req.add_header("Authorization", "Bearer " + token)
        req.add_header("X-Orch-Workspace", ws)
    else:
        req.add_header("X-Orch-Admin", ADMIN_TOKEN)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as res:
        raw = res.read()
        return json.loads(raw) if raw else None


class Relay:
    def __init__(self, key, spec, binary, root):
        self.key, self.spec = key, spec
        self.dir = root / key
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "master.key").write_bytes(secrets.token_bytes(32))
        self.pub, self.adm = free_port(), free_port()
        env = {
            "PATH": "/usr/bin:/bin",
            "ORCH_RELAY_ADMIN_TOKEN": ADMIN_TOKEN,
            "ORCH_RELAY_LISTEN": f"127.0.0.1:{self.pub}",
            "ORCH_RELAY_ADMIN_LISTEN": f"127.0.0.1:{self.adm}",
            "ORCH_RELAY_DATA_DIR": str(self.dir / "data"),
            "ORCH_RELAY_MASTER_KEY_FILE": str(self.dir / "master.key"),
            "ORCH_RELAY_PUBLIC_ORIGIN": f"http://127.0.0.1:{self.pub}",
            "RUST_LOG": "warn",
        }
        (self.dir / "data").mkdir(exist_ok=True)
        log = open(self.dir / "relay.log", "w")
        self.proc = subprocess.Popen([binary], env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL)
        (root / "pids").open("a").write(f"{self.proc.pid}\n")
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.adm}/health").read()
                break
            except OSError:
                time.sleep(0.1)
        self.online = []
        self.seed()

    @property
    def admin(self):
        return f"http://127.0.0.1:{self.adm}"

    def db(self):
        return sqlite3.connect(self.dir / "data" / next(p.name for p in (self.dir / "data").glob("*.db")))

    def seed(self):
        s = self.spec
        ws = [call(self.admin, "POST", "/admin/api/workspaces", {"name": n, "description": "", "tags": []})
              for n in ws_names(s["n"])]
        rules = [{"from": ws[a]["id"], "to": ws[b]["id"], "text": mf, "files": mf, "delegate": t, "start": st}
                 for a, b, mf, t, st in s["rules"]]
        if rules:
            call(self.admin, "PUT", "/admin/api/rules", {"rules": rules})
        # A few shared tools first, so group members get them (Shared tools page, "Gets: ..." in Add workspace).
        if s.get("groups"):
            for n in ("BANK_EXPORT_LOGIN", "OPENAI_API_KEY"):
                call(self.admin, "PUT", f"/admin/api/shared/credentials/{n}", {"value": "harness-only"})
            call(self.admin, "PUT", "/admin/api/shared/mcp/project-files", {"config": {"command": "project-files"}})
        # Groups: (name, [workspace idx], members may message each other); the rest stay in no group.
        for gname, idx, talk in s.get("groups", []):
            g = call(self.admin, "POST", "/admin/api/groups", {"name": gname, "talk": talk})
            for i in idx:
                call(self.admin, "PATCH", f"/admin/api/workspaces/{ws[i]['id']}", {"group": g["id"]})
        # Unread messages: send along an allowed rule when one exists, else leave the count out.
        for idx, count in s.get("unread", {}).items():
            src = next((a for a, b, mf, *_ in s["rules"] if b == idx and mf), None)
            if src is None:
                continue
            for i in range(count):
                m = {"schema": "orch.msg/1", "id": "m_" + secrets.token_hex(8), "from": ws[src]["id"], "to": ws[idx]["id"],
                     "type": "text", "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "body": {"text": f"Update {i + 1}: the weekly numbers are ready."}}
                call(f"http://127.0.0.1:{self.pub}", "POST", "/v1/messages", m, token=ws[src]["token"], ws=ws[src]["id"])
        phones = [(call(self.admin, "POST", "/admin/api/phones",
                        {"name": n, "workspaces": [ws[i]["id"] for i in idx]})["phone_id"], paired)
                  for n, idx, paired in s["phones"]]
        now = int(time.time())
        offline, never, pending = s.get("offline", {}), s.get("never", []), s.get("pending", [])
        c = self.db()
        for i, w in enumerate(ws):
            if i in never:
                c.execute("UPDATE workspaces SET last_seen=NULL WHERE id=?", (w["id"],))
            elif i in offline:
                c.execute("UPDATE workspaces SET last_seen=? WHERE id=?", (now - offline[i] * 3600, w["id"]))
            else:
                self.online.append(("workspaces", w["id"]))
            if i in pending:
                c.execute("UPDATE workspaces SET pending_description=?, pending_tags=?, pending_at=?, pending_rev=? WHERE id=?",
                          ("Builds the weekly report.", '["reports"]', now, "r1", w["id"]))
        for pid, paired in phones:
            if paired:
                c.execute("UPDATE phones SET token_hash='harness' WHERE id=?", (pid,))
                self.online.append(("phones", pid))
        c.commit()
        c.close()
        self.touch()

    def touch(self):
        # Keep "online" nodes online: the relay counts a node online for two minutes after its last call.
        c = self.db()
        for table, id_ in self.online:
            c.execute(f"UPDATE {table} SET last_seen=? WHERE id=?", (int(time.time()), id_))
        c.commit()
        c.close()


def index_html(relays):
    rows = "".join(f'<li><a href="/s/{k}">{r.spec["title"]}</a> · <a href="/s/{k}?narrow=1">390 px list</a></li>'
                   for k, r in relays.items())
    return f"""<!doctype html><meta charset=utf-8><title>Relay map harness</title>
<link rel=stylesheet href="/admin/style.css"><body><main class="page"><h1>Relay network map: scenarios</h1>
<p class="muted">Each link opens the real relay admin for that scenario (seeded data, local only).
Make the window narrower than 600 px to see the list view.</p><ul class="stack">{rows}</ul></main></body>"""


def go_html(key):
    return f"""<!doctype html><meta charset=utf-8><title>Opening {key}</title>
<script src="/harness/go.js" data-token="{ADMIN_TOKEN}"></script>"""


GO_JS = """const s=document.currentScript;try{sessionStorage.setItem('orch_admin',s.dataset.token)}catch{}location.replace('/admin#overview')"""


def serve(port, relays, web):
    web_files = {"/admin": ("portal.html", "text/html; charset=utf-8"),
                 "/admin/style.css": ("style.css", "text/css; charset=utf-8"),
                 "/admin/kit.js": ("kit.js", "text/javascript; charset=utf-8")}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="text/html; charset=utf-8", extra=()):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def scenario(self):
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == "scenario" and v in relays:
                    return relays[v]
            return relays["s2"]

        def handle_any(self):
            path = self.path.split("?")[0]
            if path == "/":
                return self.send(200, index_html(relays).encode())
            if path.startswith("/s/") and path[3:] in relays:
                return self.send(200, go_html(path[3:]).encode(), extra=[("Set-Cookie", f"scenario={path[3:]}; Path=/")])
            if path == "/harness/go.js":
                return self.send(200, GO_JS.encode(), "text/javascript; charset=utf-8")
            if web and path in web_files and self.command == "GET":
                name, ctype = web_files[path]
                return self.send(200, (web / name).read_bytes(), ctype)
            rel = self.scenario()
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            conn = http.client.HTTPConnection("127.0.0.1", rel.adm, timeout=30)
            headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "cookie")}
            conn.request(self.command, self.path, body=body, headers=headers)
            res = conn.getresponse()
            data = res.read()
            self.send(res.status, data, res.getheader("Content-Type") or "application/octet-stream")

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = handle_any

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.serve_forever()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--bin", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--web")
    a = ap.parse_args()
    root = Path(a.dir)
    relays = {k: Relay(k, spec, a.bin, root) for k, spec in SCENARIOS.items()}

    def keep_online():
        while True:
            time.sleep(30)
            for rel in relays.values():
                rel.touch()

    threading.Thread(target=keep_online, daemon=True).start()
    print(f"harness on http://127.0.0.1:{a.port}/ ({len(relays)} relays)", flush=True)
    try:
        serve(a.port, relays, Path(a.web) if a.web else None)
    finally:
        for rel in relays.values():
            rel.proc.terminate()


if __name__ == "__main__":
    os.umask(0o077)
    main()
