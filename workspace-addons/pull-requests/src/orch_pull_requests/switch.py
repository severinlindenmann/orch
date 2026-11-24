"""Merge when green: the per-ticket switch (`ext.pull-requests.merge_when_green`). No AI call.

`tend` is one pass over the tickets (the background service runs it every minute, `orch pull-requests tend` once):

- switch on: each open pull request of the ticket that is ready (not a draft) and that the queue admits
  (runner.admit: an allowed base branch, never main by default; no changes requested; the login it merges with) goes into the merge queue. The
  queue runner merges it only on green checks of the checked commit (orch.prwait), every GitHub write through
  this computer's write limit (orch.ghlimit). Never a pull request a person merges with a Merge card on any
  ticket; never a draft (the runner checks both again before it merges).
- switch off: a pull request this switch put in line and still waiting leaves the queue (one being checked
  right now finishes its round).

- helper stopped (ORCH-433, off unless `[pull_requests] queue_when_helper_stops = true`): a ticket without the
  switch whose helper is not working on it (none, or idle at its prompt), with no open question, not in Backlog
  and not finished, has each pull request the ticket records as "ready to merge" (checks passed, not a draft)
  put in the queue the same way. The helper left it open; nobody had to press Merge. Only the recorded status
  is read first, so drafts and red pull requests cost no GitHub call.

What it put in line is remembered per commit in `switch.json`, so a pull request that left the queue (checks
failed, a conflict, no room in the write limit) is not put back every minute: a new commit puts it back at once;
the same commit only after RETRY_SECS, while none of its checks failed, at most TRIES times. Turning the switch
off and on again starts over.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from pathlib import Path

from . import store
from .store import FINISHED, WAITING, Refused

ADDON = "pull-requests"
FIELD = "merge_when_green"
ON = "on"
BY = "agent:merge-when-green"
BY_STOPPED = "agent:helper-stopped"
SETTING_STOPPED = "queue_when_helper_stops"
READY = "ready to merge"  # the ticket's recorded status of a pull request whose checks passed (prstate.py)
NOT_STOPPED = ("open", "done", "dropped")  # open = Backlog: nobody planned work there yet
RETRY_SECS = 600
TRIES = 3
GONE = "GitHub did not show it"
SOON = "it left the merge queue a moment ago at this commit; tried again later"
QUIET = (GONE, SOON, "a draft")  # passing or expected: not said on the ticket


def is_on(ticket: dict) -> bool:
    ext = (ticket.get("ext") or {}).get(ADDON) if isinstance(ticket, dict) else None
    return isinstance(ext, dict) and ext.get(FIELD) == ON


def stopped_is_on(root: Path) -> bool:
    """The workspace switch for pull requests a helper left open. Off unless the file says true."""
    from orch import config

    return config.file_switch(root, "pull_requests", SETTING_STOPPED, False) is True


def set_stopped(root: Path, on: bool) -> bool:
    from orch import config

    config.set_key(root, "pull_requests", SETTING_STOPPED, bool(on))
    return bool(on)


def _ready_refs(ticket: dict) -> list[str]:
    """The ticket's pull requests recorded as ready to merge (checks passed, not a draft)."""
    return [
        r["url"]
        for r in ticket.get("refs") or []
        if isinstance(r, dict) and isinstance(r.get("url"), str) and r.get("status") == READY
    ]


def _helper_stopped(root: Path, ticket: dict) -> bool:
    """No helper works on the ticket (none, or idle at its prompt) and nothing waits for a person on it."""
    from orch import stuck

    if ticket.get("status") in NOT_STOPPED or ticket.get("general") is True or ticket.get("manager") is True:
        return False
    if any(isinstance(q, dict) and q.get("answer") is None for q in ticket.get("questions") or []):
        return False  # it asked a person: that answer decides
    try:
        return stuck._helper(root, ticket)[0] != "busy"
    except Exception:  # noqa: BLE001 - an unreadable run record: leave the pull request alone
        return False


def _seen_file(root: Path) -> Path:
    return store.folder(root) / "switch.json"


