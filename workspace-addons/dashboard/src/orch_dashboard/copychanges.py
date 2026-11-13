"""Read-only "what did the copy change": the files a ticket's copy would add to the project (with +/- counts)
and one file's diff. Nothing is written; only `git diff` runs, with every config that could run a program
(external diff, text conversion, file-system monitor) switched off. A file is shown only if it is in the list."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

TID = re.compile(r"t_[a-z0-9]{6,16}")
MAX_FILES = 200
MAX_DIFF = 200_000
_GIT = ["git", "-c", "core.fsmonitor=false", "-c", "core.pager=cat", "-c", "core.quotepath=off"]
_FLAGS = ["--no-ext-diff", "--no-textconv", "--no-renames", "--no-color"]


def _git(root: Path, args: list[str]) -> bytes | None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    try:
        r = subprocess.run([*_GIT, *args], cwd=root, capture_output=True, timeout=10, env=env, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _top(root: Path) -> Path | None:
    out = _git(root, ["rev-parse", "--show-toplevel"])
    return Path(out.decode("utf-8", "replace").strip()) if out and out.strip() else None


def _plain(name: str) -> str:
    return "".join(c if c.isprintable() else "?" for c in name)[:300]


def listing(root: Path, ticket: str) -> dict:
    if not TID.fullmatch(ticket):
        return {"files": []}
    root = _top(root)
    if root is None:
        return {"files": []}
    out = _git(root, ["diff", "--numstat", "-z", *_FLAGS, f"HEAD...refs/heads/orch/{ticket}", "--"])
    if out is None:
        return {"files": []}
    files = []
    for rec in out.decode("utf-8", "replace").split("\0"):
        parts = rec.split("\t", 2)
        if len(parts) != 3 or not parts[2]:
            continue
        add, rem, path = parts
        files.append(
            {
                "path": _plain(path),
                "added": int(add) if add.isdigit() else None,  # None: a binary file
                "removed": int(rem) if rem.isdigit() else None,
            }
        )
    return {"files": files[:MAX_FILES], "more": max(0, len(files) - MAX_FILES)}


def diff(root: Path, ticket: str, path: str) -> tuple[int, dict]:
    known = [f["path"] for f in listing(root, ticket)["files"]]
    if path not in known:
        return 404, {"error": "That file is not in this copy."}
    top = _top(root)
    if top is None:
        return 404, {"error": "git could not read this copy."}
    out = _git(top, ["diff", *_FLAGS, f"HEAD...refs/heads/orch/{ticket}", "--", path])
    if out is None:
        return 404, {"error": "git could not read this copy."}
    text = out.decode("utf-8", "replace")
    cut = len(text) > MAX_DIFF
    return 200, {"path": path, "diff": text[:MAX_DIFF], "cut": cut}
