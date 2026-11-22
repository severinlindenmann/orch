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

RELEASE_MERGE = re.compile(
    r"^Merge pull request #\d+ from \S*?/?release/part(\d+)(?:\.(\d+))?", re.MULTILINE
)  # part33 = release 33, part33.1 = its first fix release (ORCH-552)
VERSION_RE = re.compile(r"[1-9][0-9]{0,5}(?:\.[1-9][0-9]{0,3})?")
PR_MERGE = re.compile(r"^Merge pull request #\d+ from \S+\n+(?P<title>[^\n]+)")
PREFIX = re.compile(r"^[A-Za-z][\w /()-]{0,24}:\s+")
# issue and ticket numbers ("#1393", "ORCH-411"), with a "closes" or "fixes" before them
REFS = re.compile(
    r"(?:\b(?i:closes|fixes|fixed|resolves|refs?|see)\s+)?(?:\b[A-Z][A-Z0-9]{1,9}-\d+\b|#\d+\b)"
)
MAX_LINES = 5
CACHE_SECONDS = 600

_cache: dict = {"at": -1e9, "value": None}
_lock = threading.Lock()


def version(n: int, fix: int | None = None) -> int | str:
    """A release as a person reads it: 33, or "33.1" for the first fix release of 33."""
    return f"{n}.{fix}" if fix else n