def _read_seen(root: Path) -> dict:
    try:
        data = json.loads(_seen_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _write_seen(root: Path, seen: dict) -> None:
    d = store.folder(root)
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".switch-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=1)
    from orch import procs

    procs.replace(tmp, _seen_file(root))


def _newest_rows(rows: list[dict]) -> dict[str, dict]:
    from .runner import pr_key

    out: dict[str, dict] = {}
    for r in rows:  # in file order: the last one per pull request wins
        k = pr_key(r.get("url") or "")
        if k:
            out[k] = r
    return out


def tend(root: Path, gh, clock=time.time, log=print, start=None) -> dict:
    """One pass; start(root) starts the queue runner when something was put in line. Returns {"added": [url],
    "removed": [url], "skipped": [(url, why)]}. Refused when the tickets cannot be read (nothing is queued)."""
    from orch import stuck, tickets

    from .runner import _release_fix, admit, merge_cards, pr_key

    try:
        all_tickets = tickets.list_all(root)
    except Exception as e:  # noqa: BLE001 - unreadable tickets: fail closed, queue nothing
        raise Refused(
            f"The tickets could not be read ({e.__class__.__name__}); nothing was queued."
        ) from None
    cards = merge_cards(root)
    if cards is None:
        raise Refused("The tickets could not be read; nothing was queued.")
    seen, now = _read_seen(root), clock()
    queue = _newest_rows(store.read(root))
    out: dict = {"added": [], "removed": [], "skipped": []}
    keep: set[str] = set()
    stopped_on = stopped_is_on(root)
    for t in all_tickets:
        on = is_on(t)
        ready = set(_ready_refs(t)) if not on and stopped_on else set()
        auto = bool(ready) and _helper_stopped(root, t)
        for url in stuck.open_pulls(t):
            k = pr_key(url)
            if not k:
                continue
            row = queue.get(k)
            if auto and url in ready:
                pass  # the helper stopped and left it open: put in line like the switch does
            elif not on:
                if (
                    row
                    and row.get("state") == WAITING
                    and row.get("by") == BY
                    and row.get("ticket") == t["id"]
                ):
                    with contextlib.suppress(Refused):  # it started its round meanwhile: that round ends it
                        if store.remove(root, row["url"], BY):
                            out["removed"].append(row["url"])
                            log(
                                f"Merge when green is off on {t.get('key') or t['id']}: {row['url']} left the queue."
                            )
                continue
            keep.add(k)
            if k in cards:
                _skip(root, out, seen, t, on, url, k, log, f"a person merges it with the Merge card on {cards[k]}")
                continue
            if row and row.get("state") not in FINISHED:
                continue  # in line or being checked
            prev = seen.get(k) or {}
            v = gh.pr(url)
            if v is None:
                why = GONE
            else:
                why = _why_not(v, prev, now)
                if why == "draft":
                    seen.pop(k, None)  # a draft that becomes ready later is put in line then
                    why = "a draft"
                elif why is None and prev.get("head") == v["headRefOid"] and gh.own_checks_failed(url):
                    why = "a check of this commit failed: push a fix"
            if why:
                _skip(root, out, seen, t, on, url, k, log, why)
                continue
            try:  # the queue's own check: allowed base branch, no changes requested, the merging login
                got = admit(root, gh, url)
            except Refused as e:
                _skip(root, out, seen, t, on, url, k, log, str(e))
                continue
            head = v["headRefOid"]
            tries = prev.get("tries", 0) + 1 if prev.get("head") == head else 1
            by = BY if on else BY_STOPPED
            fix = _release_fix(root, t["id"])  # a release keeper's red-run fix goes first (ORCH-1023)
            # linked on two tickets: queued once
            queue[k], _ = store.add(root, url, t["id"], by, first=fix, **got)
            seen[k] = {"head": head, "tries": tries, "at": now, "ticket": t["id"]}
            out["added"].append(url)
            if on:
                log(f"Merge when green on {t.get('key') or t['id']}: {url} is in the merge queue.")
            else:
                log(
                    f"The helper of {t.get('key') or t['id']} stopped with {url} ready: it is in the merge queue."
                )
    _write_seen(root, {k: v for k, v in seen.items() if k in keep})
    if out["added"] and start is not None:
        start(root)
    return out


def _skip(root: Path, out: dict, seen: dict, t: dict, on: bool, url: str, k: str, log, why: str) -> None:
    out["skipped"].append((url, why))
    if on and why not in QUIET and (seen.get(k) or {}).get("said") != why:
        _say(root, t, url, why, log)  # once per reason (#2785): else the person thinks it is queued
        seen[k] = {**(seen.get(k) or {}), "said": why}


def _say(root: Path, t: dict, url: str, why: str, log) -> None:
    """A switched-on pull request that is not put in line: its ticket's history and the watcher's log say why."""
    from orch import tickets

    text = f"Merge when green did not put {url} in the merge queue: {why.rstrip('.')}."
    log(f"{t.get('key') or t['id']}: {text}")
    with contextlib.suppress(Exception):  # a locked ticket: the log line still says it, the next pass tries again
        tickets.note_history(root, t["id"], BY, text)


def _why_not(v: dict, prev: dict, now: float) -> str | None:
    """Why this pull request does not go in line now, or None. "draft" is told apart (it resets the memory)."""
    if v.get("state") != "OPEN":
        return "not open"
    if v.get("isDraft") is not False:
        return "draft"
    if not prev or prev.get("head") != v["headRefOid"]:
        return None  # new, or a new commit
    if prev.get("tries", 0) >= TRIES:
        return (
            f"it left the merge queue {TRIES} times at this commit: push again, or turn the switch off and on"
        )
    if now - float(prev.get("at") or 0) < RETRY_SECS:
        return SOON
    return None
