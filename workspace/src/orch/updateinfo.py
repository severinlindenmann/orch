"""What the update page and `orch update` say about versions: the installed release, the newest one and a
short plain list of what changed. Best effort and read-only: a network or git problem gives "unknown",
never an error.

A release is a merge of a `release/part<N>` pull request: the number N is what a person reads ("orch 16").
The install records the number next to its commit (installed.json); the newest one is read from the install
source (GitHub API, or the git folder of a local source)."""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from orch import addons
from orch.services import _printable

RELEASE_MERGE = re.compile(r"^Merge pull request #\d+ from \S*?/?release/part(\d+)", re.MULTILINE)
PR_MERGE = re.compile(r"^Merge pull request #\d+ from \S+\n+(?P<title>[^\n]+)")
PREFIX = re.compile(r"^[A-Za-z][\w /-]{0,24}:\s+")
MAX_LINES = 5
CACHE_SECONDS = 600

_cache: dict = {"at": -1e9, "value": None}
_lock = threading.Lock()


def release_in(messages: list[str]) -> int | None:
    """The release number of the newest release merge in these commit messages (newest first)."""
    for m in messages:
        hit = RELEASE_MERGE.match(m or "")
        if hit:
            return int(hit[1])
    return None


def _plain(title: str) -> str:
    t = _printable(title).strip()
    t = PREFIX.sub("", t, count=1).strip().rstrip(".").strip()
    return (t[:1].upper() + t[1:])[:100]


def changes_from(messages: list[str]) -> list[str]:
    """Plain lines (newest first) from the merged pull requests in these commit messages (newest first):
    the first MAX_LINES titles, then 'and N more'. Release merges are not a change of their own."""
    titles = []
    for m in messages:
        hit = PR_MERGE.match(m or "")
        if not hit or RELEASE_MERGE.match(m):
            continue
        t = _plain(hit["title"])
        if t and t not in titles:
            titles.append(t)
    if len(titles) < MAX_LINES:  # the release titles are the release notes: they follow the pull requests
        for m in messages:
            hit = PR_MERGE.match(m or "")
            t = (
                _plain(re.sub(r"^Release \d+:\s*", "", hit["title"]))
                if hit and RELEASE_MERGE.match(m)
                else ""
            )
            if t and t not in titles:
                titles.append(t)
    out = titles[:MAX_LINES]
    if len(titles) > MAX_LINES:
        out.append(f"and {len(titles) - MAX_LINES} more")
    return out


def _local_messages(kind: str, a: str, b: str | None) -> list[str] | None:
    from orch import safegit

    folder = Path(addons.repo())
    # 'at' follows the main line (release merges); 'between' sees every merged pull request in the range
    args = ["log", *(["--first-parent"] if kind == "at" else []), "-n", "100" if kind == "at" else "250"]
    args.append("--format=%B%x00")
    args.append(a if kind == "at" else f"{a}..{b}")
    rc, out, _ = safegit.run(args, folder, 10, read_only=True, filters=True, root=folder)
    return [m.strip() for m in out.split("\x00") if m.strip()] if rc == 0 else None


def _github_messages(kind: str, a: str, b: str | None) -> list[str] | None:
    from urllib.parse import quote
    from urllib.request import Request, urlopen

    api = addons._github_api()
    if not api:
        return None
    if kind == "at":
        url = f"{api}/commits?sha={quote(a, safe='')}&per_page=100"
    else:
        url = f"{api}/compare/{a}...{b}"
    with urlopen(Request(url, headers={"Accept": "application/vnd.github+json"}), timeout=6) as r:  # noqa: S310
        data = json.load(r)
    rows = data if kind == "at" else data.get("commits")
    if not isinstance(rows, list):
        return None
    msgs = [
        r["commit"]["message"]
        for r in rows
        if isinstance(r, dict)
        and isinstance(r.get("commit"), dict)
        and isinstance(r["commit"].get("message"), str)
    ]
    return msgs if kind == "at" else msgs[::-1]  # the compare list is oldest first; ours is newest first


def _fetch_messages(kind: str, a: str, b: str | None = None) -> list[str] | None:
    """Commit messages, newest first. kind 'at': the history up to commit/ref `a`; 'between': a..b."""
    try:
        if addons._is_local(addons.repo()):
            return _local_messages(kind, a, b)
        return _github_messages(kind, a, b)
    except Exception:  # noqa: BLE001 - best effort: no network, rate limit, odd answer
        return None


def installed() -> dict:
    """{"sha", "release"} of this install (None for what is not recorded)."""
    try:
        d = json.loads((addons.home() / "installed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = None
    d = d if isinstance(d, dict) else {}
    rel = d.get("release")
    return {
        "sha": addons._sha_or_none(d.get("sha")),
        "release": rel if isinstance(rel, int) and not isinstance(rel, bool) and rel > 0 else None,
    }


def label(release: int | None, sha: str | None, ref: str) -> str:
    if release:
        return f"orch {release}"
    if sha:
        return f"orch {_printable(ref)} {sha[:8]}"
    return f"orch {addons._orch_version()}"


def current_label() -> str:
    """What `orch --version` and `orch status` print."""
    try:
        got = installed()
        return label(got["release"], got["sha"], addons.ref())
    except Exception:  # noqa: BLE001
        return f"orch {addons._orch_version()}"


def release_now(sha: str | None) -> int | None:
    """The release number the install source has at this commit (read from its history)."""
    if not sha:
        return None
    msgs = _fetch_messages("at", sha)
    return release_in(msgs) if msgs else None


def _compute() -> dict:
    ref = addons.ref()
    have = installed()
    newest_sha = addons._source_sha()
    out = {
        "installed": {**have, "label": label(have["release"], have["sha"], ref)},
        "newest": None,
        "update_available": False,
        "changes": [],
    }
    if not newest_sha:
        return out
    rel = release_now(newest_sha)
    out["newest"] = {"sha": newest_sha, "release": rel, "label": label(rel, newest_sha, ref)}
    if have["sha"] and have["sha"] != newest_sha:
        out["update_available"] = True
        msgs = _fetch_messages("between", have["sha"], newest_sha)
        out["changes"] = changes_from(msgs or [])
    elif not have["sha"]:
        out["update_available"] = None  # unknown: nothing recorded about the installed commit
    return out


def info(use_cache: bool = True) -> dict:
    """The installed and the newest version with what changed. Cached for 10 minutes (the page asks often)."""
    with _lock:
        if use_cache and time.monotonic() - _cache["at"] < CACHE_SECONDS and _cache["value"] is not None:
            return _cache["value"]
    value = {**_compute(), "checked_at": int(time.time())}
    with _lock:
        _cache.update(at=time.monotonic(), value=value)
    return value


def forget() -> None:
    with _lock:
        _cache.update(at=-1e9, value=None)


def after_update(
    old_sha: str | None, old_release: int | None, new_sha: str | None
) -> tuple[int | None, list[str]]:
    """After an update: the new release number and the lines to print under the update text
    ('Updated orch 15 → 16', then 'What changed:' and the list). Nothing when the commit did not change."""
    if not new_sha:
        return None, []
    if old_sha == new_sha:
        return old_release or release_now(new_sha), []
    new_release = release_now(new_sha)
    lines = []
    if old_release and new_release and old_release != new_release:
        lines.append(f"Updated orch {old_release} → {new_release}")
    elif new_release:
        lines.append(f"Updated orch to {new_release}")
    changes = changes_from(_fetch_messages("between", old_sha, new_sha) or []) if old_sha else []
    if changes:
        lines += ["What changed:", *[f"  - {c}" for c in changes]]
    return new_release, lines
