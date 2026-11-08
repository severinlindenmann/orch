"""Environment bring-up and tear-down for the full e2e: relay + publish from develop, 3 workspaces, receiver.

Reuses e2e/main.py `E` (clean env, workspaces, relay/publish connect). One root per run under /Users/<me>/.tf-fe2e-XXXX.
Everything started here is ended by PID (process group for session leaders) only, never pkill.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REAL_HOME = Path(os.environ.get('E2E_REAL_HOME') or Path.home())
E2E = Path(__file__).resolve().parents[2]  # <repo>/e2e
sys.path.insert(0, str(E2E))
import lib  # noqa: E402
import main as e2emain  # noqa: E402

WORKSPACES = {  # name -> (git?, role)
    "Pilatus": "A: main browser walk, Claude in tmux",
    "Reports": "B: git + remote, second workspace for workspace-to-workspace",
    "Home": "C: no git",
}


class Env:
    def __init__(self, root: Path, repo: Path, bins: dict, sha: str):
        self.root, self.repo, self.bins, self.sha = root, repo, bins, sha
        self.e = e2emain.E("local", root, repo, root.name.rsplit("-", 1)[-1].lower())
        self.e.bins = bins
        self.urls: dict[str, str] = {}
        self.vars: dict[str, str] = {}
        self.headers: dict[str, dict] = {}
        self.timings: dict[str, float] = {}

    # -- bring-up -------------------------------------------------------------------------------
    def up(self, log=print) -> dict:
        e = self.e
        e.home.mkdir(parents=True, exist_ok=True)
        (e.home / ".gitconfig").write_text("[init]\n\tdefaultBranch = main\n")
        t = time.time()
        r = subprocess.run(["uv", "tool", "install", "--reinstall", str(self.repo / "workspace")], env=e.env,
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError("orch install failed: " + r.stderr[-400:])
        self.timings["install_orch_s"] = round(time.time() - t, 1)
        log(f"orch installed in {self.timings['install_orch_s']} s")
        e.pub, e.rel = lib.start_local(e, self.root, self.bins, e.used_ports)
        self.urls.update(relay=e.rel.url, relay_admin=e.rel.admin_url, publish=e.pub.url, publish_admin=e.pub.admin_url)
        self.vars.update(relay_admin_token=e.rel.admin.token, publish_admin_token=e.pub.admin.token)
        self.headers["relay_admin"] = {"X-Orch-Admin": e.rel.admin.token}
        self.headers["publish_admin"] = {"X-Orch-Admin": e.pub.admin.token}
        for name in WORKSPACES:
            e.ws(name)
            for a in ("dashboard", "automation", "focus"):
                rc, out, err = e.addon_add(e.ws(name), a)
                if rc:
                    raise RuntimeError(f"addon add {a} in {name}: {(err or out)[-200:]}")
            e.connect_relay(name, tags={"Pilatus": ["engineering"], "Home": ["private"], "Reports": ["reports"]}[name])
            e.connect_publish(name)
        ids = {n: e.creds[("rel", n)][0] for n in WORKSPACES}
        self.vars.update({f"relay_id_{n.lower()}": i for n, i in ids.items()})
        cur = e.rel.admin.call("GET", "/admin/api/rules").json() or {"rules": []}
        rules = cur.get("rules", []) + [
            {"from": ids["Pilatus"], "to": ids["Reports"], "text": True, "files": True, "delegate": True, "start": True},
            {"from": ids["Reports"], "to": ids["Pilatus"], "text": True, "files": False, "delegate": False, "start": False}]
        e.rel.admin.call("PUT", "/admin/api/rules", {"rules": rules})
        for name in WORKSPACES:
            rc, out, err = e.sh(["orch", "start", "--json", "--no-open"], cwd=e.ws(name), timeout=120)
        self.refresh_urls()
        self.fixtures()
        self.write_status_script()
        return self.env_json()

    def write_status_script(self):
        """A tiny script the browser lanes may call (action `shell`): set the fixture ticket's status through the real CLI, in this run's environment."""
        import shlex
        e = self.e
        script = self.root / "setstatus.sh"
        env_args = " ".join(f"{k}={shlex.quote(v)}" for k, v in e.env.items())
        script.write_text(f"#!/bin/sh\ncd {shlex.quote(str(e.ws('Pilatus')))} || exit 1\nexec env -i {env_args} orch ticket status \"${{2:-{self.vars['ticket_id']}}}\" \"$1\" >/dev/null\n")
        script.chmod(0o700)
        self.vars["setstatus"] = str(script)

    def fixtures(self):
        """One ticket with a question waiting in Pilatus: the steps that need 'a ticket' use it (vars ticket_id, ticket_title)."""
        e = self.e
        w = e.ws("Pilatus")
        rc, out, err = e.sh(["orch", "ticket", "new", "Plan the launch", "--note", "Fixture ticket of the full e2e", "--json"], cwd=w)
        t = json.loads(out)
        self.vars.update(ticket_id=t["id"], ticket_title=t["title"])
        rc2, out2, _ = e.sh(["orch", "ticket", "new", "Focus live check", "--json"], cwd=w)  # a second ticket for the Focus lane, so lanes never share a status
        self.vars["ticket2_id"] = json.loads(out2)["id"]
        p = subprocess.Popen(["orch", "ask", t["id"], "Which greeting should I use?", "--option", "Hi", "--option", "Hello",
                              "--recommend", "Hi"], cwd=w, env=e.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        e.pids.append(p.pid)

    def refresh_urls(self):
        for name in WORKSPACES:
            rc, out, _ = self.e.sh(["orch", "status", "--json"], cwd=self.e.ws(name))
            try:
                for ws in json.loads(out):
                    if ws.get("name") != name:
                        continue
                    for a in ws.get("addons", []):
                        if a.get("url"):
                            key = name.lower() if a["addon"] == "dashboard" else f"{name.lower()}_{a['addon']}"
                            self.urls[key] = a["url"].rstrip("/")
            except ValueError:
                pass

    def env_json(self) -> dict:
        d = {"urls": self.urls, "vars": self.vars, "headers": {}, "root": str(self.root), "sha": self.sha,
             "workspaces": {n: str(self.e.ws(n)) for n in WORKSPACES}}
        p = self.root / "env.json"
        p.write_text(json.dumps(d, indent=1))
        p.chmod(0o600)  # holds the admin keys of this run
        return d

    # -- helpers for lanes ---------------------------------------------------------------------
    def orch(self, ws: str, *args, check=True, timeout=120):
        rc, out, err = self.e.sh(["orch", *args], cwd=self.e.ws(ws), timeout=timeout)
        if check and rc:
            raise RuntimeError(f"orch {' '.join(args)[:60]}: {(err or out)[-200:]}")
        return rc, out, err

    # -- tear-down -----------------------------------------------------------------------------
    def down(self, log=print):
        e = self.e
        for name in WORKSPACES:
            try:
                e.sh(["orch", "relay", "mobile", "off"], cwd=e.ws(name), timeout=30)
            except Exception:  # noqa: BLE001
                pass
            try:
                e.sh(["orch", "stop"], cwd=e.ws(name), timeout=60)
            except Exception:  # noqa: BLE001
                pass
        for fn in reversed(e.cleanup):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
        for pid in e.pids:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    try:
                        os.killpg(pid, sig)  # started with start_new_session: its children too
                    except OSError:
                        os.kill(pid, sig)
                except OSError:
                    break
                time.sleep(0.4)
        sweep_tmux(str(self.root))  # live agent runs live in their own tmux server (socket orch-<hash>): end the ones under this root
        leaked = e2emain.leaked_servers(self.root)
        if leaked:
            log(f"LEAK: add-on servers still running: {leaked}")
        return leaked


def tmux_sockets_under(root_prefix: str) -> set[str]:
    """Sockets (orch-<hash>) of tmux servers whose sessions run in a folder under `root_prefix`."""
    import re
    ps = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True).stdout
    out = set()
    for ln in ps.splitlines():
        m = re.search(r"tmux -L (orch-\w+) .*-c (\S+)", ln)
        if m and m.group(2).startswith(root_prefix):
            out.add(m.group(1))
    return out


def sweep_tmux(root_prefix: str) -> list[str]:
    """End every tmux server (live agent sessions) that runs under `root_prefix`, by exact socket. Returns the sockets ended."""
    socks = sorted(tmux_sockets_under(root_prefix))
    for s in socks:
        subprocess.run(["tmux", "-L", s, "kill-server"], capture_output=True)
    return socks


def sweep_orphans(log=print) -> list[str]:
    """At the start of a run: end tmux servers of earlier runs that died without teardown (their run folder has no env.json or is gone)."""
    import re
    ps = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True).stdout
    ended = []
    for ln in ps.splitlines():
        m = re.search(r"tmux -L (orch-\w+) .*-c (/\S*?/\.tf-fe2e-\w+)/", ln)
        if m and not (Path(m.group(2)) / "env.json").exists():
            subprocess.run(["tmux", "-L", m.group(1), "kill-server"], capture_output=True)
            ended.append(m.group(1))
    if ended:
        log(f"ended {len(set(ended))} tmux server(s) left over from earlier runs")
    return ended


def claude_under(root_prefix: str) -> list[str]:
    """Processes of live agents whose command line or folder mentions the run folder."""
    ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    return [ln.strip()[:120] for ln in ps.splitlines() if root_prefix in ln and ("claude" in ln or "tmux" in ln)]


def build_bins(repo: Path, log=print) -> dict:
    """cargo build both servers from <repo> (shared CARGO_TARGET_DIR). The caller already holds the heavy lock."""
    env = {**os.environ, "PATH": "/opt/homebrew/opt/rustup/bin:" + os.environ.get("PATH", ""),
           "CARGO_TARGET_DIR": os.environ.get("CARGO_TARGET_DIR", str(REAL_HOME / "orch-dev/.cargo-target-v2"))}
    for crate in ("publish", "relay"):
        # embedded web files are not always rebuilt across worktrees: touch the crate's main
        for f in (repo / crate / "src").glob("main.rs"):
            f.touch()
        t = time.time()
        r = subprocess.run(["cargo", "build", "--release", "-j", "4", "-q"], cwd=repo / crate, env=env,
                           capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"cargo build {crate} failed: {r.stderr[-500:]}")
        log(f"built {crate} in {time.time() - t:.0f} s")
    tgt = env["CARGO_TARGET_DIR"]
    return {"publish": f"{tgt}/release/orch-publish", "relay": f"{tgt}/release/orch-relay"}
