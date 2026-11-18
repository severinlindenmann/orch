"""The merge queue's settings in the workspace's `.orch/config.toml`, section `[pull_requests]`.

- `bases`: the base branches the queue merges into. Default `["develop"]`. `main` and `master` are never
  accepted, whatever the file says: a release into them is a person's Merge card.
- `login`: the GitHub login the queue merges with. When set, a pull request is queued only from that login and
  a runner signed in as anyone else does not run. When not set, each entry remembers the login that added it
  and only a runner with that same login merges it.
- `alone_paths`: a pull request that changes a file under one of these runs alone in its own queue group (never
  with others), so its green run is the proof before it counts. Default: CI (`.github/`) and the merge queue's
  own code in the orch repository.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_BASES = ("develop",)
NEVER = ("main", "master")
DEFAULT_ALONE = (
    ".github/",
    "workspace-addons/pull-requests/",
    "workspace/src/orch/prwait.py",
    "workspace/src/orch/ghlimit.py",
)


def _table(root: Path) -> dict:
    from orch import config

    try:
        t = config.read(root).get("pull_requests")
    except Exception:  # noqa: BLE001 - an unreadable file means the safe defaults
        return {}
    return t if isinstance(t, dict) else {}


def bases(root: Path) -> list[str]:
    got = _table(root).get("bases")
    if not isinstance(got, list) or not got or not all(isinstance(b, str) and b.strip() for b in got):
        got = list(DEFAULT_BASES)
    return [b.strip() for b in got if b.strip().lower() not in NEVER]


def login(root: Path) -> str | None:
    got = _table(root).get("login")
    return got.strip() if isinstance(got, str) and got.strip() else None


def same_login(a: str | None, b: str | None) -> bool:
    """GitHub logins do not care about case; an unknown login never matches."""
    return bool(a) and bool(b) and a.lower() == b.lower()


def alone_paths(root: Path) -> list[str]:
    got = _table(root).get("alone_paths")
    if not isinstance(got, list) or not all(isinstance(x, str) for x in got):
        return list(DEFAULT_ALONE)
    return [x.strip().lstrip("/") for x in got if x.strip()]
