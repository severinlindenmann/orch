#!/usr/bin/env python3
"""Update-safe data check for the workspace look (PR #249): old relay + publish write data, the new build opens the SAME
data dir. Usage: e2e/upgrade_look.py [OLD_REF=dc0d401] [NEW_REF=origin/develop]. Builds both refs in throw-away worktrees
under ~/orch-dev/.tf-upg-* with their own CARGO_TARGET_DIRs (through heavy.sh when present). Never touches real data."""
import base64, json, os, random, shutil, sqlite3, subprocess, sys, tempfile, time, urllib.request, urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OLD = sys.argv[1] if len(sys.argv) > 1 else "dc0d401"
NEW = sys.argv[2] if len(sys.argv) > 2 else "origin/develop"
HOME = Path.home()
HEAVY = HOME / "orch-dev/state/v2-plan-2026-11-05/build/heavy.sh"
CARGO = HOME / ".rustup/toolchains/stable-aarch64-apple-darwin/bin"
tmp = Path(tempfile.mkdtemp(prefix=".tf-upg-", dir=HOME / "orch-dev"))
# orch trusts ORCH_HOME only outside any repo (~/orch-dev is one); otherwise it falls back to ~/.orch-tool.
(HOME / ".orch-test").mkdir(exist_ok=True)
ohome = Path(tempfile.mkdtemp(prefix="upg-", dir=HOME / ".orch-test"))
pids: list[subprocess.Popen] = []
ok_all = True


def say(m):
    print(m, flush=True)


def check(c, m):
    global ok_all
    say(("PASS " if c else "FAIL ") + m)
    ok_all &= bool(c)


def build(ref, name):
    wt = tmp / f"src-{name}"
    subprocess.run(["git", "-C", str(REPO), "worktree", "add", "-q", "--detach", str(wt), ref], check=True)
    tgt = tmp / f"target-{name}"
    env = {**os.environ, "PATH": f"{CARGO}:{os.environ['PATH']}", "CARGO_TARGET_DIR": str(tgt)}
    for crate in ("relay", "publish"):
        cmd = ["cargo", "build", "--release", "-j", "4", "-q"]
        if HEAVY.exists():
            cmd = [str(HEAVY), "l34-upg", "--"] + cmd
        subprocess.run(cmd, cwd=wt / crate, env=env, check=True)
    return {"relay": str(tgt / "release/orch-relay"), "publish": str(tgt / "release/orch-publish")}, wt


def ports(n):
    out = []
    while len(out) < n:
        p = random.randint(19000, 19900)
        if p not in out:
            out.append(p)
    return out


def start(bins, data, ps):
    rp, ra, pp, pa = ps
    base = {"PATH": "/usr/bin:/bin", "HOME": str(ohome), "ORCH_HOME": str(ohome / ".orch-tool"),
            "ORCH_HOME_STRICT": "1", "LANG": "C.UTF-8"}
    renv = {**base, "ORCH_RELAY_DATA_DIR": str(data / "relay"), "ORCH_RELAY_MASTER_KEY_FILE": str(data / "master.key"),
            "ORCH_RELAY_LISTEN": f"127.0.0.1:{rp}", "ORCH_RELAY_ADMIN_LISTEN": f"127.0.0.1:{ra}",
            "ORCH_RELAY_ADMIN_TOKEN": "r" * 24, "ORCH_RELAY_PUBLIC_ORIGIN": f"http://127.0.0.1:{rp}"}
    penv = {**base, "ORCH_PUBLISH_DATA_DIR": str(data / "publish"), "ORCH_PUBLISH_LISTEN": f"127.0.0.1:{pp}",
            "ORCH_PUBLISH_ADMIN_LISTEN": f"127.0.0.1:{pa}", "ORCH_PUBLISH_ADMIN_TOKEN": "p" * 24,
            "ORCH_PUBLISH_PUBLIC_ORIGIN": f"http://127.0.0.1:{pp}", "ORCH_PUBLISH_APP_PORTS": "19950-19959"}
    procs = []
    for b, env, name in ((bins["relay"], renv, "relay"), (bins["publish"], penv, "publish")):
        p = subprocess.Popen([b], env=env, stdout=open(tmp / f"{name}.log", "a"), stderr=subprocess.STDOUT, cwd=tmp)
        pids.append(p)
        procs.append(p)
    for port in (rp, pp):
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise SystemExit(f"server on {port} did not start, see {tmp}/*.log")
    return procs


def stop(procs):
    for p in procs:  # only the processes this script started
        p.terminate()
    for p in procs:
        p.wait(timeout=20)


