"""Calls to the `orch` CLI (on PATH) with --json. The scheduler writes tickets only through it."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

BY = "agent:scheduler"


def call(root: Path, *args: str, by: bool = True):
    """Run `orch <args> --json`. Returns parsed JSON, or None on failure / no JSON."""
    cmd = ["orch", *args, "--json"] + (["--by", BY] if by else [])
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
