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


def is_active(root: Path) -> bool | None:
    """Is this add-on turned on here? None = could not find out (keep running)."""
    data = call(root, "addon", "list", by=False)
    if not isinstance(data, list):
        return None
    for a in data:
        if isinstance(a, dict) and a.get("name") == "scheduler":
            return bool(a.get("active"))
    return False


def set_ext(root: Path, t: dict, **changes) -> bool:
    """Write ext.scheduler (merged with what is there); checked against the ticket revision when it has one."""
    cur = dict((t.get("ext") or {}).get("scheduler") or {})
    cur.update(changes)
    args = ["ext", "set", t["id"], "scheduler", json.dumps(cur)]
    if isinstance(t.get("revision"), int):
        args += ["--if-revision", str(t["revision"])]
    return call(root, *args) is not None