def call(method, url, headers=None, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = dict(headers or {})
    if body is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=20)
        t = r.read()
        return r.status, (json.loads(t) if t[:1] in (b"{", b"[") else t)
    except urllib.error.HTTPError as e:
        t = e.read()
        return e.code, (json.loads(t) if t[:1] in (b"{", b"[") else t)


def schema(db):
    c = sqlite3.connect(db)
    tabs = {r[0]: r[1] for r in c.execute("select name, rootpage from sqlite_master where type='table'")}
    cols = {t: {r[1]: (r[2], r[4], r[3]) for r in c.execute(f"pragma table_info('{t}')")} for t in tabs}
    rows = {t: c.execute(f"select * from {t} order by rowid").fetchall() for t in tabs}
    c.close()
    return tabs, cols, rows


try:
    old_bins, _ = build(OLD, "old")
    new_bins, _ = build(NEW, "new")
    data = tmp / "data"
    (data / "relay").mkdir(parents=True)
    (data / "publish").mkdir()
    (data / "master.key").write_bytes(os.urandom(32))
    ps = ports(4)
    rp, ra, pp, pa = ps
    RA, PA = {"X-Orch-Admin": "r" * 24}, {"X-Orch-Admin": "p" * 24}
    say(f"== old build {OLD}, data dir {data}")
    procs = start(old_bins, data, ps)
    # relay: two workspaces, a rule, a message, a phone
    ws = []
    for n in ("Old A", "Old B"):
        s, j = call("POST", f"http://127.0.0.1:{ra}/admin/api/workspaces", RA, {"name": n, "description": "d", "tags": ["x"]})
        assert s == 201, j
        ws.append(j)
    s, j = call("PUT", f"http://127.0.0.1:{ra}/admin/api/rules", RA, {"rules": [{"from": ws[0]["id"], "to": ws[1]["id"], "text": True, "files": False, "delegate": False, "start": False}]})
    assert s == 200, j
    wh = lambda w: {"X-Orch-Workspace": w["id"], "Authorization": f"Bearer {w['token']}"}
    s, j = call("POST", f"http://127.0.0.1:{rp}/v1/messages", wh(ws[0]), {"schema": "orch.msg/1", "id": "m_0123456789abcdef", "from": ws[0]["id"], "to": ws[1]["id"], "type": "text", "created_at": "2026-11-04T10:00:00Z", "ticket": "t_7k3f9q", "body": {"text": "hello before the upgrade"}})
    assert s in (200, 201), (s, j)
    s, j = call("POST", f"http://127.0.0.1:{ra}/admin/api/phones", RA, {"name": "Old phone", "workspaces": [ws[0]["id"]]})
    assert s == 201, j
    code = j["link"].split("code=")[1]
    s, pj = call("POST", f"http://127.0.0.1:{rp}/v1/phone/pair", None, {"code": code, "name": "Old phone"})
    assert s == 201, pj
    ph = {"X-Orch-Phone": pj["phone_id"], "Authorization": f"Bearer {pj['token']}"}
    # publish: a workspace and a file
    s, pw = call("POST", f"http://127.0.0.1:{pa}/admin/api/workspaces", PA, {"name": "Old Pub", "description": "d", "tags": [], "rights": {"files": True, "apps": True, "permanent": False, "public": False}})
    assert s == 201, pw
    blob = bytes.fromhex(json.load(open(REPO / "contracts/vectors/publish-blob-v1.json"))["good"]["blob_hex"])
    pwh = {"X-Orch-Workspace": pw["id"], "Authorization": f"Bearer {pw['token']}"}
    s, fj = call("POST", f"http://127.0.0.1:{pp}/v1/files?days=7", pwh, raw=blob)
    assert s == 201, fj
    fid = fj["id"]
    s, who_old = call("GET", f"http://127.0.0.1:{rp}/v1/whoami", wh(ws[0]))
    check("icon" not in who_old, "old relay whoami has no look fields (really the old build)")
    stop(procs)
    before = {n: schema(data / n / db) for n, db in (("relay", "relay.db"), ("publish", "publish.db"))} if (data / "relay" / "relay.db").exists() else None
    dbs = {"relay": next((data / "relay").glob("*.db")), "publish": next((data / "publish").glob("*.db"))}
    before = {n: schema(p) for n, p in dbs.items()}

    say(f"== new build {NEW}, SAME data dir")
    procs = start(new_bins, data, ps)
    # the new build opened the data; check what it did to it
    stop(procs)
    after = {n: schema(p) for n, p in dbs.items()}
    new_cols = {"relay": {"workspaces": {"icon", "color", "look_by"}},
                "publish": {"workspaces": {"icon", "color", "look_by", "show_on_shared_pages"}}}
    for n in ("relay", "publish"):
        bt, bc, br = before[n]
        at, ac, ar = after[n]
        check(set(bt) <= set(at), f"{n}: no table dropped ({len(bt)} tables before, {len(at)} after)")
        check(all(bt[t] == at[t] for t in bt), f"{n}: every old table keeps its root page (none recreated)")
        added = {t: set(ac[t]) - set(bc[t]) for t in bc if set(ac[t]) - set(bc[t])}
        check(added == new_cols[n], f"{n}: only the look columns were added: {added}")
        check(all(set(bc[t]) <= set(ac[t]) and all(ac[t][c] == bc[t][c] for c in bc[t]) for t in bc), f"{n}: old columns unchanged")
        for t, cs in new_cols[n].items():
            for c in cs:
                say(f"     {n}.{t}.{c}: type/default/notnull = {ac[t][c]}")
        # old rows are still there, byte for byte, in the old columns
        same = True
        for t, rows in br.items():
            ncol = len(bc[t])
            names_old = list(bc[t])
            names_new = list(ac[t])
            idx = [names_new.index(c) for c in names_old]
            same &= [tuple(r) for r in rows] == [tuple(r[i] for i in idx) for r in ar[t]]
        check(same, f"{n}: all old rows identical in the old columns ({sum(len(r) for r in br.values())} rows)")
    check(after["publish"][2]["workspaces"][0][after["publish"][1]["workspaces"] and list(after["publish"][1]["workspaces"]).index("show_on_shared_pages")] == 1, "publish: existing workspace has show_on_shared_pages = 1")

    procs = start(new_bins, data, ps)
    s, w0 = call("GET", f"http://127.0.0.1:{rp}/v1/whoami", wh(ws[0]))
    check(s == 200 and (w0["icon"], w0["color"], w0["look_by"]) == (None, None, None) and w0["name"] == "Old A", f"relay whoami: {w0}")
    s, ad = call("GET", f"http://127.0.0.1:{ra}/admin/api/workspaces", RA)
    check(all((w["icon"], w["color"], w["look_by"]) == (None, None, None) for w in ad["items"]) and len(ad["items"]) == 2, "relay admin list: both old workspaces, look null")
    s, pl = call("GET", f"http://127.0.0.1:{rp}/v1/phone/workspaces", ph)
    check(s == 200 and pl["items"][0]["icon"] is None and pl["items"][0]["color"] is None, f"old phone still works, phone list look null: {pl['items'][0]['name']}")
    s, inbox = call("GET", f"http://127.0.0.1:{rp}/v1/inbox", wh(ws[1]))
    check(s == 200 and any(i.get("body", {}).get("text") == "hello before the upgrade" for i in inbox["items"]), "old message still in the inbox")
    s, pwho = call("GET", f"http://127.0.0.1:{pp}/v1/whoami", pwh)
    check(s == 200 and (pwho["icon"], pwho["color"], pwho["look_by"], pwho["show_on_shared_pages"]) == (None, None, None, True), f"publish whoami: icon/color/look_by null, show_on_shared_pages true")
    s, pad = call("GET", f"http://127.0.0.1:{pa}/admin/api/workspaces", PA)
    check(pad["items"][0]["show_on_shared_pages"] is True and pad["items"][0]["files"] == 1, "publish admin list: file count 1, switch on")
    s, b2 = call("GET", f"http://127.0.0.1:{pp}/f/{fid}/blob")
    check(s == 200 and b2 == blob, "old file blob unchanged")
    s, m = call("GET", f"http://127.0.0.1:{pp}/f/{fid}/meta")
    check(s == 200 and m == {"workspace": {"name": "Old Pub", "icon": None, "color": None}}, f"meta (switch on): {m}")
    s, _ = call("PATCH", f"http://127.0.0.1:{pp}/v1/me", pwh, {"show_on_shared_pages": False})
    s, m = call("GET", f"http://127.0.0.1:{pp}/f/{fid}/meta")
    check(s == 200 and m == {"workspace": None}, f"meta (switch off): {m}")
    stop(procs)
finally:
    for p in pids:
        if p.poll() is None:
            p.terminate()
    for n in ("old", "new"):
        wt = tmp / f"src-{n}"
        if wt.exists():
            subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(wt)])
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(ohome, ignore_errors=True)
say("RESULT: " + ("PASS" if ok_all else "FAIL"))
sys.exit(0 if ok_all else 1)
