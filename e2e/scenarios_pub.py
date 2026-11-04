"""Publish (P) scenarios: CLI client where it exists, plain HTTP for the negative cases."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import struct
import time
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from lib import Fail, Skip, check, http, scenario, tar_gz
import lib


def b64u_decode(t: str) -> bytes:
    import base64
    return base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))


def opf1_decrypt(blob: bytes, key: bytes) -> tuple[dict, bytes]:
    """Independent reader of crypto.md section 1."""
    check(blob[:4] == b"OPF1" and len(blob) >= 32, "bad magic or too short")
    plain = AESGCM(key).decrypt(blob[4:16], blob[16:], b"OPF1")  # raises InvalidTag on a wrong key
    n = struct.unpack(">I", plain[:4])[0]
    hdr = json.loads(plain[4:4 + n])
    body = plain[4 + n:]
    check(hdr["size"] == len(body), "header size does not match")
    return hdr, body


def link_parts(link: str) -> tuple[str, str, bytes]:
    base, _, frag = link.partition("#k=")
    return base.rsplit("/f/", 1)[0], base.rsplit("/f/", 1)[1], b64u_decode(frag)


def share(e, ws: str, name="report.pdf", size=300_000, extra=()):
    f = e.ws(ws) / name
    data = os.urandom(size)
    f.write_bytes(data)
    r = e.orchj(ws, "publish", "file", str(f), *extra)
    return r, data


def app_files(stack: str, name: str, version="v1", test=None, public=False) -> dict:
    head = f'name = "{name}"\nabout = "e2e app"\nstack = "{stack}"\npublic = {"true" if public else "false"}\n'
    if stack == "static":
        return {"app.toml": head, "index.html": f"<h1>{name} {version}</h1>"}
    if stack == "python":
        head += 'start = "python3 main.py"\nhealth = "/health"\nstore = "sqlite"\n'
        if test:
            head += f'test = "{test}"\n'
        main = '''import os, sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
db = sqlite3.connect(os.environ["DATA_DIR"] + "/app.db", check_same_thread=False)
db.execute("create table if not exists hits(n integer)")
class H(BaseHTTPRequestHandler):
    def do_GET(s):
        if s.path.endswith("/health"):
            body = b"ok"
        else:
            db.execute("insert into hits values (1)"); db.commit()
            n = db.execute("select count(*) from hits").fetchone()[0]
            body = ("hits=%d ver=VERSION" % n).encode()
        s.send_response(200); s.end_headers(); s.wfile.write(body)
    def log_message(s, *a): pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
'''.replace("VERSION", version)
        return {"app.toml": head, "main.py": main}
    head += 'start = "node server.js"\nhealth = "/health"\nstore = "json"\n'
    js = '''const http = require("http"), fs = require("fs");
const f = process.env.DATA_DIR + "/data.json";
http.createServer((req, res) => {
  if (req.url.endsWith("/health")) return res.end("ok");
  let d = {n: 0}; try { d = JSON.parse(fs.readFileSync(f)); } catch (e) {}
  d.n++; fs.writeFileSync(f, JSON.stringify(d));
  res.end("n=" + d.n + " ver=VERSION");
}).listen(parseInt(process.env.PORT), "127.0.0.1");
'''.replace("VERSION", version)
    return {"app.toml": head, "server.js": js}


def write_app(e, ws: str, name: str, stack: str, **kw) -> Path:
    d = e.tmp / "apps" / f"{ws}-{name}"
    d.mkdir(parents=True, exist_ok=True)
    for fn, content in app_files(stack, name, **kw).items():
        (d / fn).write_text(content)
    return d


def app_get(e, name: str, token: str | None, path="/", retries=20) -> lib.Resp:
    """GET /a/<name><path> with the view token (cookie flow). Retries while the app starts."""
    base = f"{e.pub.url}/a/{name}"
    h = {}
    if token:
        r = http("GET", f"{base}/?token={token}")
        if r.status == 302 and r.headers.get("set-cookie"):
            h["Cookie"] = r.headers["set-cookie"].split(";")[0]
    for _ in range(retries):
        r = http("GET", base + path, h)
        if r.status not in (502, 503):
            return r
        time.sleep(0.5)
    return r


def name_for(e, base: str) -> str:
    return f"{base}-{e.run_id}"[:40].lower().replace("_", "-")


@scenario("P1")
def p1(e):
    """Admin adds Pilatus (description, tags, rights); connect writes secrets, skill, AGENTS block."""
    pid, tok = e.connect_publish("Pilatus", desc="Product work", tags=["engineering"])
    prompt = e.prompts[("pub", "Pilatus")]
    check("orch publish connect" in prompt and pid in prompt, f"prompt lacks the connect line: {prompt[:100]}")
    ws = e.ws("Pilatus")
    sec = json.loads((ws / ".orch/secrets/publish.json").read_text())
    check(sec["workspace"] == pid and sec["token"] == tok, "secrets/publish.json wrong")
    check((ws / ".agents/skills/orch-publish/SKILL.md").is_file(), "orch-publish skill missing")
    check("orch:begin orch-publish" in (ws / "AGENTS.md").read_text(), "AGENTS.md block missing")
    rc, out, _ = e.sh(["git", "check-ignore", ".orch/secrets/publish.json"], cwd=ws)
    check(rc == 0, "secrets are not gitignored")
    who = e.orchj("Pilatus", "publish", "whoami")
    check(who["description"] == "Product work" and who["tags"] == ["engineering"], f"whoami {who}")
    check(who["rights"]["files"] and who["rights"]["apps"] and not who["rights"]["permanent"] and not who["rights"]["public"], "rights")
    lst = e.pub.admin.call("GET", "/admin/api/workspaces").json()
    items = lst["items"] if isinstance(lst, dict) else lst
    check(any(w["id"] == pid for w in items), "admin list lacks the workspace")
    ob = http("GET", e.pub.url + "/onboarding.sh")
    check(ob.status == 200 and "orch" in ob.text, "onboarding.sh not served")
    return "prompt shown once; connect via CLI"


@scenario("P2")
def p2(e):
    """orch publish file -> blob is ciphertext, key only in the link, decrypt gives identical bytes."""
    e.connect_publish("Pilatus")
    r, data = share(e, "Pilatus")
    base, fid, key = link_parts(r["link"])
    blob = http("GET", f"{e.pub.url}/f/{fid}/blob")
    check(blob.status == 200 and blob.body[:4] == b"OPF1", f"blob fetch {blob.status}")
    hdr, body = opf1_decrypt(blob.body, key)
    check(body == data and hdr["name"] == "report.pdf", "decrypted bytes differ")
    check(data[:64] not in blob.body, "plaintext found in the stored blob")
    if e.mode == "local":
        disk = (e.pub.data / "files" / fid).read_bytes()
        check(disk == blob.body and data[:64] not in disk, "server file is not the ciphertext")
    page = http("GET", f"{e.pub.url}/f/{fid}")
    check(page.status == 200 and "frame-ancestors 'none'" in page.headers.get("content-security-policy", ""), "file page headers")
    check(page.headers.get("x-frame-options") == "DENY" and page.headers.get("referrer-policy") == "no-referrer", "file page headers")
    check("#k=" not in page.text and r["link"].split("#k=")[1] not in page.text, "key leaked into the page")
    return "browser decrypt part not run"


@scenario("P3")
def p3(e):
    """Wrong key fails to decrypt; expired file -> 410 (clock moved by editing the DB, local only)."""
    e.connect_publish("Pilatus")
    r, data = share(e, "Pilatus", name="p3.bin", size=2000, extra=("--days", "1"))
    base, fid, key = link_parts(r["link"])
    check(r["expires_at"] and r["expires_at"] > time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 80000)), f"days=1 expiry {r['expires_at']}")
    blob = http("GET", f"{e.pub.url}/f/{fid}/blob").body
    try:
        opf1_decrypt(blob, os.urandom(32))
        raise Fail("wrong key decrypted")
    except Fail:
        raise
    except Exception:
        pass
    if e.mode != "local":
        return "wrong key ok; expiry (clock move) is local-only"
    db = sqlite3.connect(e.pub.data / "publish.db")
    db.execute("UPDATE files SET expires_at='2020-01-01T00:00:00Z' WHERE id=?", (fid,))
    db.commit()
    db.close()
    for p in (f"/f/{fid}", f"/f/{fid}/blob"):
        check(http("GET", e.pub.url + p).status == 410, f"{p} should be 410")
    return "missing-key page is browser side (not run)"


@scenario("P4")
def p4(e):
    """Permanent without the right -> 403; file over the cap -> refused; temp app removal is the hourly sweep."""
    e.connect_publish("Home", rights={"files": True, "apps": True, "permanent": False, "public": False})
    blob, _ = _blob(b"x" * 100)
    r = e.papi("Home", "POST", "/v1/files?permanent=1", blob)
    check(r.status == 403, f"permanent file: {r}")
    app = tar_gz({k: v for k, v in app_files("static", name_for(e, "p4app")).items()})
    r = e.papi("Home", "PUT", f"/v1/apps/{name_for(e, 'p4app')}?permanent=1", app)
    check(r.status == 403, f"permanent app: {r}")
    if e.mode == "local":
        big, _ = _blob(os.urandom(3 * 1024 * 1024))  # local server cap is 2 MB
        try:
            r = e.papi("Home", "POST", "/v1/files?days=1", big)
            check(r.status == 413, f"over the cap: {r}")
        except OSError:
            pass  # server closed the connection while the oversized body was sent: refused too
    return "100 MB cap tested with a 2 MB cap (local); sweep of expired temp apps is hourly: covered by cargo test, not run here"


def _blob(content: bytes, name="a.bin"):
    import json as _j
    key, iv = os.urandom(32), os.urandom(12)
    hdr = _j.dumps({"name": name, "type": "application/octet-stream", "size": len(content)}).encode()
    plain = struct.pack(">I", len(hdr)) + hdr + content
    return b"OPF1" + iv + AESGCM(key).encrypt(iv, plain, b"OPF1"), key


@scenario("P5")
def p5(e):
    """Static, python (sqlite) and node (json) apps healthy under /a/<name>; DATA_DIR survives a redeploy."""
    e.connect_publish("Pilatus")
    out = []
    for stack in ("static", "python", "node"):
        n = name_for(e, f"p5-{stack}")
        d = write_app(e, "Pilatus", n, stack)
        r = e.orchj("Pilatus", "publish", "app", str(d))
        check(r["status"] == "running" and r.get("view_token"), f"{stack} deploy: {r}")
        g = app_get(e, n, r["view_token"])
        check(g.status == 200, f"{stack} GET {g.status} {g.text[:100]}")
        if stack == "static":
            check(f"{n} v1" in g.text, "static page content")
            continue
        g = app_get(e, n, r["view_token"])
        first = g.text
        # redeploy v2: counter must continue
        d2 = write_app(e, "Pilatus", n, stack, version="v2")
        r2 = e.orchj("Pilatus", "publish", "app", str(d2))
        g2 = app_get(e, n, r["view_token"])
        key = "hits=" if stack == "python" else "n="
        check(key in first and key in g2.text, f"{stack} redeploy status={r2.get('status')} app answer: {g2.status} {first[:80]!r} -> {g2.text[:120]!r}")
        n1 = int(first.split(key)[1].split()[0])
        n2 = int(g2.text.split(key)[1].split()[0])
        check("ver=v2" in g2.text and n2 > n1, f"{stack} data lost on redeploy: {first!r} -> {g2.text!r}")
        out.append(stack)
    # the shipped python + sqlite template: deploys (its own test runs on the server) and redeploys
    tok = None
    n = name_for(e, "p5-tpl")
    d = e.tmp / "apps" / f"Pilatus-{n}"
    e.orch("Pilatus", "publish", "new", "python", "--store", "sqlite", str(d))
    m = d / "app.toml"
    m.write_text(m.read_text().replace(next(l for l in m.read_text().splitlines() if l.startswith("name =")), f'name = "{n}"'))
    for round_ in (1, 2):
        r = e.orchj("Pilatus", "publish", "app", str(d))
        check(r["status"] == "running", f"template deploy {round_}: {r}")
        tok = r.get("view_token") or tok
        g = app_get(e, n, tok)
        check(g.status == 200, f"template GET after deploy {round_}: {g.status} {g.text[:100]}")
    return "python app uses stdlib http.server (no FastAPI install); python+sqlite template deploy + redeploy"


@scenario("P6")
def p6(e):
    """App with a failing test -> 422 test_failed; the old version keeps running."""
    e.connect_publish("Pilatus")
    n = name_for(e, "p6-app")
    d = write_app(e, "Pilatus", n, "python")
    r = e.orchj("Pilatus", "publish", "app", str(d))
    tok = r["view_token"]
    check("ver=v1" in app_get(e, n, tok).text, "v1 not running")
    bad = write_app(e, "Pilatus", n, "python", version="v2", test="python3 -c 'import sys; print(\\\"boom\\\"); sys.exit(1)'")
    rc, out, err = e.orch("Pilatus", "publish", "app", str(bad), ok=False)
    check(rc != 0, "failing test was deployed")
    raw = e.papi("Pilatus", "PUT", f"/v1/apps/{n}", tar_gz({fn: c for fn, c in app_files("python", n, "v2", test="python3 -c 'import sys; sys.exit(1)'").items()}))
    j = raw.json() or {}
    check(raw.status == 422 and j.get("error") == "test_failed" and "output" in j, f"expected 422 test_failed: {raw}")
    check("ver=v1" in app_get(e, n, tok).text, "old version is not running any more")


@scenario("P7")
def p7(e):
    """Private app needs ?token=; public=true refused without the public right, allowed with it."""
    wid, _ = e.connect_publish("Pilatus")
    n = name_for(e, "p7-static")
    d = write_app(e, "Pilatus", n, "static")
    r = e.orchj("Pilatus", "publish", "app", str(d))
    check(http("GET", f"{e.pub.url}/a/{n}/").status == 401, "private app answered without a token")
    check("This app is private" in http("GET", f"{e.pub.url}/a/{n}/").text, "private page text")
    check(http("GET", f"{e.pub.url}/a/{n}/?token=apv_wrong").status == 401, "wrong token accepted")
    check(app_get(e, n, r["view_token"]).status == 200, "token flow failed")
    pn = name_for(e, "p7-public")
    pd = write_app(e, "Pilatus", pn, "static", public=True)
    rc, out, err = e.orch("Pilatus", "publish", "app", str(pd), ok=False)
    check(rc != 0, f"public app was allowed without the right: {out}")
    rr = e.pub.admin.call("PATCH", f"/admin/api/workspaces/{wid}", {"rights": {"files": True, "apps": True, "permanent": False, "public": True}})
    check(rr.status == 200, f"grant public: {rr}")
    try:
        r2 = e.orchj("Pilatus", "publish", "app", str(pd))
        check(http("GET", f"{e.pub.url}/a/{pn}/").status == 200, "public app not open")
    finally:
        e.pub.admin.call("PATCH", f"/admin/api/workspaces/{wid}", {"rights": {"files": True, "apps": True, "permanent": False, "public": False}})


@scenario("P8")
def p8(e):
    """List, restart, stop, delete own apps and files; Home cannot touch Pilatus's items."""
    e.connect_publish("Pilatus")
    e.connect_publish("Home")
    n = name_for(e, "p8-app")
    e.orchj("Pilatus", "publish", "app", str(write_app(e, "Pilatus", n, "python")))
    r, _ = share(e, "Pilatus", name="p8.bin", size=500)
    fid = r["id"]
    lst = e.orchj("Pilatus", "publish", "list")
    check(any(a["name"] == n for a in lst["apps"]) and any(f["id"] == fid for f in lst["files"]), f"list: {lst}")
    for method, path in (("DELETE", f"/v1/files/{fid}"), ("DELETE", f"/v1/apps/{n}"), ("POST", f"/v1/apps/{n}/restart"), ("POST", f"/v1/apps/{n}/stop")):
        s = e.papi("Home", method, path).status
        check(s in (403, 404), f"Home {method} {path} -> {s}")
    check(not any(a["name"] == n for a in (e.papi("Home", "GET", "/v1/apps").json() or {"items": []})["items"]), "Home sees Pilatus's app")
    check(e.orchj("Pilatus", "publish", "restart", n)["status"] == "running", "restart")
    check(e.orchj("Pilatus", "publish", "stop", n)["status"] == "stopped", "stop")
    e.orch("Pilatus", "publish", "delete", n)
    e.orch("Pilatus", "publish", "delete", fid)
    lst = e.orchj("Pilatus", "publish", "list")
    check(not any(a["name"] == n for a in lst["apps"]) and not any(f["id"] == fid for f in lst["files"]), f"not deleted: {lst}")


@scenario("P9")
def p9(e):
    """Admin API facts: public /admin is 404, admin port needs the token (portal pages need a browser)."""
    check(http("GET", e.pub.url + "/admin").status == 404, "public /admin should be 404")
    check(http("GET", e.pub.url + "/admin/api/workspaces").status == 404, "public admin api should be 404")
    if e.mode == "local":
        check(http("GET", e.pub.admin_url + "/admin/api/workspaces").status == 401, "admin port without token should be 401")
        check(http("GET", e.pub.admin_url + "/admin/api/workspaces", {"X-Orch-Admin": "wrong"}).status == 401, "wrong admin token")
    else:
        try:
            r = http("GET", "http://179.237.125.155:8411/admin/api/workspaces", timeout=5)
            raise Fail(f"admin port reachable from the public IP: {r.status}")
        except OSError:
            pass
    return "portal pages (names hidden, status, restart/stop buttons) need the browser lane"
