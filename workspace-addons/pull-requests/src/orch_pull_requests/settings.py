"""The merge queue's settings in the workspace's `.orch/config.toml`, section `[pull_requests]`.

- `bases`: the base branches the queue merges into. Default `["develop"]`. `main` and `master` are never
  accepted, whatever the file says: a release into them is a person's Merge card.
- `login`: the GitHub login the queue merges with. When set, a pull request is queued only from that login and
  a runner signed in as anyone else does not run. When not set, each entry remembers the login that added it
  and only a runner with that same login merges it.
- `alone_paths`: a pull request that changes a file under one of these runs alone in its own queue group (never
  with others), so its green run is the proof before it counts. Default: CI (`.github/`) and the merge queue's
  own code in the orch repository.
- `overlap`: while a group's checks run, the next group is built on top of it and checked at the same time; it
  merges only after the group before it merged (ORCH-432). Default true; `false` checks one group at a time.
- `max_group`: how many pull requests go into one queue group at most. Default 5, from 1 to 20; any other value
  means the default. Read at the start of every round, so a change counts without restarting the runner.
- `merge_alone`: true (default) = a pull request waiting alone whose own checks are green and whose files the
  base did not change is merged on its own checks, with no second run. false = it is checked in a queue group of
  its own on top of the base first, like every group: for a repository whose pull requests run only a light set of
  checks of their own and the full set runs on queue groups (orch development, ORCH-545).
- `group_check`: how a queue group is checked (ORCH-1124, localcheck.py). `github` (default) = GitHub's checks of
  the group pull request; `shadow` = the same, and the local check runs next to it so both verdicts can be compared;
  `local` = the local check on this computer decides and GitHub's group run is skipped. Anything else = `github`.
- `check_command`: the local check's command (a list of words, run in a clean copy of the group commit; `{base}` is
  the base commit). Default: DEFAULT_CHECK.
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
DEFAULT_MAX_GROUP, MOST_GROUP = 5, 20
GROUP_CHECKS = ("github", "shadow", "local")
DEFAULT_CHECK = ("python3", "scripts/ci_light.py", "--base", "{base}")


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


def overlap(root: Path) -> bool:
    return _table(root).get("overlap") is not False


def merge_alone(root: Path) -> bool:
    got = _table(root).get("merge_alone")
    return got if isinstance(got, bool) else True


def max_group(root: Path) -> int:
    got = _table(root).get("max_group")
    if isinstance(got, bool) or not isinstance(got, int) or not 1 <= got <= MOST_GROUP:
        return DEFAULT_MAX_GROUP
    return got


def group_check(root: Path) -> str:
    got = _table(root).get("group_check")
    got = got.strip().lower() if isinstance(got, str) else ""
    return got if got in GROUP_CHECKS else "github"


def check_command(root: Path) -> list[str]:
    got = _table(root).get("check_command")
    if isinstance(got, list) and got and all(isinstance(x, str) and x.strip() for x in got):
        return [x.strip() for x in got]
    return list(DEFAULT_CHECK)


def precheck(root: Path) -> str | None:
    got = _table(root).get("precheck")
    return got.strip() if isinstance(got, str) and got.strip() else None
