"""How many GitHub Actions jobs wait for a machine right now, and the day's peak (ORCH-454). No AI call.

The night of 17/18 Nov 2026: about 22 pull request runs restarted at once on top of eleven develop runs,
281 jobs waited for a machine, the 01:00 nightly started 7 hours late and the nightly e2e did not run. So orch
counts the waiting jobs before it starts CI work itself (a rerun, taking the base branch in) and holds that
work while LIMIT or more jobs wait; the Development expert reads the day's peak and says so on a ticket.

One count is a few GitHub reads (the queued and running runs, then the jobs of each run that are still
waiting for a machine), at most MAX_RUNS runs; the answer is kept CACHE_SECS for the whole computer, per
repository, in `ci-waiting.json` in the orch folder, with the highest count of each of the last DAYS days.
A read that fails gives None: it never blocks work and never counts as a peak.
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime

from orch.errors import Refused

LIMIT = 20  # this many jobs waiting for a machine or more: orch starts no CI work of its own
CACHE_SECS = 120
MAX_RUNS = 30  # runs whose jobs are read in one count (beyond that the count is a lower bound)
DAYS = 14
WAIT_SECS = 1800  # how long wait_room waits for room before it says so
POLL_SECS = 60
WAITING = ("queued", "waiting", "pending", "requested")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")


def _file():
    from orch import addons

    return addons.home() / "ci-waiting.json"


def _read() -> dict:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError, Refused):
        return {}
    return d if isinstance(d, dict) else {}


def _write(doc: dict) -> None:
    from orch import runs

    with contextlib.suppress(OSError, Refused):
        runs._atomic(_file(), json.dumps(doc, indent=1, sort_keys=True) + "\n")


def _gh_api(path: str) -> dict | None:
    """One read-only GitHub API call through gh; None when it failed."""
    from orch import ghmerge

    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        r = ghmerge._gh_plain(gh, ["api", path], 60)
    except Refused:
        return None
    if r.returncode != 0:
        return None
    try:
        d = json.loads(r.stdout or "null")
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def count(repo: str, api: Callable[[str], dict | None] = _gh_api) -> int | None:
    """Jobs of the repository waiting for a machine now (queued runs and the waiting jobs of running ones);
    None when GitHub could not be read."""
    if not REPO_RE.match(repo or ""):
        return None
    ids: list[int] = []
    for status in ("queued", "in_progress"):
        d = api(f"repos/{repo}/actions/runs?status={status}&per_page=100")
        if d is None:
            return None
        for r in d.get("workflow_runs") or []:
            if isinstance(r, dict) and isinstance(r.get("id"), int) and r["id"] not in ids:
                ids.append(r["id"])
    n = 0
    for rid in ids[:MAX_RUNS]:
        d = api(f"repos/{repo}/actions/runs/{rid}/jobs?filter=latest&per_page=100")
        if d is None:
            continue  # a run that ended meanwhile: its jobs wait no more
        n += sum(1 for j in d.get("jobs") or [] if isinstance(j, dict) and j.get("status") in WAITING)
    return n


def _day(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d")


def waiting(
    repo: str,
    *,
    fresh: bool = False,
    api: Callable[[str], dict | None] = _gh_api,
    clock: Callable[[], float] = time.time,
) -> int | None:
    """The count, from the shared answer when it is younger than CACHE_SECS (fresh=True reads GitHub anyway).
    Every count read from GitHub also raises the day's peak."""
    key = (repo or "").lower()
    now = clock()
    doc = _read()
    repos = doc.get("repos") if isinstance(doc.get("repos"), dict) else {}
    cur = repos.get(key) if isinstance(repos.get(key), dict) else {}
    last = cur.get("last") if isinstance(cur.get("last"), dict) else {}
    at, n = last.get("at"), last.get("n")
    if not fresh and isinstance(at, (int, float)) and isinstance(n, int) and 0 <= now - at < CACHE_SECS:
        return n
    got = count(repo, api)
    if got is None:
        return None
    peaks = cur.get("peaks") if isinstance(cur.get("peaks"), dict) else {}
    day = _day(now)
    old = peaks.get(day) if isinstance(peaks.get(day), dict) else {}
    if got > int(old.get("n") or 0) or not old:
        peaks[day] = {"n": got, "at": datetime.fromtimestamp(now, UTC).isoformat(timespec="seconds")}
    keep = sorted(peaks)[-DAYS:]
    repos[key] = {"last": {"at": now, "n": got}, "peaks": {d: peaks[d] for d in keep}}
    doc["repos"] = repos
    _write(doc)
    return got


def peaks(repo: str) -> dict[str, dict]:
    """{day (UTC): {"n": highest count, "at": when}} of the last DAYS days, as counted on this computer."""
    doc = _read()
    repos = doc.get("repos") if isinstance(doc.get("repos"), dict) else {}
    cur = repos.get((repo or "").lower())
    p = cur.get("peaks") if isinstance(cur, dict) else None
    return {d: v for d, v in (p or {}).items() if isinstance(v, dict) and isinstance(v.get("n"), int)}


def room(repo: str, **kw) -> tuple[bool, int | None]:
    """(True, n) when orch may start CI work now: fewer than LIMIT jobs wait, or the count could not be read
    (an unreadable count never blocks work)."""
    n = waiting(repo, **kw)
    return (n is None or n < LIMIT), n


def busy_line(n: int | None) -> str:
    return f"{n} jobs wait for a machine on GitHub (orch starts no CI work of its own from {LIMIT})"


def wait_room(
    repo: str,
    *,
    max_wait: int = WAIT_SECS,
    say: Callable[[str], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    **kw,
) -> tuple[bool, int | None]:
    """Wait until fewer than LIMIT jobs wait, at most max_wait seconds; (False, n) when there was no room."""
    start = clock()
    ok, n = room(repo, **kw)
    told = False
    while not ok and clock() - start < max_wait:
        if say and not told:
            say(busy_line(n) + "; waiting for room.")
            told = True
        sleep(POLL_SECS)
        ok, n = room(repo, **kw)
    return ok, n