def as_version(v, stored: bool = False) -> int | str | None:
    """33, "33" or "33.1" as a release value (33 or "33.1"); anything else None. stored: as written to a
    file, where a plain release is a number and only a fix release is text ("9" there is no release)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v if 0 < v < 10**6 else None
    if isinstance(v, str) and VERSION_RE.fullmatch(v) and not (stored and "." not in v):
        n, _, fix = v.partition(".")
        return version(int(n), int(fix) if fix else None)
    return None


def vkey(v) -> tuple[int, int]:
    """Order of releases: 33 < 33.1 < 33.2 < 34. Unknown values sort first."""
    v = as_version(v)
    if v is None:
        return (0, 0)
    n, _, fix = str(v).partition(".")
    return (int(n), int(fix or 0))


def release_in(messages: list[str]) -> int | str | None:
    """The release of the newest release merge in these commit messages (newest first): 33 or "33.1"."""
    for m in messages:
        hit = RELEASE_MERGE.match(m or "")
        if hit:
            return version(int(hit[1]), int(hit[2]) if hit[2] else None)
    return None


def _plain(title: str) -> str:
    """A pull request title as a line for people: no type prefix, no issue or ticket numbers ("#1393",
    "(ORCH-411)"); empty when nothing but numbers is left (report r-1118-0907: Home showed "#1393, #1381")."""
    t = _printable(title).strip()
    t = PREFIX.sub("", t, count=1).strip()
    t = REFS.sub("", t)
    t = re.sub(r"\(\s*[,;/]?\s*\)|\[\s*\]", "", t)
    t = re.sub(r"\s+([,.;:)])", r"\1", re.sub(r"\s{2,}", " ", t)).strip(" ,;:/-–—").rstrip(".").strip()
    if not re.search(r"[A-Za-z]{2}", t):
        return ""
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
                _plain(re.sub(r"^Release \d+(?:\.\d+)?:\s*", "", hit["title"]))
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

    folder = addons.file_repo(addons.repo()) or Path(addons.repo())
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
        if addons._is_local(addons.repo()) or addons.file_repo(addons.repo()) is not None:
            return _local_messages(kind, a, b)
        return _github_messages(kind, a, b)
    except Exception:  # noqa: BLE001 - best effort: no network, rate limit, odd answer
        return None


RELEASE_BRANCH = re.compile(r"^release/part(\d+)(?:\.(\d+))?(?:-|$)")


def _github_release_line() -> list[tuple[int | str, str]] | None:
    from urllib.request import Request, urlopen

    api = addons._github_api()
    if not api:
        return None
    url = f"{api}/pulls?state=closed&base={addons.RELEASE_REF}&sort=updated&direction=desc&per_page=100"
    with urlopen(Request(url, headers={"Accept": "application/vnd.github+json"}), timeout=8) as r:  # noqa: S310
        rows = json.load(r)
    if not isinstance(rows, list):
        return None
    out = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("merged_at"):
            continue
        head = row.get("head") if isinstance(row.get("head"), dict) else {}
        hit = RELEASE_BRANCH.match(head.get("ref") or "")
        sha = addons._sha_or_none(row.get("merge_commit_sha"))
        if hit and sha:
            out.append((version(int(hit[1]), int(hit[2]) if hit[2] else None), sha))
    return out


def _git_release_line(folder: Path) -> list[tuple[int | str, str]] | None:
    from orch import safegit

    args = ["log", "--first-parent", "-n", "400", "--format=%H%x01%B%x00", addons.RELEASE_REF]
    rc, out, _ = safegit.run(args, folder, 10, read_only=True, filters=True, root=folder)
    if rc != 0:
        return None
    line = []
    for chunk in out.split("\x00"):
        sha, _, msg = chunk.strip().partition("\x01")
        hit = RELEASE_MERGE.match(msg)
        if hit and addons._sha_or_none(sha):
            line.append((version(int(hit[1]), int(hit[2]) if hit[2] else None), sha.strip()))
    return line


def release_line() -> list[tuple[int | str, str]] | None:
    """The releases of the install source's release branch as (release, merge commit), newest first (33.1
    after 33), one entry per release; None when they cannot be read (no network, unknown host)."""
    try:
        r = addons.repo()
        if addons.file_repo(r) is not None:
            got = _git_release_line(addons.file_repo(r))
        elif addons._is_local(r):
            got = _git_release_line(Path(r))
        else:
            got = _github_release_line()
    except Exception:  # noqa: BLE001 - best effort: no network, rate limit, odd answer
        return None
    if got is None:
        return None
    seen: dict = {}
    for n, sha in got:
        seen.setdefault(n, sha)  # the newest merge of a number wins (a release merged twice)
    return sorted(seen.items(), key=lambda x: vkey(x[0]), reverse=True)


def installed() -> dict:
    """{"sha", "release"} of this install (None for what is not recorded)."""
    try:
        d = json.loads((addons.home() / "installed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = None
    d = d if isinstance(d, dict) else {}
    return {"sha": addons._sha_or_none(d.get("sha")), "release": as_version(d.get("release"), stored=True)}


def label(release: int | str | None, sha: str | None, ref: str) -> str:
    if release:
        return f"orch {release}"
    if sha:
        return f"orch {_printable(ref)} {sha[:8]}"
    return f"orch {addons._orch_version()}"


def current_label() -> str:
    """What `orch --version` and `orch status` print."""
    try:
        got = installed()
        text = label(got["release"], got["sha"], addons.ref())
    except Exception:  # noqa: BLE001
        text = f"orch {addons._orch_version()}"
    return text + build_words()


def build_words() -> str:
    """' (development build)' when this orch is not a release, so nobody mistakes one for the other."""
    try:
        return "" if addons.build() == "release" else " (development build)"
    except Exception:  # noqa: BLE001
        return ""


def release_now(sha: str | None) -> int | str | None:
    """The release the install source has at this commit (read from its history): 33 or "33.1"."""
    if not sha:
        return None
    msgs = _fetch_messages("at", sha)
    return release_in(msgs) if msgs else None


def _compute_held(held: dict, have: dict) -> dict:
    """Held at a release it went back to: an update is offered only once a release newer than the one left
    is out (that update leaves the hold and takes the release branch again)."""
    out = {
        "installed": {**have, "label": label(have["release"] or held["release"], have["sha"], "main")},
        "newest": None,
        "update_available": False,
        "changes": [],
        "held": {"release": held["release"], "left": held["left"]},
    }
    line = release_line()
    if not line:
        return out
    n, sha = line[0]
    out["newest"] = {"sha": sha, "release": n, "label": label(n, sha, "main")}
    if vkey(n) > vkey(held["left"]):
        out["update_available"] = True
        if have["sha"]:
            out["changes"] = changes_from(_fetch_messages("between", have["sha"], sha) or [])
    return out


def _commit_at(ref: str, at: int) -> str | None:
    """The commit `ref` pointed at, at time `at` (Unix seconds), from the GitHub API; None when unknown."""
    from urllib.parse import quote
    from urllib.request import Request, urlopen

    api = addons._github_api()
    if not api:
        return None
    until = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))
    url = f"{api}/commits?sha={quote(ref, safe='')}&until={until}&per_page=1"
    try:
        with urlopen(Request(url, headers={"Accept": "application/vnd.github+json"}), timeout=6) as r:  # noqa: S310
            rows = json.load(r)
    except Exception:  # noqa: BLE001 - best effort: still no answer, try again next time
        return None
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return addons._sha_or_none(rows[0].get("sha"))
    return None


def resolve_pending() -> None:
    """An update GitHub did not answer recorded only the ref and time it installed: look up that commit and
    its release number now, and save them (orch then shows the right release again)."""
    try:
        d = json.loads((addons.home() / "installed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(d, dict):
        return
    p = d.get("pending")
    if addons._sha_or_none(d.get("sha")) or not isinstance(p, dict):
        return
    ref, at = p.get("ref"), p.get("at")
    if not isinstance(ref, str) or not isinstance(at, int) or isinstance(at, bool):
        return
    sha = _commit_at(ref, at)
    msgs = _fetch_messages("at", sha) if sha else None
    if msgs is not None:  # both answered; else keep `pending` and try again next time
        addons._save_installed(sha, release_in(msgs))


def _compute() -> dict:
    resolve_pending()
    ref = addons.ref()
    have = installed()
    held = addons.pinned()
    if held:
        return _compute_held(held, have)
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


def _ticket_lines(root, messages: list[str] | None, heading: str) -> list[str]:
    """'<heading>' and one line per ticket of this workspace whose pull request these commits merged."""
    from orch import released

    got = released.tickets_arrived(root, messages or [])
    return [heading, *[f"  - {t}" for t in got]] if got else []


def after_update(
    old_sha: str | None, old_release: int | str | None, new_sha: str | None, root=None
) -> tuple[int | str | None, list[str]]:
    """After an update: the new release number and the lines to print under the update text
    ('Updated orch 15 → 16', then 'What changed:' and the list, then the tickets of this workspace that
    arrived). Nothing when the commit did not change."""
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
    msgs = _fetch_messages("between", old_sha, new_sha) if old_sha else None
    changes = changes_from(msgs or [])
    if changes:
        lines += ["What changed:", *[f"  - {c}" for c in changes]]
    lines += _ticket_lines(root, msgs, "Tickets that arrived:")
    return new_release, lines


def announce_lines(root=None) -> list[str]:
    """What `orch update` says before it waits for the click: 'Updating orch 15 → orch 16', what changed and
    the tickets of this workspace that come with it. Nothing when it is up to date or unknown (best effort,
    never an error)."""
    try:
        data = info()
        if data.get("update_available") is not True:
            return []
        lines = [f"Updating {data['installed']['label']} → {data['newest']['label']}"]
        if data.get("changes"):
            lines += ["What changed:", *[f"  - {c}" for c in data["changes"]]]
        if root is not None:
            msgs = _fetch_messages("between", data["installed"]["sha"], data["newest"]["sha"])
            lines += _ticket_lines(root, msgs, "Tickets that come with it:")
        return lines
    except Exception:  # noqa: BLE001
        return []
