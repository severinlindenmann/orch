"""Starts agent commands: one run per ticket (lock file), output to .orch/scheduler/logs/, state.json."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import orchcli
from .cron import fmt

DEFAULT_AGENT = 'claude -p "{prompt}"'
GITIGNORE = "scheduler.pid\nscheduler.log\nlocks/\n"


def sdir(root: Path) -> Path:
    d = root / ".orch" / "scheduler"
    (d / "logs").mkdir(parents=True, exist_ok=True)
    (d / "locks").mkdir(exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text(GITIGNORE)
    return d


def load_config(root: Path) -> dict:
    p = root / ".orch" / "scheduler" / "config.toml"
    cfg: dict = {}
    if p.is_file():
        try:
            cfg = tomllib.loads(p.read_text())
        except (tomllib.TOMLDecodeError, OSError):
            cfg = {}
    cfg.setdefault("agent", DEFAULT_AGENT)
    cfg["interval"] = int(cfg.get("interval", 60))
    cfg["inbox_every"] = int(cfg.get("inbox_every", 60))
    return cfg


def load_state(root: Path) -> dict:
    try:
        d = json.loads((root / ".orch" / "scheduler" / "state.json").read_text())
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
    """Per-ticket ext.scheduler.agent: a full command with {prompt}, or a name from [agents] in config."""
    want = ((ticket or {}).get("ext") or {}).get("scheduler", {}).get("agent")
    if want:
        if "{prompt}" in want:
            return want
        named = (cfg.get("agents") or {}).get(want)
        if named:
            return named
    return cfg["agent"]


def build_argv(template: str, prompt: str) -> list[str]:
    parts = shlex.split(template)
    if not any("{prompt}" in p for p in parts):
        parts.append("{prompt}")
    return [p.replace("{prompt}", prompt) for p in parts]


def _alive(pid: int) -> bool:
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
        with open(log_path, "a") as f:
            f.write(f"# start {fmt(now)} ticket {tid} ({reason})\n# command {shlex.join(argv[:1])} ...\n")
            f.flush()
            try:
                proc = subprocess.Popen(argv, cwd=self.root, stdout=f, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL)
            except OSError as e:
                f.write(f"# could not start: {e}\n# end {fmt(now)} exit 127\n")
                lock.unlink(missing_ok=True)
                self._record(tid, now, 127, log_path, None)
                orchcli.log(self.root, tid, f"Scheduler could not start the agent ({e.__class__.__name__})")
                return False
        lock.write_text(str(proc.pid))
        self.runs[tid] = Run(tid, proc, log_path, lock, now, reason)
        orchcli.log(self.root, tid, f"Scheduler started an agent run ({reason}). Log: {log_path.name}")
        return True

    def _record(self, tid: str, now: datetime, code: int, log_path: Path, next_run: str | None) -> None:
        st = load_state(self.root)
        e = st.setdefault(tid, {})
        e.update(last_run=fmt(now), last_exit=code, last_log=log_path.name)
        if next_run is not None:
            e["next_run"] = next_run
        save_state(self.root, st)

    def reap(self, now: datetime, wait: bool = False) -> list[str]:
        """Collect finished runs: log footer, history entry, state. wait=True blocks (tests, --once)."""
        done = []
        for tid, r in list(self.runs.items()):
            code = r.proc.wait() if wait else r.proc.poll()
            if code is None:
                continue
            with open(r.log_path, "a") as f:
                f.write(f"# end {fmt(now)} exit {code}\n")
            r.lock.unlink(missing_ok=True)
            st = load_state(self.root)
            e = st.setdefault(tid, {})
            e.update(last_exit=code, last_log=r.log_path.name, last_run=fmt(r.started))
            save_state(self.root, st)
            orchcli.log(self.root, tid, f"Scheduler run finished, exit code {code}")
            del self.runs[tid]
            done.append(tid)
        return done
