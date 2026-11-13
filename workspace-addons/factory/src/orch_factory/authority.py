"""Start authority comes only from recorded questions, frozen bytes and human answers."""

import json
import re

from . import orchcli
from .render import render
from .store import Refused, Store, digest

FOLDERS = {
    "factory:start": ("proposals", "p", "run"),
    "factory:autopilot": ("proposals", "p", "autopilot"),
    "factory:change": ("changes", "c", "change"),
    "factory:stop": ("stops", "s", "stop"),
}


def expected(order, kind, rel, h, data):
    """(text, options, action) Factory must have asked for this frozen file; anything else has no authority."""
    folder, prefix, file_kind = FOLDERS[kind]
    m = re.fullmatch(rf"{folder}/{re.escape(order)}/{prefix}([1-9][0-9]*)\.json", rel)
    if not m or data.get("kind") != file_kind:
        raise Refused("A Factory question does not match its frozen file.", "tampered")
    text, options = render(kind, data, int(m[1]))
    action = {"order": order, "file": rel, "hash": h}
    if kind == "factory:autopilot":
        action["days"] = data["limits"]["days"]
    elif kind == "factory:stop":
        action["stage"] = data["stage"]
    return text, options, action


def human(q):
    return q.get("answer") is not None and str(q.get("answered_by") or "").startswith("human:")


def entries(store, ticket):
    """Every valid Factory question with its journal row, frozen data and file number."""
    rows = [r for r in store.journal_read() if r["order"] == ticket["id"]]
    superseded = {r.get("q") for r in rows if r["type"] == "superseded"}
    asked = {r["q"]: r for r in rows if r["type"] == "asked"}
    present = {q["id"] for q in ticket.get("questions", [])}
    if set(asked) - superseded - present:
        raise Refused("A recorded Factory question is missing.", "tampered")
    result = []
    for q in ticket.get("questions", []):
        row = asked.get(q["id"])
        if not row or q["id"] in superseded:
            continue
        if q.get("kind") != row.get("kind") or row.get("kind") not in FOLDERS:
            raise Refused("A Factory question no longer matches its journal.", "tampered")
        try:
            raw = store.read(row["file"])
            matches = digest(raw) == row["hash"]
        except FileNotFoundError:
            matches = False
        if not matches:
            raise Refused("The frozen Factory file has changed or is missing.", "tampered")
        data = json.loads(raw)
        text, options, action = expected(ticket["id"], row["kind"], row["file"], row["hash"], data)
        if q.get("action") != action:
            raise Refused("A Factory question no longer matches its journal.", "tampered")
        if q.get("text") != text or list(q.get("options") or []) != options:
            raise Refused("A Factory question's text does not match its frozen file.", "tampered")
        result.append(
            {"q": q, "row": row, "data": data, "n": int(re.search(r"(\d+)\.json$", row["file"])[1])}
        )
    return result


def questions(store, ticket):
    return [e["q"] for e in entries(store, ticket)]


def from_ticket(store, ticket):
    return any(
        q.get("kind") == "factory:start"
        and q.get("answer") == "Start"
        and str(q.get("answered_by") or "").startswith("human:")
        for q in questions(store, ticket)
    )


def started(order, root=None):
    import os
    from pathlib import Path

    root = Path(root or os.environ.get("ORCH_ROOT", "."))
    return from_ticket(Store(root), orchcli.ticket(root, order))
