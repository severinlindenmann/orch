"""The merge queue file of one workspace: `.orch/addons/pull-requests/queue.json`.

Entries keep their order. States: waiting (in line), running (in the group being checked), merged, out (left
the queue; `why` says why). Every change reads, changes and writes the file under a short lock folder, so the
runner and a helper adding a pull request never lose each other's change.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


class Refused(Exception):
    """A plain-words refusal for the person or helper."""


PR_URL = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/([0-9]{1,9})")
WAITING, RUNNING, MERGED, OUT = "waiting", "running", "merged", "out"
FINISHED = (MERGED, OUT)
LOCK_SECS = 10.0
KEEP_FINISHED = 50  # finished entries kept for `queue list`; older ones are dropped


def folder(root: Path) -> Path:
    return root / ".orch" / "addons" / "pull-requests"


def _file(root: Path) -> Path:
    return folder(root) / "queue.json"


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_url(url: str) -> tuple[str, int]:
    m = PR_URL.fullmatch((url or "").strip())
    if m is None:
        raise Refused(
            f"'{url}' is not a GitHub pull request address (https://github.com/owner/name/pull/12)."
        )
    return m[1], int(m[2])


def read(root: Path, strict: bool = False) -> list[dict]:
    """The entries. No file yet: none. A file that cannot be read now (Windows: being replaced) is read again a
    few times; strict (inside change) refuses a damaged file instead of starting over with an empty queue."""
    for i in range(20):
        try:
            text = _file(root).read_text(encoding="utf-8")
            break
        except FileNotFoundError:
            return []
        except OSError:
            if i == 19:
                raise Refused(
                    "The merge queue file cannot be read right now. Try again in a minute."
                ) from None
            time.sleep(0.05)
    try:
        data = json.loads(text)
    except ValueError:
        if strict:
            raise Refused(
                f"The merge queue file is damaged: {_file(root)}. Move it away to start over."
            ) from None
        return []
    rows = data.get("entries") if isinstance(data, dict) else None
    return [r for r in rows or [] if isinstance(r, dict) and isinstance(r.get("url"), str)]


def _write(root: Path, rows: list[dict]) -> None:
    done = [r for r in rows if r.get("state") in FINISHED]
    drop = {id(r) for r in done[:-KEEP_FINISHED]} if len(done) > KEEP_FINISHED else set()
    rows = [r for r in rows if id(r) not in drop]
    d = folder(root)
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".queue-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"entries": rows}, f, indent=1)
    from orch import procs

    procs.replace(tmp, _file(root))


STALE_SECS = 30.0  # the queue lock is held for milliseconds: one this old without a living owner is stale


def take_lock(lock: Path, stale_after: float | None) -> bool:
    """Make the lock folder; True when ours. A lock whose owner is verifiably gone (or, with stale_after, one
    with no owner file older than that) is moved aside first, by one atomic rename: only one taker wins."""
    from orch import procs

    try:
        lock.mkdir()
    except FileExistsError:
        try:
            holder = (lock / "owner").read_text(encoding="utf-8")
        except OSError:
            holder = ""
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            return False
        dead = procs.owner_dead(holder) if holder else stale_after is not None and age > stale_after
        if not dead:
            return False
        aside = lock.with_name(f"{lock.name}.stale-{os.getpid()}-{time.monotonic_ns()}")
        try:
            lock.rename(aside)
        except OSError:
            return False  # someone else moved it first
        try:
            moved = (aside / "owner").read_text(encoding="utf-8")
        except OSError:
            moved = ""
        if moved != holder:  # a new owner took it between our look and the rename: give it back
            if not lock.exists():
                with contextlib.suppress(OSError):
                    aside.rename(lock)
            return False
        _drop_lock(aside)
        try:
            lock.mkdir()
        except FileExistsError:
            return False
    (lock / "owner").write_text(procs.own_token(), encoding="utf-8")
    return True


@contextmanager
def locked(root: Path):
    """Hold the queue's short lock while reading and writing the file."""
    d = folder(root)
    d.mkdir(parents=True, exist_ok=True)
    lock = d / "queue.lock"
    end = time.monotonic() + LOCK_SECS
    while not take_lock(lock, STALE_SECS):
        if time.monotonic() > end:
            raise Refused("The merge queue file stays locked. Try again in a minute.")
        time.sleep(0.05)
    try:
        yield
    finally:
        _drop_lock(lock)


