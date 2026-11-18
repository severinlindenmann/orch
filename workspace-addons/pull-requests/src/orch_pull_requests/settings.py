"""The merge queue's settings in the workspace's `.orch/config.toml`, section `[pull_requests]`.

- `bases`: the base branches the queue merges into. Default `["develop"]`. `main` and `master` are never
  accepted, whatever the file says: a release into them is a person's Merge card.
- `login`: the GitHub login the queue merges with. When set, a pull request is queued only from that login and
  a runner signed in as anyone else does not run. When not set, each entry remembers the login that added it
  and only a runner with that same login merges it.
- `max_group`: how many pull requests go into one queue group at most. Default 5, from 1 to 20; any other value
  means the default. Read at the start of every round, so a change counts without restarting the runner.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_BASES = ("develop",)
NEVER = ("main", "master")
DEFAULT_MAX_GROUP, MOST_GROUP = 5, 20


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


def max_group(root: Path) -> int:
    got = _table(root).get("max_group")
    if isinstance(got, bool) or not isinstance(got, int) or not 1 <= got <= MOST_GROUP:
        return DEFAULT_MAX_GROUP
    return got
