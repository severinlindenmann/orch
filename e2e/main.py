"""e2e driver. Started by run.sh inside `env -i` (clean environment). Usage: main.py <id|all> --mode local|live."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import lib  # noqa: E402
from lib import Admin, Fail, Resp, Skip, check, http  # noqa: E402

REGISTRY = lib.REGISTRY


class E:
    """Everything a scenario needs."""

    def __init__(self, mode: str, tmp: Path, repo: Path, run_id: str):
        self.mode, self.tmp, self.repo, self.run_id = mode, tmp, repo, run_id
        self.home = tmp / "home"
        self.bin = tmp / "bin"
        self.pids: list[int] = []
        self.used_ports: set[int] = set()
        self.pub: lib.Server | None = None
        self.rel: lib.Server | None = None
        self.creds: dict[tuple[str, str], tuple[str, str]] = {}
        self.cleanup: list = []
        self._inited: set[str] = set()
        self._addons = False
        self._rules_done = False
        self.path = os.pathsep.join(
            [str(self.bin)] + [p for p in os.environ.get("E2E_PATH_EXTRA", "").split(os.pathsep) if p]
            + ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
        )
        self.env = {
            "HOME": str(self.home), "PATH": self.path, "USER": "e2e", "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "TERM": "dumb", "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", ""),
            "UV_TOOL_DIR": str(tmp / "uvtools"), "UV_TOOL_BIN_DIR": str(self.bin),
            "ORCH_REPO": str(repo), "ORCH_HOME": os.environ.get("E2E_ORCH_HOME") or str(tmp / "orch-tool"),
            "GIT_AUTHOR_NAME": "e2e", "GIT_AUTHOR_EMAIL": "e2e@example.invalid",
            "GIT_COMMITTER_NAME": "e2e", "GIT_COMMITTER_EMAIL": "e2e@example.invalid",
            "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"), "GIT_TERMINAL_PROMPT": "0",
        }
        self.env = {k: v for k, v in self.env.items() if v != ""}
        self.ws_dir = tmp / "ws"
        self.orch_home = Path(self.env["ORCH_HOME"])

    # -- running things --
    def sh(self, cmd, cwd=None, input=None, env=None, timeout=300, check_rc=False):
        if isinstance(input, str):
            input = input.encode()
        p = subprocess.run(cmd, cwd=cwd or self.tmp, env={**self.env, **(env or {})}, input=input,
                           capture_output=True, timeout=timeout)
        out, err = p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
        if check_rc and p.returncode != 0:
            raise Fail(f"{' '.join(map(str, cmd))[:80]} exit {p.returncode}: {(err or out).strip()[-200:]}")
        return p.returncode, out, err

    def orch(self, ws, *args, ok=True, by=None):
        """Run orch in a workspace. Returns (rc, stdout, stderr); with ok=True a non-zero exit fails."""
        a = list(args)
        if by:
            a += ["--by", by]
        rc, out, err = self.sh(["orch", *a], cwd=self.path_of(ws))
        if ok and rc != 0:
            raise Fail(f"orch {' '.join(a)[:60]} exit {rc}: {(err or out).strip()[-200:]}")
        return rc, out, err

    def orchj(self, ws, *args, by=None):
        rc, out, err = self.orch(ws, *args, "--json", by=by)
        try:
            return json.loads(out)
        except ValueError:
            raise Fail(f"orch {' '.join(args)[:50]} did not print JSON: {out[:150]}") from None

    def path_of(self, ws) -> Path:
        return ws if isinstance(ws, Path) else self.ws(ws)

    # -- workspaces --
    def ws(self, name: str) -> Path:
        """Pilatus (git), Home (no git), Reports (git + local bare remote). Created and `orch init`-ed once."""
        d = self.ws_dir / name
        if name not in self._inited:
            d.mkdir(parents=True, exist_ok=True)
            if name in ("Pilatus", "Reports"):
                self.sh(["git", "init", "-q", "-b", "main"], cwd=d, check_rc=True)
            if name == "Reports":
                rem = self.tmp / "reports-remote.git"
                self.sh(["git", "init", "-q", "--bare", "-b", "main", str(rem)], check_rc=True)
                self.sh(["git", "remote", "add", "origin", str(rem)], cwd=d, check_rc=True)
            self.sh(["orch", "init"], cwd=d, check_rc=True)
            self._inited.add(name)
        return d

    def addon_add(self, ws, name: str, *flags: str):
        """`orch addon add <name|folder> --yes` (the consent text is printed, not asked)."""
        return self.sh(["orch", "addon", "add", str(name), "--yes", *flags], cwd=self.path_of(ws), timeout=600)

    def sched_config(self, ws, agent_line: str, interval: int = 2, inbox_every: int | None = None):
        """Write the [scheduler] table of .orch/config.toml (agent_line is a TOML line `agent = ...`)."""
        p = self.path_of(ws) / ".orch" / "config.toml"
        extra = f"inbox_every = {inbox_every}\n" if inbox_every else ""
        p.write_text(f"[scheduler]\n{agent_line}\ninterval = {interval}\n{extra}")

    def ensure_addons(self):
        if not self._addons:
            for a in ("dashboard", "scheduler"):
                rc, out, err = self.addon_add(self.ws("Pilatus"), a)
                if rc != 0:
                    raise Fail(f"addon add {a}: {(err or out)[-200:]}")
            self._addons = True

    def label(self, name: str) -> str:
        return name if self.mode == "local" else f"e2e-{self.run_id}-{name}"

    def connect_publish(self, name: str, rights=None, tags=None, desc=None) -> tuple[str, str]:
        key = ("pub", name)
        if key not in self.creds:
            r = self.pub.admin.call("POST", "/admin/api/workspaces", {
                "name": self.label(name), "description": desc or f"{name} workspace", "tags": tags or [name.lower()],
                "rights": rights or {"files": True, "apps": True, "permanent": False, "public": False}})
            check(r.status == 201, f"publish admin add {name}: {r}")
            j = r.json()
            self.creds[key] = (j["id"], j["token"])
            self.prompts = getattr(self, "prompts", {})
            self.prompts[key] = j.get("prompt", "")
            self.cleanup.append(lambda i=j["id"]: self.pub.admin.call("DELETE", f"/admin/api/workspaces/{i}"))
            self.orch(self.ws(name), "publish", "connect", self.pub.url, "--workspace", j["id"], "--token", j["token"])
        return self.creds[key]

    def connect_relay(self, name: str, tags=None, desc=None) -> tuple[str, str]:
        key = ("rel", name)
        if key not in self.creds:
            r = self.rel.admin.call("POST", "/admin/api/workspaces", {
                "name": self.label(name), "description": desc or f"{name} workspace", "tags": tags or [name.lower()]})
            check(r.status == 201, f"relay admin add {name}: {r}")
            j = r.json()
            self.creds[key] = (j["id"], j["token"])
            self.prompts = getattr(self, "prompts", {})
            self.prompts[key] = j.get("prompt", "")
            self.cleanup.append(lambda i=j["id"]: self.rel.admin.call("DELETE", f"/admin/api/workspaces/{i}"))
            self.orch(self.ws(name), "relay", "connect", self.rel.url, "--workspace", j["id"], "--token", j["token"])
        return self.creds[key]

    def relay_all(self):
        """R1 setup: three relay workspaces and the rules Pilatus->Reports (all four), Home->Pilatus (text)."""
        ids = {n: self.connect_relay(n, tags={"Pilatus": ["engineering", "product"], "Home": ["private", "notes"],
                                              "Reports": ["reports", "weekly"]}[n],
                                     desc={"Pilatus": "Product work for Pilatus", "Home": "Private notes at home",
                                           "Reports": "Writes the weekly reports"}[n])[0]
               for n in ("Pilatus", "Home", "Reports")}
        if not self._rules_done:
            cur = self.rel.admin.call("GET", "/admin/api/rules").json() or {"rules": []}
            old = cur.get("rules", [])
            mine = [
                {"from": ids["Pilatus"], "to": ids["Reports"], "text": True, "files": True, "delegate": True, "start": True},
                {"from": ids["Home"], "to": ids["Pilatus"], "text": True, "files": False, "delegate": False, "start": False},
            ]
            r = self.rel.admin.call("PUT", "/admin/api/rules", {"rules": old + mine})
            check(r.status == 200, f"set rules: {r}")
            self.cleanup.append(lambda: self.rel.admin.call("PUT", "/admin/api/rules", {"rules": old}))
            self._rules_done = True
        return ids

    # -- relay as a workspace (raw api) --
    def rapi(self, name: str, method: str, path: str, body=None, headers=None) -> Resp:
        wid, tok = self.creds[("rel", name)]
        h = {"X-Orch-Workspace": wid, "Authorization": f"Bearer {tok}", **(headers or {})}
        return http(method, self.rel.url + path, h, body)

    def papi(self, name: str, method: str, path: str, body=None, headers=None) -> Resp:
        wid, tok = self.creds[("pub", name)]
        h = {"X-Orch-Workspace": wid, "Authorization": f"Bearer {tok}", **(headers or {})}
        return http(method, self.pub.url + path, h, body)

    def msg(self, frm: str, to: str, typ: str, body: dict, **kw) -> dict:
        import secrets
        m = {"schema": "orch.msg/1", "id": "m_" + "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(16)),
             "from": frm, "to": to, "type": typ, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "body": body}
        m.update(kw)
        return m


def run_scenarios(e: E, ids: list[str], out_md: Path) -> dict:
    results = {}
    lines = []
    for sid in ids:
        sc = REGISTRY[sid]
        t0 = time.time()
        try:
            if sc["local_only"] and e.mode != "local":
                raise Skip("local mode only")
            note = sc["fn"](e)
            status, reason = "PASS", note or ""
        except Skip as s:
            status, reason = "SKIP", str(s)
        except Fail as f:
            status, reason = "FAIL", str(f)
        except Exception as x:  # noqa: BLE001
            status, reason = "FAIL", f"{type(x).__name__}: {x} ({traceback.format_exc().splitlines()[-3].strip()})"
        reason = " ".join(str(reason).split())[:300]
        line = f"{sid:<5} {status:<4} {reason}"
        print(line, flush=True)
        lines.append(f"- {line}  ({time.time() - t0:.0f}s)")
        results[sid] = status
        with open(out_md, "a") as f:
            f.write(lines[-1] + "\n")
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what")
    ap.add_argument("--mode", default="local", choices=["local", "live"])
    ap.add_argument("--fast", action="store_true", help="skip slow scenarios (A5)")
    ap.add_argument("--tmp", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--bins", default="")
    a = ap.parse_args()
    import scenarios_ws, scenarios_addons, scenarios_pub, scenarios_rel, scenarios_misc  # noqa: F401,E401

    if a.what == "all":
        ids = list(REGISTRY)
    else:  # comma list; a single letter (W, A, P, R, M, F) selects the group
        ids = []
        for w in a.what.split(","):
            ids += [k for k in REGISTRY if k[0] == w] if len(w) == 1 else [w]
    # run order: W A P R M F  (A0 before A4/A5)
    order = {"W": 0, "A": 1, "P": 2, "R": 3, "M": 4, "F": 5}
    ids = sorted(ids, key=lambda s: (order.get(s[0], 9), int("".join(c for c in s[1:] if c.isdigit()) or 0)))
    for s in ids:
        if s not in REGISTRY:
            print(f"unknown scenario {s}; known: {', '.join(sorted(REGISTRY))}")
            return 2
    if a.fast:
        ids = [s for s in ids if not REGISTRY[s]["slow"]]
    tmp, repo = Path(a.tmp), Path(a.repo)
    run_id = tmp.name.rsplit("-", 1)[-1].lower()
    e = E(a.mode, tmp, repo, run_id)
    out_dir = repo / "e2e" / "out" / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "results.md"
    out_md.write_text(f"# e2e {a.mode} {a.what} {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    (e.home).mkdir(parents=True, exist_ok=True)
    (e.home / ".gitconfig").write_text("[init]\n\tdefaultBranch = main\n")
    try:
        print(f"e2e {a.mode}: {len(ids)} scenarios, tmp {tmp}", flush=True)
        r = subprocess.run(["uv", "tool", "install", str(repo / "workspace")], env=e.env, capture_output=True, text=True)
        if r.returncode:
            print("orch install failed:", r.stderr[-400:])
            return 1
        needs_servers = any(s[0] in "PRMF" for s in ids)
        if needs_servers:
            if a.mode == "local":
                bins = json.loads(a.bins)
                e.pub, e.rel = lib.start_local(e, tmp, bins, e.used_ports)
            else:
                e.pub, e.rel = live_servers(e)
                if e.pub is None:
                    for s in ids:
                        if s[0] in "PRMF":
                            print(f"{s:<5} SKIP  live servers are not up")
                    ids = [s for s in ids if s[0] not in "PRMF"]
        res = run_scenarios(e, ids, out_md)
    finally:
        for fn in reversed(e.cleanup):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
        stop_scheduler(e)
        for pid in e.pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        time.sleep(0.5)
        for pid in e.pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    n = {k: sum(1 for v in res.values() if v == k) for k in ("PASS", "FAIL", "SKIP")}
    summary = f"\nSUMMARY {a.mode}: {n['PASS']} pass, {n['FAIL']} fail, {n['SKIP']} skip"
    print(summary)
    with open(out_md, "a") as f:
        f.write(summary + "\n")
    print(f"results: {out_md}")
    return 1 if n["FAIL"] else 0


def stop_scheduler(e: E) -> None:
    for wsd in (e.ws_dir.glob("*") if e.ws_dir.exists() else []):
        pidf = wsd / ".orch" / "addons" / "scheduler" / "scheduler.pid"
        if pidf.exists():
            try:
                os.kill(int(pidf.read_text().strip()), signal.SIGTERM)
            except (OSError, ValueError):
                pass


def live_servers(e: E):
    pu, rl = "https://publish.severin.io", "https://relay.severin.io"
    for u in (pu, rl):
        try:
            if http("GET", u + "/health", timeout=10).status != 200:
                print(f"live: {u}/health not 200")
                return None, None
        except OSError as ex:
            print(f"live: {u}/health failed: {ex!r}")
            return None, None
    host = os.environ.get("E2E_VPS", "ubuntu@179.237.125.155")
    key = os.path.join(os.environ.get("E2E_REAL_HOME", ""), ".ssh", "orch-dev_rsa")
    base = ["ssh", "-i", key, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={os.environ.get('E2E_REAL_HOME', '')}/.ssh/known_hosts", host]
    def admin(port, tok_env, tokfile):
        url = f"http://100.71.130.135:{port}"
        tok = os.environ.get(tok_env)
        if tok:  # direct over the private network (token from Proton Pass, passed by run.sh)
            try:
                if http("GET", url + "/admin/api/workspaces", {"X-Orch-Admin": tok}, timeout=5).status == 200:
                    return Admin(url, tok)
            except OSError:
                pass
        return Admin(url, None, {"cmd": base, "tokenfile": tokfile})  # fallback: curl on the VPS over ssh

    pa = admin(8411, "E2E_PUBLISH_ADMIN_TOKEN", "/etc/orch-publish/admin-token")
    ra = admin(8412, "E2E_RELAY_ADMIN_TOKEN", "/etc/orch-relay/admin-token")
    return lib.Server("publish", pu, pa.base, pa), lib.Server("relay", rl, ra.base, ra)


if __name__ == "__main__":
    sys.exit(main())
