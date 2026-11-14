"""The last syncs, for the Sync page ("Last 5 syncs"): this machine's run/sync/history.json, never synced.
One entry per step: when, whether it worked, and one plain line (what changed, or why it did not finish).
Only display text; nothing here is read for a decision, so an unreadable or edited file just shows less."""

import json

from . import paths, repo

FILE = "run/sync/history.json"
KEEP = 20
SHOWN = 5


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _what(root, before, after):
    """'2 tickets, 1 file' for what changed between two commits, 'nothing new' when nothing did."""
    if not after or before == after:
        return "nothing new"
    if before:
        raw = repo.git(root, "diff", "--name-only", "-z", before, after).stdout
    else:
        raw = repo.git(root, "ls-tree", "-r", "--name-only", "-z", after).stdout
    names = [n.decode("utf-8", "replace") for n in raw.split(b"\0") if n]
    tickets = sum(1 for n in names if paths.TICKET.fullmatch(n))
    files = sum(1 for n in names if paths.ARTIFACT.fullmatch(n))
    parts = ([_plural(tickets, "ticket")] if tickets else []) + ([_plural(files, "file")] if files else [])
    return ", ".join(parts) or "nothing new"


def _why(error):
    if error == "offline":
        return "could not reach your storage"
    if str(error).startswith("Sync stopped:") or "paused" in str(error).lower():
        return "stopped, something needs you"
    return "did not finish"


def record(root, now, before, after, error):
    """Add this step's entry. Never raises: the history is only a convenience."""
    from .step import encoded, write

    try:
        text = _why(error) if error else _what(root, before, after)
        entries = read(root, all_=True)
        entries.append({"at": str(now), "ok": not error, "text": text})
        write(root, FILE, encoded({"entries": entries[-KEEP:]}))
    except Exception:  # noqa: BLE001, S110 - the history is a convenience: never breaks a sync
        return


def read(root, all_=False):
    """[{at, ok, text}] newest first (the last SHOWN unless all_, then oldest first); [] when unreadable."""
    try:
        data = json.loads(repo.safe(root, FILE).read_text())
        rows = [
            {"at": str(e["at"])[:40], "ok": e["ok"] is True, "text": str(e["text"])[:120]}
            for e in data["entries"]
            if isinstance(e, dict) and "at" in e and "ok" in e and "text" in e
        ]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []
    return rows if all_ else rows[::-1][:SHOWN]