def _drop_lock(lock: Path) -> None:
    try:
        (lock / "owner").unlink()
    except OSError:
        pass
    try:
        lock.rmdir()
    except OSError:
        pass


def change(root: Path, fn):
    """Run fn(rows) under the lock; it changes rows in place and may return a value."""
    with locked(root):
        rows = read(root, strict=True)
        out = fn(rows)
        _write(root, rows)
        return out


def find(rows: list[dict], url: str) -> dict | None:
    """The newest entry for this pull request."""
    return next((r for r in reversed(rows) if r.get("url") == url), None)


def add(root: Path, url: str, ticket: str | None, by: str) -> tuple[dict, bool]:
    """Put a pull request at the end of the line. Already waiting or running: that entry, not a second one."""
    repo, number = parse_url(url)
    url = f"https://github.com/{repo}/pull/{number}"

    def go(rows):
        old = find(rows, url)
        if old and old.get("state") not in FINISHED:
            if ticket and not old.get("ticket"):
                old["ticket"] = ticket
            return dict(old), False
        row = {"url": url, "repo": repo, "number": number, "ticket": ticket, "by": by, "added": now()}
        row.update(state=WAITING, why="waiting in line")
        rows.append(row)
        return dict(row), True

    return change(root, go)


def remove(root: Path, url: str, by: str) -> bool:
    repo, number = parse_url(url)
    url = f"https://github.com/{repo}/pull/{number}"

    def go(rows):
        old = find(rows, url)
        if old is None or old.get("state") in FINISHED:
            return False
        if old.get("state") == RUNNING:
            raise Refused(
                f"{url} is in the group being checked now; it cannot leave the queue until that ends."
            )
        old.update(state=OUT, why=f"taken out by {by}", ended=now())
        return True

    return change(root, go)


def set_state(root: Path, url: str, state: str, why: str, **extra) -> dict | None:
    """Change the newest entry of url that is not finished. Returns a copy of it, or None."""

    def go(rows):
        row = find(rows, url)
        if row is None or row.get("state") in FINISHED:
            return None
        row.update(state=state, why=why, **extra)
        if state in FINISHED:
            row["ended"] = now()
        return dict(row)

    return change(root, go)


def back_to_front(root: Path, urls: list[str], why: str, not_before: float | None = None) -> None:
    """Running entries that did not finish go back to waiting, ahead of the others (they waited longest).
    not_before: a unix time before which the runner does not take them again."""

    def go(rows):
        moved = [r for r in rows if r.get("url") in urls and r.get("state") == RUNNING]
        for r in moved:
            rows.remove(r)
            r.update(state=WAITING, why=why)
            r.pop("group", None)
            if not_before:
                r["not_before"] = not_before
            else:
                r.pop("not_before", None)
        first = next((i for i, r in enumerate(rows) if r.get("state") not in FINISHED), len(rows))
        rows[first:first] = moved

    change(root, go)


def claim(root: Path, batch: list[dict]) -> list[dict]:
    """Mark the batch running in one step; an entry taken out or added again meanwhile is left out."""

    def go(rows):
        got = []
        for b in batch:
            row = find(rows, b["url"])
            if row is None or row.get("state") != WAITING or row.get("added") != b.get("added"):
                continue
            row.update(state=RUNNING, why="in the group being checked")
            row.pop("not_before", None)
            got.append(b)
        return got

    return change(root, go)


def waiting(root: Path) -> list[dict]:
    return [r for r in read(root) if r.get("state") == WAITING]
