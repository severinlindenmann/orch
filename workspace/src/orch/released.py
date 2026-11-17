"""Is a ticket's merged change in the orch installed on this computer? (ORCH-87)

A finished ticket that links pull requests of the repository orch installs from gets one plain line:
'In release 30 (installed here)', 'In release 31, not installed here yet' or 'Merged, not released yet'.
It is worked out from each pull request's merge commit and the installed commit (installed.json): the
GitHub API for a GitHub source, git for a local folder source. Best effort and read-only: no network, a
rate limit or an odd answer gives no line, never an error. Answers are kept in memory (a 'contained' answer
never changes for the same installed commit; the others are asked again after a while).

The same pull request numbers name the tickets that arrived with an update ('orch update' release notes)."""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from orch import addons, updateinfo

PR_URL = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d{1,7})(?:[/?#]|$)", re.IGNORECASE)
MERGE_NUM = re.compile(r"^Merge pull request #(\d{1,7}) from ")
SQUASH_NUM = re.compile(r"\(#(\d{1,7})\)\s*$")  # a squash merge: 'Title (#123)' on the first line
GH_REMOTE = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", re.IGNORECASE)
FINISHED = ("review", "done")
RECHECK_SECONDS = 600
ERROR_SECONDS = 60
MAX_TICKETS_LISTED = 10

_cache: dict = {}
_lock = threading.Lock()


def _cached(key, compute, keep):
    """compute() once per key; keep(value) says for how long (None = forever)."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and (hit[1] is None or now < hit[1]):
            return hit[0]
    value = compute()
    secs = keep(value)
    with _lock:
        _cache[key] = (value, None if secs is None else now + secs)
    return value


def forget() -> None:
    with _lock:
        _cache.clear()


def _local() -> bool:
    return addons._is_local(addons.repo())


def _git(args: list[str]) -> tuple[int, str]:
    from orch import safegit

    folder = Path(addons.repo())
    rc, out, _ = safegit.run(args, folder, 10, read_only=True, filters=True, root=folder)
    return rc, out


def source_repo() -> str | None:
    """'owner/name' (lower case) of the GitHub repository orch installs from, None when unknown."""
    try:
        if _local():
            rc, out = _git(["config", "--get", "remote.origin.url"])
            m = GH_REMOTE.search(out.strip()) if rc == 0 else None
        else:
            m = re.fullmatch(r"https://github\.com/([^/]+)/([^/]+)", addons.repo().removesuffix(".git"))
        return f"{m[1]}/{m[2]}".lower() if m else None
    except Exception:  # noqa: BLE001 - best effort
        return None


def ticket_prs(ticket: dict, repo: str | None) -> list[int]:
    """The pull request numbers of `repo` this ticket links (references and step evidence), sorted."""
    if not repo or not isinstance(ticket, dict):
        return []
    urls = []
    for r in ticket.get("refs") or []:
        if isinstance(r, dict):
            urls += [r.get("url"), r.get("ref")]
    for c in ticket.get("checklist") or []:
        for ev in (c.get("evidence") or []) if isinstance(c, dict) else []:
            if isinstance(ev, dict):
                urls.append(ev.get("ref"))
    out = set()
    for u in urls:
        m = PR_URL.match(u) if isinstance(u, str) else None
        if m and f"{m[1]}/{m[2]}".lower() == repo:
            out.add(int(m[3]))
    return sorted(out)


def prs_in(messages: list[str]) -> set[int]:
    """Pull request numbers these commits merged ('Merge pull request #N from', or a squash 'Title (#N)')."""
    out = set()
    for msg in messages or []:
        first = (msg or "").strip().split("\n", 1)[0]
        m = MERGE_NUM.match(first) or SQUASH_NUM.search(first)
        if m:
            out.add(int(m[1]))
    return out


def _github(path: str) -> dict | None:
    from urllib.request import Request, urlopen

    api = addons._github_api()
    if not api:
        return None
    with urlopen(Request(f"{api}/{path}", headers={"Accept": "application/vnd.github+json"}), timeout=6) as r:  # noqa: S310
        data = json.load(r)
    return data if isinstance(data, dict) else None


def _merge_commit(n: int) -> dict | None:
    """{"merged": bool, "sha": str | None} of pull request n; None when it could not be read."""
    try:
        if _local():
            rc, out = _git(
                ["log", "--all", "-E", f"--grep=^Merge pull request #{n} from ", "-n", "1", "--format=%H"]
            )
            if rc != 0:
                return None
            sha = addons._sha_or_none(out.strip())
            return {"merged": bool(sha), "sha": sha}
        d = _github(f"pulls/{n}")
        if d is None:
            return None
        return {"merged": d.get("merged") is True, "sha": addons._sha_or_none(d.get("merge_commit_sha"))}
    except Exception:  # noqa: BLE001 - best effort: network, rate limit, odd answer
        return None


def merge_commit(n: int) -> dict | None:
    return _cached(
        ("pr", addons.repo(), n),
        lambda: _merge_commit(n),
        lambda v: ERROR_SECONDS if v is None else None if v["merged"] else RECHECK_SECONDS,
    )


def _contains(sha: str, head: str) -> bool | None:
    try:
        if sha == head:
            return True
        if _local():
            rc, _ = _git(["merge-base", "--is-ancestor", sha, head])
            return True if rc == 0 else False if rc == 1 else None
        d = _github(f"compare/{sha}...{head}")
        status = (d or {}).get("status")
        return (
            True if status in ("ahead", "identical") else False if status in ("behind", "diverged") else None
        )
    except Exception:  # noqa: BLE001
        return None


def contains(sha: str, head: str) -> bool | None:
    """Is commit `sha` part of commit `head`'s history? None when unknown."""
    return _cached(
        ("in", addons.repo(), sha, head),
        lambda: _contains(sha, head),
        lambda v: ERROR_SECONDS if v is None else None if v else RECHECK_SECONDS,
    )


def _all_in(shas: list[str], head: str | None) -> bool | None:
    if not head:
        return None
    got = [contains(s, head) for s in shas]
    return None if None in got else all(got)


def ticket_release(ticket: dict) -> dict | None:
    """{"state": "installed" | "released" | "merged", "release": N | None, "text": "<plain line>"} for a
    finished ticket whose pull requests (of the repository orch installs from) are merged; None otherwise or
    when it is unknown."""
    try:
        if not isinstance(ticket, dict) or ticket.get("status") not in FINISHED:
            return None
        prs = ticket_prs(ticket, source_repo())
        have = updateinfo.installed()
        if not prs or not have["sha"]:
            return None
        commits = [merge_commit(n) for n in prs]
        shas = [c["sha"] for c in commits if c and c["merged"] and c["sha"]]
        if not shas:
            return None
        here = _all_in(shas, have["sha"])
        if here is None:
            return None
        if here:
            rel = have["release"]
            text = f"In release {rel} (installed here)" if rel else "In the version installed here"
            return {"state": "installed", "release": rel, "text": text}
        newest = (updateinfo.info() or {}).get("newest") or {}
        if newest.get("sha") and _all_in(shas, newest["sha"]):
            rel = newest.get("release")
            text = f"In release {rel}, not installed here yet" if rel else "Merged, not installed here yet"
            return {"state": "released", "release": rel, "text": text}
        return {"state": "merged", "release": None, "text": "Merged, not released yet"}
    except Exception:  # noqa: BLE001 - a line on a page: never an error
        return None


def tickets_arrived(root: Path | None, messages: list[str]) -> list[str]:
    """Lines 'ORCH-36 Suggest button': the tickets here whose pull requests these commits merged."""
    if root is None:
        return []
    try:
        merged = prs_in(messages)
        repo = source_repo()
        if not merged or not repo:
            return []
        from orch import tickets
        from orch.services import _printable

        def order(t):  # by key number: tickets made in the same second keep their order
            m = re.search(r"(\d+)$", str(t.get("key") or ""))
            return (int(m[1]) if m else 1 << 30, str(t.get("created_at") or ""))

        out = []
        for t in sorted(tickets.list_all(root), key=order):
            if set(ticket_prs(t, repo)) & merged:
                title = _printable(str(t.get("title") or "")).strip()[:80]
                out.append(f"{t.get('key') or t.get('id')} {title}".strip())
        if len(out) > MAX_TICKETS_LISTED:
            out = out[:MAX_TICKETS_LISTED] + [f"and {len(out) - MAX_TICKETS_LISTED} more"]
        return out
    except Exception:  # noqa: BLE001
        return []
