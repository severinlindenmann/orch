"""files_sig: one short fingerprint of "what the work folder looks like now", to tell whether files changed
since a check was recorded. Pure reading: it runs only fixed `git` argv lists (nothing taken from a
ticket) and
never runs, evaluates or shells out any stored command or output.

Design (git folders only; no git, a timeout or a size cap means None = no staleness is shown):
  sha256 over  "orch-files-sig-v1"
             + `git diff HEAD` of tracked files (the empty tree when there is no commit yet)
             + the sorted untracked, non-ignored files: name + content hash (size + mtime when above 1 MB).
Left out: `.orch/`, `.git`, node_modules, .venv, __pycache__, dist, build. mtimes of small files are not
used, so
touching a file without changing it does not count as a change."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

TIMEOUT = 3.0
MAX_DIFF = 16 * 1024 * 1024
MAX_UNTRACKED = 2000
HASH_LIMIT = 1024 * 1024
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
SKIP_DIRS = (".orch", "node_modules", ".venv", "__pycache__", "dist", "build")
_EXCLUDE = [f":(exclude,glob)**/{d}/**" for d in SKIP_DIRS]
_GIT = ["git", "-c", "core.fsmonitor=false", "-c", "core.quotepath=off"]
_CACHE: dict[str, tuple[float, str | None]] = {}
CACHE_TTL = 3.0


def _git(root: Path, args: list[str], deadline: float) -> bytes | None:
    left = deadline - time.monotonic()
    if left <= 0:
        return None
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        r = subprocess.run(  # fixed argv list, no shell
            _GIT + args, cwd=root, capture_output=True, timeout=left, env=env, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or len(r.stdout) > MAX_DIFF:
        return None
    return r.stdout


def files_sig(root: Path) -> str | None:
    """The fingerprint (64 hex characters) of the work folder under `root`, or None."""
    root = Path(root)
    deadline = time.monotonic() + TIMEOUT
    if _git(root, ["rev-parse", "--is-inside-work-tree"], deadline) is None:
        return None
    head = _git(root, ["rev-parse", "--verify", "-q", "HEAD"], deadline)
    base = head.decode().strip() if head else EMPTY_TREE
    diff = _git(
        root, ["diff", "--no-ext-diff", "--no-textconv", "--no-color", base, "--", ".", *_EXCLUDE], deadline
    )
    names = _git(root, ["ls-files", "--others", "--exclude-standard", "-z", "--", ".", *_EXCLUDE], deadline)
    if diff is None or names is None:
        return None
    files = sorted(n for n in names.split(b"\0") if n)
    if len(files) > MAX_UNTRACKED:
        return None
    h = hashlib.sha256(b"orch-files-sig-v1\0")
    h.update(diff)
    for raw in files:
        if time.monotonic() > deadline:
            return None
        rel = os.fsdecode(raw)
        h.update(b"\0U\0" + raw + b"\0")
        p = root / rel
        try:
            st = p.lstat()
            if p.is_symlink():
                h.update(b"L" + os.fsencode(os.readlink(p)))
            elif st.st_size <= HASH_LIMIT:
                h.update(b"F" + hashlib.sha256(p.read_bytes()).digest())
            else:
                h.update(f"B{st.st_size}:{st.st_mtime_ns}".encode())
        except OSError:
            h.update(b"?")
    return h.hexdigest()


def cached_sig(root: Path) -> str | None:
    """files_sig with a short cache, for pages that are polled."""
    key, t = str(root), time.monotonic()
    hit = _CACHE.get(key)
    if hit and t - hit[0] < CACHE_TTL:
        return hit[1]
    sig = files_sig(root)
    _CACHE[key] = (time.monotonic(), sig)
    return sig
