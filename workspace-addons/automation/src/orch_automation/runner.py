"""Scheduler files: .orch/addons/automation/state.json and runs.jsonl. Runs themselves are started by core (`orch run start`)."""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from pathlib import Path

from . import runfiles

GITIGNORE = "state.json\nruns.jsonl\nlisten.json\n"


def sdir(root: Path) -> Path:
    """.orch/addons/automation/ A symlink anywhere on that path is refused (a repo could aim
    it at files outside); files in it are written without following symlinks (runfiles.open_append, os.replace)."""
    d = root / ".orch" / "addons" / "automation"
    for p in (root / ".orch", root / ".orch" / "addons", d):
        if p.is_symlink():
            raise RuntimeError(
                f"{p} is a symbolic link; the scheduler does not use it. Remove it and try again."
            )
    d.mkdir(parents=True, exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists() and not gi.is_symlink():
        with runfiles.open_append(gi) as f:
            f.write(GITIGNORE)
    return d


def load_config(root: Path) -> dict:
    """The [automation] table of .orch/config.toml: interval, inbox_every. The agent is [workspace] agent (core)."""
    p = root / ".orch" / "config.toml"
    cfg: dict = {}
    if p.is_file():
        try:
            t = tomllib.loads(p.read_text()).get("automation")
            cfg = dict(t) if isinstance(t, dict) else {}
        except (tomllib.TOMLDecodeError, OSError):
            cfg = {}
    for k, d in (("interval", 60), ("inbox_every", 60)):
        try:
            cfg[k] = max(1, int(cfg.get(k, d)))
        except (TypeError, ValueError):
            cfg[k] = d
    return cfg


def load_state(root: Path) -> dict:
    try:
        d = json.loads((root / ".orch" / "addons" / "automation" / "state.json").read_text())
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


def history(root: Path, tid: str, at: str, took: int, code: int) -> None:
    """One line per finished run in runs.jsonl (the dashboard view reads it)."""
    with runfiles.open_append(sdir(root) / "runs.jsonl") as f:
        f.write(json.dumps({"ticket": tid, "at": at, "took": took, "exit": code}) + "\n")
