"""Start authority comes only from recorded questions, frozen bytes and human answers."""

import json

from . import orchcli
from .render import START_OPTIONS, question_text
from .store import Refused, Store, digest


def questions(store, ticket):
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
        action = q.get("action") or {}
        if (
            q.get("kind") != row.get("kind")
            or action.get("order") != ticket["id"]
            or any(action.get(k) != row.get(k) for k in ("file", "hash"))
        ):
            raise Refused("A Factory question no longer matches its journal.", "tampered")
        try:
            matches = digest(store.read(row["file"])) == row["hash"]
        except FileNotFoundError:
            matches = False
        if not matches:
            raise Refused("The frozen Factory proposal has changed or is missing.", "tampered")
        if q.get("kind") == "factory:start" and not _rendered_by_factory(store, row, q):
            raise Refused("A Factory question's text does not match its frozen proposal.", "tampered")
        result.append(q)
    return result


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


def _rendered_by_factory(store, row, q):
    """The owner saw exactly what Factory renders from the frozen file: same text, same options."""
    try:
        n = int(row["file"].rsplit("/p", 1)[1].removesuffix(".json"))
        text = question_text(json.loads(store.read(row["file"])), n)
    except (ValueError, KeyError, IndexError, UnicodeError):
        return False
    return q.get("text") == text and list(q.get("options") or []) == list(START_OPTIONS)
