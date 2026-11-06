#!/usr/bin/env python3
"""Docs that run: execute every `$ orch ...` line shown in docs/** and README.md.

    python3 e2e/docs_check.py [--fast] [--bins '{"publish": "...", "relay": "..."}'] [--only FILE]

Each Markdown file gets its own fresh temp workspace and runs its lines in order, in a clean environment (like `env -i`:
own HOME, own ORCH_HOME, orch installed into a temp uv tool folder; nothing from the shell and never your real ~/.config/orch).
Only lines inside ``` fences that start with `$ ` count. Rules:

  $ orch ticket show <id>            <id> = the last ticket made by `orch ticket new` without --parent; <sub> = the last with --parent
  $ orch check reopen <id> c1  # refused   expected exit code 2 (a refusal the docs show). `# error` = any non-zero exit.
  $ orch relay inbox  # server       needs the local publish/relay servers; skipped with --fast
  $ orch run attach <id>  # skip     shown in the docs, not run (interactive, or needs a real service)
  no comment                         must exit 0

The agent in the docs is called `my-agent`: a shim for e2e/fixtures/generic-agent/agent.py (the generic fake agent).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "e2e"))
TAGS = ("refused", "error", "server", "skip")
FENCE = re.compile(r"^\s*```")
PLACEHOLDER = re.compile(r"<[a-z][a-z ]*>")
TICKET = re.compile(r"\[(t_[a-z0-9]+)\]")


def doc_files() -> list[Path]:
    files = [REPO / "README.md"] + sorted((REPO / "docs").rglob("*.md"))
    return [f for f in files if f.exists()]


def parse(path: Path) -> list[tuple[int, list[str], str]]:
    """(line number, tokens, tag) for every `$ orch ...` line in a fenced block."""
    out, inside = [], False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line):
            inside = not inside
            continue
        if not inside or not line.startswith("$ "):
            continue
        try:
            toks = shlex.split(line[2:])
        except ValueError as e:
            raise SystemExit(f"{path.name}:{n}: cannot read the line ({e})")
        tag = ""
        if "#" in toks:
            i = toks.index("#")
            tag = toks[i + 1] if i + 1 < len(toks) else ""
            toks = toks[:i]
            if tag not in TAGS:
                raise SystemExit(f"{path.name}:{n}: unknown tag '# {tag}' (use one of {', '.join(TAGS)})")
        if toks and toks[0] == "orch":
            out.append((n, toks, tag))
    return out


class Env:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "home"
        self.bin = tmp / "bin"
        self.uvbin = tmp / "uvbin"
        self.uvtools = tmp / "uvtools"
        for d in (self.home, self.bin, self.uvbin, self.uvtools):
            d.mkdir()
        real_home = Path(os.path.expanduser("~"))
        # ORCH_HOME is trusted only as a plain folder under the real home with no .git/.orch/.agents above it
        self.orch_home = Path(tempfile.mkdtemp(prefix=".orch-docs-", dir=real_home))
        tools = {Path(shutil.which(t) or "/usr/bin/true").parent for t in ("uv", "git", "tmux")}
        path = [str(self.bin), str(self.uvbin), *map(str, sorted(tools)), "/usr/bin", "/bin"]
        self.env = {
            "HOME": str(self.home), "PATH": os.pathsep.join(dict.fromkeys(path)), "USER": "docs", "LANG": "C.UTF-8",
            "TERM": "dumb", "ORCH_REPO": str(REPO), "ORCH_HOME": str(self.orch_home),
            "UV_TOOL_DIR": str(self.uvtools), "UV_TOOL_BIN_DIR": str(self.uvbin),
            "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR") or str(real_home / ".cache" / "uv"),
            "GIT_AUTHOR_NAME": "docs", "GIT_AUTHOR_EMAIL": "docs@example.invalid",
            "GIT_COMMITTER_NAME": "docs", "GIT_COMMITTER_EMAIL": "docs@example.invalid",
            "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"), "GIT_TERMINAL_PROMPT": "0",
        }
        self.pids: list[int] = []
        self.path = self.env["PATH"]

    def run(self, cmd, cwd, timeout=120) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, cwd=cwd, env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=timeout)

    def install(self) -> None:
        r = self.run(["uv", "tool", "install", "-q", str(REPO / "workspace")], self.tmp, 300)
        if r.returncode:
            raise SystemExit(f"orch install failed: {r.stderr[-400:]}")
        py = next(iter(glob.glob(str(self.uvtools / "*" / "bin" / "python"))), None)
        if not py:
            raise SystemExit("no python in the orch tool folder")
        agent = REPO / "e2e" / "fixtures" / "generic-agent" / "agent.py"
        shim = self.bin / "my-agent"
        shim.write_text(f'#!/bin/sh\nORCH_CMD={shlex.quote(str(self.uvbin / "orch"))} exec {shlex.quote(py)} '
                        f'{shlex.quote(str(agent))} "$@"\n')
        shim.chmod(0o755)

    def cleanup(self) -> None:
        for p in self.pids:
            try:
                os.kill(p, 15)
            except OSError:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.orch_home, ignore_errors=True)


def find_bins(given: str) -> dict:
    if given:
        return json.loads(given)
    target = Path(os.environ.get("CARGO_TARGET_DIR") or Path.home() / "orch-dev" / ".cargo-target-v2")
    bins = {}
    for name, crate in (("publish", "publish"), ("relay", "relay")):
        p = target / "release" / f"orch-{name}"
        if not p.exists():
            env = {**os.environ, "CARGO_TARGET_DIR": str(target)}
            print(f"building orch-{name} (release) ...", flush=True)
            r = subprocess.run(["cargo", "build", "--release", "-j", "4", "-q"], cwd=REPO / crate, env=env)
            if r.returncode:
                raise SystemExit(f"cannot build {crate}; use --fast to skip the server lines")
        bins[name] = str(p)
    return bins


class Servers:
    def __init__(self, env: Env, bins: dict):
        import lib  # e2e/lib.py

        shim = type("E", (), {"path": env.path, "pids": env.pids})()
        self.lib = lib
        self.pub, self.rel = lib.start_local(shim, env.tmp, bins, set())

    def connect(self, env: Env, ws: Path) -> None:
        for kind, srv in (("publish", self.pub), ("relay", self.rel)):
            r = srv.admin.call("POST", "/admin/api/workspaces", {"name": f"docs-{ws.name}", "description": "docs check",
                               "tags": ["docs"], **({"rights": {"files": True, "apps": True, "permanent": False,
                                                                "public": False}} if kind == "publish" else {})})
            if r.status != 201:
                raise SystemExit(f"{kind} admin add failed: {r}")
            j = r.json()
            for cmd in (["orch", "addon", "add", kind, "--yes"],
                        ["orch", kind, "connect", srv.url, "--workspace", j["id"], "--token", j["token"]]):
                p = env.run(cmd, ws)
                if p.returncode:
                    raise SystemExit(f"{' '.join(cmd[:4])}: {(p.stderr or p.stdout)[-300:]}")


def wait_runs(ws: Path) -> None:
    """After `orch run start` the agent works in the background; wait until no run claim is left."""
    end = time.time() + 40
    while time.time() < end and glob.glob(str(ws / ".orch" / "run" / "tickets" / "*.json")):
        time.sleep(0.3)


def check_file(env: Env, path: Path, fast: bool, servers: Servers | None, only_listed: bool) -> list[str]:
    lines = parse(path)
    if not lines:
        return []
    ws = env.tmp / f"ws-{path.stem}"
    ws.mkdir()
    (ws / "report.csv").write_text("item,total\nwidgets,12\n")
    for cmd in (["config", "agent", "add", "my-agent", "--command", "my-agent {prompt}"],
                ["config", "set", "workspace.agent", "my-agent"]):
        env.run(["orch", *cmd], ws)  # the agent the docs talk about is already chosen
    needs_server = any(t == "server" for _, _, t in lines)
    if needs_server and servers:
        servers.connect(env, ws)
    fails, ids = [], {"id": "", "sub": ""}
    for n, toks, tag in lines:
        label = f"{path.relative_to(REPO)}:{n}: {' '.join(toks)}"
        if tag == "skip" or (tag == "server" and (fast or not servers)):
            print(f"  skip  {label}")
            continue
        args = []
        for t in toks[1:]:
            t = t.replace("<id>", ids["id"]).replace("<sub>", ids["sub"])
            args.append(t)
        left = [a for a in args if PLACEHOLDER.search(a)]
        if left or (("<id>" in toks[1:]) and not ids["id"]):
            fails.append(f"{label}\n      placeholder not filled: {left or '<id>'} (make a ticket earlier in the file, or tag the line '# skip')")
            continue
        try:
            p = env.run(["orch", *args], ws)
        except subprocess.TimeoutExpired:
            fails.append(f"{label}\n      timed out")
            continue
        out = (p.stdout + p.stderr).strip()
        if args[:2] == ["ticket", "new"]:
            m = TICKET.search(out)
            if m:
                ids["sub" if "--parent" in args else "id"] = m.group(1)
        if args[:2] == ["run", "start"]:
            wait_runs(ws)
        want = {"": "rc == 0", "server": "rc == 0", "refused": "rc == 2", "error": "rc != 0"}[tag]
        ok = {"": p.returncode == 0, "server": p.returncode == 0, "refused": p.returncode == 2,
              "error": p.returncode != 0}[tag]
        print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
        if not ok:
            fails.append(f"{label}\n      exit {p.returncode}, the docs show {want}\n      " + out[-400:].replace("\n", "\n      "))
    env.run(["orch", "stop"], ws)  # background add-ons started by the docs
    return fails


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fast", action="store_true", help="skip lines tagged '# server' (no local publish/relay)")
    ap.add_argument("--bins", default="", help='JSON {"publish": path, "relay": path}; default: build in the shared cargo target')
    ap.add_argument("--only", help="check only this file (e.g. docs/workspace.md)")
    a = ap.parse_args()
    files = [REPO / a.only] if a.only else doc_files()
    parsed = {f: parse(f) for f in files}
    todo = [f for f in files if parsed[f]]
    if not todo:
        print("no `$ orch` lines found")
        return 1
    tmp = Path(tempfile.mkdtemp(prefix=".tf-docs-", dir=Path.home() / "orch-dev"))
    env = Env(tmp)
    servers = None
    fails: list[str] = []
    try:
        env.install()
        if not a.fast and any(t == "server" for f in todo for _, _, t in parsed[f]):
            servers = Servers(env, find_bins(a.bins))
        for f in todo:
            print(f"{f.relative_to(REPO)}", flush=True)
            fails += check_file(env, f, a.fast, servers, bool(a.only))
    finally:
        env.cleanup()
    total = sum(len(parsed[f]) for f in todo)
    if fails:
        print(f"\n{len(fails)} of {total} lines in the docs do not run as shown:")
        print("\n".join("  " + x for x in fails))
        return 1
    print(f"\ndocs check: all {total} lines run as shown" + (" (server lines skipped)" if a.fast else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
