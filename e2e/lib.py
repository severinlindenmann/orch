"""Shared helpers for the e2e scenarios: process env, http, servers, workspaces, admin access."""
from __future__ import annotations

import io
import json
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path


REGISTRY: dict[str, dict] = {}


def scenario(sid: str, slow: bool = False, local_only: bool = False):
    def deco(fn):
        REGISTRY[sid] = {"fn": fn, "slow": slow, "local_only": local_only}
        return fn

    return deco


class Fail(Exception):
    pass


class Skip(Exception):
    pass


def check(cond, msg: str) -> None:
    if not cond:
        raise Fail(msg)


# ---- http ------------------------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


class Resp:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status, self.headers, self.body = status, headers, body

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self):
        try:
            return json.loads(self.body)
        except ValueError:
            return None

    def __repr__(self):
        return f"<{self.status} {self.text[:120]}>"


def http(method: str, url: str, headers: dict | None = None, body=None, timeout: float = 60) -> Resp:
    h = dict(headers or {})
    data = None
    if isinstance(body, (dict, list)):
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    elif body is not None:
        data = body
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with _opener.open(req, timeout=timeout) as r:
            return Resp(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read())
    except urllib.error.HTTPError as e:
        return Resp(e.code, {k.lower(): v for k, v in e.headers.items()}, e.read())


def free_port(used: set[int]) -> int:
    for _ in range(500):
        p = random.randint(18000, 18999)
        if p in used:
            continue
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
            except OSError:
                continue
        used.add(p)
        return p
    raise RuntimeError("no free port in 18000-18999")


def wait_http(url: str, secs: float = 30) -> bool:
    end = time.time() + secs
    while time.time() < end:
        try:
            if http("GET", url, timeout=3).status == 200:
                return True
        except OSError:
            pass
        time.sleep(0.3)
    return False


def tar_gz(files: dict[str, str | bytes], extra=None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, content in files.items():
            raw = content.encode() if isinstance(content, str) else content
            ti = tarfile.TarInfo(name)
            ti.size = len(raw)
            ti.mode = 0o644
            t.addfile(ti, io.BytesIO(raw))
    return buf.getvalue()


# ---- admin access (local: direct, live: through ssh on the VPS) -------------------------------------


class Admin:
    """Calls an admin API. direct: http to the admin port. ssh: curl on the VPS, token read there (never printed)."""

    def __init__(self, base: str, token: str | None = None, ssh: dict | None = None):
        self.base, self.token, self.ssh = base.rstrip("/"), token, ssh  # ssh = {cmd, tokenfile}

    def call(self, method: str, path: str, body=None, raw: bytes | None = None) -> Resp:
        if self.ssh is None:
            return http(method, self.base + path, {"X-Orch-Admin": self.token or ""}, raw if raw is not None else body)
        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        ct = "" if raw is not None or body is None else "-H 'Content-Type: application/json'"
        remote = (
            f"sudo sh -c 'T=$(cat {self.ssh['tokenfile']}); curl -s -o /dev/stdout -w \"\\n%{{http_code}}\" "
            f"-X {method} -H \"X-Orch-Admin: $T\" {ct} --data-binary @- {self.base}{path}'"
        )
        p = subprocess.run([*self.ssh["cmd"], remote], input=payload, capture_output=True, timeout=120)
        out = p.stdout
        if p.returncode != 0 or b"\n" not in out:
            raise Fail(f"ssh admin call failed: {p.stderr.decode()[-200:]}")
        data, _, code = out.rpartition(b"\n")
        return Resp(int(code), {}, data)


# ---- local servers ---------------------------------------------------------------------------------


class Server:
    def __init__(self, name: str, pub: str, admin: str, admin_api: Admin, proc=None, data: Path | None = None):
        self.name, self.url, self.admin_url, self.admin, self.proc, self.data = name, pub, admin, admin_api, proc, data


def start_local(e, tmp: Path, bins: dict, used: set[int]) -> tuple[Server, Server]:
    env = {"PATH": e.path, "HOME": str(tmp / "home"), "LANG": "C.UTF-8"}
    tok_p, tok_r = "p" * 8 + os.urandom(16).hex(), "r" * 8 + os.urandom(16).hex()
    # publish
    pp, pa = free_port(used), free_port(used)
    lo = free_port(used)
    pd = tmp / "publish-data"
    pd.mkdir()
    pub_env = {**env, "ORCH_PUBLISH_DATA_DIR": str(pd), "ORCH_PUBLISH_LISTEN": f"127.0.0.1:{pp}",
               "ORCH_PUBLISH_ADMIN_LISTEN": f"127.0.0.1:{pa}", "ORCH_PUBLISH_ADMIN_TOKEN": tok_p,
               "ORCH_PUBLISH_PUBLIC_ORIGIN": f"http://127.0.0.1:{pp}", "ORCH_PUBLISH_MAX_FILE_MB": "2",
               "ORCH_PUBLISH_APP_PORTS": f"{lo}-{lo}"}
    # app ports: need a small free range; find 10 consecutive free ports
    base = None
    for _ in range(200):
        b = random.randint(18000, 18980)
        if all(p not in used for p in range(b, b + 10)):
            ok = True
            for p in range(b, b + 10):
                with socket.socket() as s:
                    try:
                        s.bind(("127.0.0.1", p))
                    except OSError:
                        ok = False
                        break
            if ok:
                base = b
                break
    used.update(range(base, base + 10))
    pub_env["ORCH_PUBLISH_APP_PORTS"] = f"{base}-{base + 9}"
    log = open(tmp / "publish.log", "w")
    pproc = subprocess.Popen([bins["publish"]], env=pub_env, stdout=log, stderr=log, cwd=tmp)
    e.pids.append(pproc.pid)
    # relay
    rp, ra = free_port(used), free_port(used)
    rd = tmp / "relay-data"
    rd.mkdir()
    (tmp / "relay-master.key").write_bytes(os.urandom(32))
    rel_env = {**env, "ORCH_RELAY_DATA_DIR": str(rd), "ORCH_RELAY_MASTER_KEY_FILE": str(tmp / "relay-master.key"),
               "ORCH_RELAY_LISTEN": f"127.0.0.1:{rp}", "ORCH_RELAY_ADMIN_LISTEN": f"127.0.0.1:{ra}",
               "ORCH_RELAY_ADMIN_TOKEN": tok_r, "ORCH_RELAY_PUBLIC_ORIGIN": f"http://127.0.0.1:{rp}"}
    rlog = open(tmp / "relay.log", "w")
    rproc = subprocess.Popen([bins["relay"]], env=rel_env, stdout=rlog, stderr=rlog, cwd=tmp)
    e.pids.append(rproc.pid)
    pub = Server("publish", f"http://127.0.0.1:{pp}", f"http://127.0.0.1:{pa}", Admin(f"http://127.0.0.1:{pa}", tok_p), pproc, pd)
    rel = Server("relay", f"http://127.0.0.1:{rp}", f"http://127.0.0.1:{ra}", Admin(f"http://127.0.0.1:{ra}", tok_r), rproc, rd)
    for s in (pub, rel):
        if not wait_http(s.url + "/health"):
            raise Fail(f"{s.name} did not start; see {tmp}/{s.name}.log")
    return pub, rel


# ---- text helpers ----------------------------------------------------------------------------------


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)
