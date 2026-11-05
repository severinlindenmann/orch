"""Starts agent commands: one run per ticket (lock file), output to .orch/addons/scheduler/logs/, state.json."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import time
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import orchcli, runfiles
from .cron import fmt

DEFAULT_AGENT = 'claude -p "{prompt}"'
GITIGNORE = "locks/\nlogs/\nstate.json\nruns.jsonl\n"


def sdir(root: Path) -> Path:
    """.orch/addons/scheduler/ with logs/ and locks/. A symlink anywhere on that path is refused (a repo could aim
    it at files outside); files in it are written without following symlinks (runfiles.open_append, os.replace)."""
    d = root / ".orch" / "addons" / "scheduler"
    for p in (root / ".orch", root / ".orch" / "addons", d, d / "logs", d / "locks"):
        if p.is_symlink():
            raise RuntimeError(f"{p} is a symbolic link; the scheduler does not use it. Remove it and try again.")
    (d / "logs").mkdir(parents=True, exist_ok=True)
    (d / "locks").mkdir(exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists() and not gi.is_symlink():
        with runfiles.open_append(gi) as f:
            f.write(GITIGNORE)
    return d


def load_config(root: Path) -> dict:
    """The [scheduler] table of .orch/config.toml: agent, interval, inbox_every, [scheduler.agents]."""
    p = root / ".orch" / "config.toml"
    cfg: dict = {}
    if p.is_file():
        try:
            t = tomllib.loads(p.read_text()).get("scheduler")
            cfg = dict(t) if isinstance(t, dict) else {}
        except (tomllib.TOMLDecodeError, OSError):
            cfg = {}
    if not isinstance(cfg.get("agent"), str):
        cfg["agent"] = DEFAULT_AGENT
    for k, d in (("interval", 60), ("inbox_every", 60)):
        try:
            cfg[k] = max(1, int(cfg.get(k, d)))
        except (TypeError, ValueError):
            cfg[k] = d
    return cfg


def load_state(root: Path) -> dict:
    try:
        d = json.loads((root / ".orch" / "addons" / "scheduler" / "state.json").read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(root: Path, state: dict) -> None:
    d = sdir(root)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".state-")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, d / "state.json")


def update_state(root: Path, tid: str, **kw) -> None:
    st = load_state(root)
    st.setdefault(tid, {}).update(kw)
    save_state(root, st)


def pick_agent(cfg: dict, ticket: dict | None) -> str:
    """ext.scheduler.agent may only NAME an entry of [agents] in the local config; never a command from ticket data."""
    want = (((ticket or {}).get("ext") or {}).get("scheduler") or {}).get("agent")
    agents = cfg.get("agents")
    if isinstance(want, str) and isinstance(agents, dict) and isinstance(agents.get(want), str):
        return agents[want]
    return cfg["agent"]


def build_argv(template: str, prompt: str) -> list[str]:
    parts = shlex.split(template)
    if not any("{prompt}" in p for p in parts):
        parts.append("{prompt}")
    return [p.replace("{prompt}", prompt) for p in parts]


def _alive(pid: int) -> bool:
    if not runfiles.valid_pid(pid):
        return False
    if os.name == "nt":
        return runfiles.alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class Run:
    tid: str
    proc: subprocess.Popen | None
    log_path: Path
    lock: Path
    started: datetime
    reason: str
    t0: float = 0.0


class Runner:
    def __init__(self, root: Path):
        self.root = root
        self.runs: dict[str, Run] = {}

    def locked(self, tid: str) -> bool:
        lock = sdir(self.root) / "locks" / f"{tid}.lock"
        if not lock.exists():
            return False
        try:
            pid = int(lock.read_text().strip() or 0)
        except (OSError, ValueError):
            pid = 0
        if pid and _alive(pid):
            return True
        if pid == 0 and tid in self.runs:
            return True
        lock.unlink(missing_ok=True)  # stale: the agent died without the scheduler seeing it
        return False

    def start(self, tid: str, prompt: str, template: str, reason: str, now: datetime) -> bool:
        """Start the agent for a ticket. False if this ticket already has a run."""
        d = sdir(self.root)
        if self.locked(tid):
            return False
        lock = d / "locks" / f"{tid}.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        os.close(fd)
        log_path = d / "logs" / f"{tid}-{now.strftime('%Y%m%dT%H%M%SZ')}.log"
        argv = build_argv(template, prompt)
        with runfiles.open_append(log_path) as f:
            f.write(f"# start {fmt(now)} ticket {tid} ({reason})\n# command {shlex.join(argv[:1])} ...\n")
            f.flush()
            try:
                proc = subprocess.Popen(argv, cwd=self.root, stdout=f, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL)
            except OSError as e:
                f.write(f"# could not start: {e}\n# end {fmt(now)} exit 127\n")
                lock.unlink(missing_ok=True)
                self._history(tid, now, 0, 127)
                update_state(self.root, tid, last_exit=127, last_log=log_path.name)
                orchcli.log(self.root, tid, f"Scheduler could not start the agent ({e.__class__.__name__})")
                return False
        with runfiles.open_append(lock) as f:  # created above with O_EXCL: ours, not a symlink
            f.write(str(proc.pid))
        self.runs[tid] = Run(tid, proc, log_path, lock, now, reason, time.monotonic())
        orchcli.log(self.root, tid, f"Scheduler started an agent run ({reason}). Log: {log_path.name}")
        return True

    def _history(self, tid: str, started: datetime, took: float, code: int) -> None:
        """One line per finished run in runs.jsonl (the dashboard view reads it)."""
        with runfiles.open_append(sdir(self.root) / "runs.jsonl") as f:
            f.write(json.dumps({"ticket": tid, "at": fmt(started), "took": round(took), "exit": code}) + "\n")

    def reap(self, now: datetime, wait: bool = False) -> list[str]:
        """Collect finished runs: log footer, history entry, state. wait=True blocks (tests, --once)."""
        done = []
        for tid, r in list(self.runs.items()):
            code = r.proc.wait() if wait else r.proc.poll()
            if code is None:
                continue
            with runfiles.open_append(r.log_path) as f:
                f.write(f"# end {fmt(datetime.now(UTC))} exit {code}\n")
            r.lock.unlink(missing_ok=True)
            self._history(tid, r.started, time.monotonic() - r.t0, code)
            st = load_state(self.root)
            e = st.setdefault(tid, {})
            e.update(last_exit=code, last_log=r.log_path.name)
            save_state(self.root, st)
            orchcli.log(self.root, tid, f"Scheduler run finished, exit code {code}")
            del self.runs[tid]
            done.append(tid)
        return done
