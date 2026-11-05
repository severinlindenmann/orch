"""Calls to the orch CLI (`$ORCH_BIN`, else `orch`) with --json. The scheduler touches tickets only through it."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

BY = "agent:scheduler"
ID_RE = re.compile(r"^t_[a-z0-9]{6,16}$")


def call(root: Path, *args: str, by: bool = True):
    """Run `orch <args> --json`. Returns parsed JSON, or None on failure / no JSON."""
    cmd = [os.environ.get("ORCH_BIN") or "orch", *args, "--json"] + (["--by", BY] if by else [])
    try:
        p = subprocess.run(cmd, check=False, cwd=root, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except ValueError:
        return None


def log(root: Path, tid: str, text: str) -> None:
    call(root, "log", tid, text)


def tickets(root: Path) -> list[dict]:
    """`orch ticket list --json` (a list, or {"tickets": [...]}); only well-formed tickets."""
    data = call(root, "ticket", "list", by=False)
    items = data.get("tickets", []) if isinstance(data, dict) else data
    return [t for t in items if isinstance(t, dict) and isinstance(t.get("id"), str)
            and ID_RE.match(t["id"]) and t.get("status")] if isinstance(items, list) else []


def addon_on(root: Path, name: str) -> bool | None:
    """Is add-on `name` turned on here? None = could not find out."""
    data = call(root, "addon", "list", by=False)
    if not isinstance(data, list):
        return None
    for a in data:
        if isinstance(a, dict) and a.get("name") == name:
            return bool(a.get("active"))
    return False


def is_active(root: Path) -> bool | None:
    """Is this add-on turned on here? None = could not find out (keep running)."""
    return addon_on(root, "scheduler")


def set_ext(root: Path, t: dict, remove: tuple = (), **changes) -> bool:
    """Write ext.scheduler (merged with what is there); checked against the ticket revision when it has one."""
    cur = dict((t.get("ext") or {}).get("scheduler") or {})
    cur.update(changes)
    for k in remove:
        cur.pop(k, None)
    args = ["ext", "set", t["id"], "scheduler", json.dumps(cur)]
    if isinstance(t.get("revision"), int):
        args += ["--if-revision", str(t["revision"])]
    return call(root, *args) is not None


AGENT_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def run_start(root: Path, tid: str, text: str | None = None, agent: str | None = None) -> dict:
    """`orch run start <tid> --by agent:scheduler`: all of resume / fresh / busy is decided inside core.
    Returns {"result": "started", "run", "log"} | {"result": "pending"} (ticket busy, text queued)
    | {"result": "failed", "reason": plain words}."""
    cmd = [os.environ.get("ORCH_BIN") or "orch", "run", "start", tid, "--mode", "oneshot", "--json", "--by", BY]
    if agent and AGENT_RE.match(agent):  # only a name; core refuses one it does not know
        cmd += ["--agent", agent]
    if text:
        cmd += ["--text", text]
    try:
        p = subprocess.run(cmd, check=False, cwd=root, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"result": "failed", "reason": f"orch could not be run ({e.__class__.__name__})"}
    try:
        data = json.loads(p.stdout)
    except ValueError:
        data = None
    if p.returncode == 0 and isinstance(data, dict):
        return {"result": "started", "run": data.get("run"), "log": data.get("log")}
    if isinstance(data, dict) and data.get("pending") is True:
        return {"result": "pending"}
    reason = str(data.get("error")) if isinstance(data, dict) and data.get("error") else (p.stderr.strip() or "unknown")
    if "No agent found" in reason:
        reason = "No agent set: orch config set workspace.agent <name>"
    return {"result": "failed", "reason": reason[:300]}


def run_running(root: Path, tid: str) -> bool | None:
    """Is a run holding the ticket right now? None = could not find out."""
    data = call(root, "run", "status", tid, by=False)
    return bool(data.get("running")) if isinstance(data, dict) else None


def ticket(root: Path, tid: str) -> dict | None:
    return next((t for t in tickets(root) if t["id"] == tid), None)


def relay_since(root: Path, cursor: int, wait: int = 30):
    """`orch relay inbox --since <cursor> --wait N --json` (marks nothing seen). None on failure."""
    data = call(root, "relay", "inbox", "--since", str(cursor), "--wait", str(wait), by=False)
    return data if isinstance(data, dict) else None


def relay_ready(root: Path) -> bool:
    return (root / ".orch" / "secrets" / "relay.json").is_file() and bool(addon_on(root, "relay"))
