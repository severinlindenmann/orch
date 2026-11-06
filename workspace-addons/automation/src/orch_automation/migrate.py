"""The scheduler became automation. Moves what the old add-on left: ticket data, settings, its own files.
Safe to run again and again: whatever is already moved is left alone. Old data is kept (the old add-on name is
off, so core hides `ext.scheduler`)."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from . import orchcli

OLD_TABLE = re.compile(r"^\[scheduler\][ \t]*$", re.MULTILINE)


def tickets(root: Path) -> int:
    """Copy ext.scheduler to ext.automation (one write per ticket). A ticket that has ext.automation keeps it."""
    n = 0
    for t in orchcli.tickets(root):
        ext = t.get("ext") or {}
        old = ext.get("scheduler")
        if not isinstance(old, dict) or "automation" in ext:
            continue
        args = ["ext", "set", t["id"], "automation", json.dumps(old)]
        if isinstance(t.get("revision"), int):
            args += ["--if-revision", str(t["revision"])]
        if orchcli.call(root, *args) is not None:
            n += 1
    return n


def config(root: Path) -> bool:
    """[scheduler] -> [automation] in .orch/config.toml (only when there is no [automation] yet)."""
    p = root / ".orch" / "config.toml"
    if p.is_symlink() or not p.is_file():
        return False
    text = p.read_text()
    if not OLD_TABLE.search(text) or re.search(r"^\[automation\]", text, re.MULTILINE):
        return False
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".config-")  # private, never an existing file or link
    try:
        with os.fdopen(fd, "w") as f:
            f.write(OLD_TABLE.sub("[automation]", text, count=1))
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def files(root: Path) -> int:
    """.orch/addons/scheduler/{state.json,runs.jsonl} -> .orch/addons/automation/ (not over an existing file)."""
    old, new = root / ".orch" / "addons" / "scheduler", root / ".orch" / "addons" / "automation"
    if old.is_symlink() or new.is_symlink() or not old.is_dir():
        return 0
    new.mkdir(parents=True, exist_ok=True)
    n = 0
    for name in ("state.json", "runs.jsonl"):
        a, b = old / name, new / name
        if a.is_file() and not a.is_symlink() and not b.exists():
            os.replace(a, b)
            n += 1
    return n


def unsafe(root: Path) -> Path | None:
    """The first of .orch, .orch/addons, the old or the new folder that is a symbolic link (a repo could aim it outside)."""
    o = root / ".orch"
    for p in (o, o / "addons", o / "addons" / "scheduler", o / "addons" / "automation", o / "config.toml"):
        if p.is_symlink():
            return p
    return None


def run(root: Path) -> dict:
    bad = unsafe(root)
    if bad is not None:
        return {"tickets": 0, "config": False, "files": 0,
                "note": f"{bad} is a symbolic link; nothing was moved. Remove it and run: orch automation migrate"}
    return {"tickets": tickets(root), "config": config(root), "files": files(root)}
