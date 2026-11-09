"""files_sig: one short fingerprint of "what the work folder looks like now", to tell whether files changed
since a check was recorded. Pure reading. Two rules keep it safe in a repo someone else prepared:

- git only LISTS files (`ls-files`, `rev-parse`): it never compares or filters content, so no clean/smudge
  filter, textconv or diff driver from the repo's config or attributes can run. Every call is a fixed
  argv list
  (nothing taken from a ticket), no shell, GIT_* environment removed, hooks/fsmonitor/untracked cache off.
- orch hashes the working-tree bytes itself through `saferead` (no links followed, no FIFO read, bounded).

Design (git folders only; no git, a timeout, a cap or an error means None = no staleness is shown):
  sha256 over a version tag and, for every file git lists (tracked, and untracked but not ignored), sorted by
  path: the path + exec bit + content hash (size + mtime above 1 MB; a link: its target; other types: type).
  The index (staged or not, committed or not) does not count, only what is in the folder now: `git add` or
  `git commit` alone is not a change. Left out: `.orch/`, `.git`, node_modules, .venv, __pycache__, dist,
  build.
  File hashes are cached by (path, size, mtime_ns, ino)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

from orch import saferead

TIMEOUT = 3.0
MAX_LIST = 16 * 1024 * 1024
MAX_FILES = 5000
MAX_READ = 64 * 1024 * 1024
HASH_LIMIT = 1024 * 1024
SKIP_DIRS = (".orch", "node_modules", ".venv", "__pycache__", "dist", "build")
_EXCLUDE = [f":(exclude,glob)**/{d}/**" for d in SKIP_DIRS]
_GIT = [
    "git",
    "--no-pager",
    "--no-optional-locks",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.untrackedCache=false",
    "-c",
    "core.quotepath=off",
]
_HASHES: dict[tuple, str] = {}
_CACHE: dict[str, tuple[float, str | None]] = {}
CACHE_TTL = 10.0


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
    if r.returncode != 0 or len(r.stdout) > MAX_LIST:
        return None
    return r.stdout


def _listed(root: Path, deadline: float) -> list[bytes] | None:
    """Every tracked and untracked-not-ignored path under root, as git lists them (names only)."""
    if _git(root, ["rev-parse", "--is-inside-work-tree"], deadline) is None:
        return None
    tracked = _git(root, ["ls-files", "-z", "--stage", "--", ".", *_EXCLUDE], deadline)
    others = _git(root, ["ls-files", "-z", "--others", "--exclude-standard", "--", ".", *_EXCLUDE], deadline)
    if tracked is None or others is None:
        return None
    names = set()
    for rec in tracked.split(b"\0"):
        if rec:  # "<mode> <blob sha> <stage>\t<path>": only the path is used, the content is hashed by orch
            _, _, path = rec.partition(b"\t")
            if path:
                names.add(path)
    names.update(n for n in others.split(b"\0") if n)
    return sorted(names)


def _state(root: Path, rel: str, budget: list[int]) -> str:
    full = root / rel
    try:
        st = os.lstat(full)
    except OSError:
        return "?"
    key = (str(full), st.st_size, st.st_mtime_ns, st.st_ino)
    hit = _HASHES.get(key)
    if hit is not None:
        return hit
    state = saferead.file_state(full, HASH_LIMIT, budget)
    if "?" not in state:
        if len(_HASHES) > 50_000:
            _HASHES.clear()
        _HASHES[key] = state
    return state


def files_sig(root: Path) -> str | None:
    """The fingerprint (64 hex characters) of the work folder under `root`, or None."""
    root = Path(root)
    deadline = time.monotonic() + TIMEOUT
    names = _listed(root, deadline)
    if names is None or len(names) > MAX_FILES:
        return None
    budget = [MAX_READ]
    h = hashlib.sha256(b"orch-files-sig-v2\0")
    for raw in names:
        if time.monotonic() > deadline:
            return None
        state = _state(root, os.fsdecode(raw), budget)
        if budget[0] < 0:
            return None
        h.update(raw + b"\0" + state.encode("utf-8", "replace") + b"\0")
    return h.hexdigest()


def cached_sig(root: Path) -> str | None:
    """files_sig with a cache of a few seconds, for pages that are polled."""
    key, t = str(root), time.monotonic()
    hit = _CACHE.get(key)
    if hit and t - hit[0] < CACHE_TTL:
        return hit[1]
    sig = files_sig(root)
    _CACHE[key] = (time.monotonic(), sig)
    return sig
