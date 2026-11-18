"""The JSON answers of a few read-only commands, made inside the caller's own process (ORCH-102).

The dashboard builds its state from `orch ticket list --all --json`, `orch run status <ids> --json` and
`orch review list [--answered] --json`, and answers a click with `orch ticket show <id> --json`. Each was a
new Python process; with helpers running and the machine busy one build took seconds and a click waited for
it. The dashboard server runs in the core's own interpreter, so it asks here instead. The answer is the same
JSON the command prints (the CLI calls the same functions); argv this module does not know raises NotHere and
the caller starts the command as before."""

from __future__ import annotations

import json
from pathlib import Path

from orch import history, review, ticketindex, tickets
from orch.errors import Refused


class NotHere(LookupError):
    """This argv is not answered in-process: run the command."""


def ticket_rows(root: Path, status: str | None = None, all_: bool = False) -> list[dict]:
    """`orch ticket list` rows, before the JSON shaping: the visible tickets, sorted by status, with children
    counts and the quiet mark."""
    from orch.cli import visible

    everything = ticketindex.rows(root)  # which tickets and their children: the index, not every file
    kids = ticketindex.children_counts(everything)
    ts = []
    for r in _picked(everything, status, all_):
        try:
            t = tickets.load(root, r["id"])  # only the listed tickets are read in full
        except (Refused, OSError):
            continue  # changed into something unlistable meanwhile: a listing never stalls on a bad file
        if tickets.is_hidden(t) or t.get("status") not in tickets.STATUS_WORDS:
            continue
        t = visible(root, t)
        t["children"] = dict(kids.get(t["id"]) or ticketindex.no_children())
        if quiet := tickets.quiet_since(t):
            t["quiet_since"] = quiet
        ts.append(t)
    ts.sort(key=lambda t: tuple(tickets.STATUS_WORDS).index(t["status"]))
    return ts


def _picked(everything: list[dict], status: str | None, all_: bool) -> list[dict]:
    return [
        r
        for r in everything
        if r.get("status") in tickets.STATUS_WORDS
        and (r["status"] == status if status else all_ or r["status"] not in ("done", "dropped"))
    ]


def index_list(root: Path, status: str | None = None, all_: bool = False) -> tuple[list[dict], list[dict]]:
    """(the listed rows, every row) for the text `orch ticket list`: index rows only, no ticket file read.
    Each listed row gets children and quiet_since like ticket_rows."""
    everything = ticketindex.rows(root)
    kids = ticketindex.children_counts(everything)
    ts = _picked(everything, status, all_)
    ts.sort(key=lambda r: tuple(tickets.STATUS_WORDS).index(r["status"]))
    for r in ts:
        r["children"] = dict(kids.get(r["id"]) or ticketindex.no_children())
        stamps = {"status": r["status"], "updated_at": r.get("updated_at"), "created_at": r.get("created_at")}
        if r.get("last_at"):
            stamps["history"] = [{"at": r["last_at"]}]
        if quiet := tickets.quiet_since(stamps):
            r["quiet_since"] = quiet
    return ts, everything


def run_status(root: Path, ids: list[str]) -> dict:
    """`orch run status <id> <id> ... --json` for several tickets: {"runs": {id: answer}}; a ticket that
    cannot be read gets {"ticket", "error"} and does not spoil the others."""
    from orch.cli_run import status_of

    out: dict[str, dict] = {}
    for tid in dict.fromkeys(ids):
        try:
            out[tid] = status_of(root, tid)[0]
        except Refused as e:
            out[tid] = {"ticket": tid, "error": str(e)}
    return {"runs": out}


def review_cards(root: Path) -> dict:
    return {"workspace": root.name, "cards": review.stack(root)}


def review_answered(root: Path) -> list[dict]:
    from orch.cli_review import _answered

    return _answered(root)


def _plain(root: Path, data):
    """As the command prints it with --json: tickets shown as provable here, then through JSON (a copy that
    shares nothing with the core's own objects)."""
    return json.loads(json.dumps(history.shown_json(root, data), ensure_ascii=False))


def answer(root: Path, argv: list[str]):
    """The parsed JSON `orch <argv>` would print. Refused when the command would refuse (exit 2), NotHere when
    this argv is not one of the reads above."""
    a = list(argv)
    if not a or a[-1] != "--json":
        raise NotHere(" ".join(a))
    a = a[:-1]
    if a == ["ticket", "list", "--all"]:
        return _plain(root, ticket_rows(root, all_=True))
    if a == ["ticket", "list"]:
        return _plain(root, ticket_rows(root))
    if a[:2] == ["ticket", "show"] and len(a) == 3 and tickets._ID_RE.fullmatch(a[2]):
        from orch.cli import visible

        return _plain(root, visible(root, tickets.load(root, a[2])))
    if a[:2] == ["run", "status"] and len(a) > 2 and all(tickets._ID_RE.fullmatch(x) for x in a[2:]):
        ids = a[2:]
        if len(ids) == 1:  # the one-ticket answer is the ticket's own row
            from orch.cli_run import status_of

            return _plain(root, status_of(root, ids[0])[0])
        return _plain(root, run_status(root, ids))
    if (
        a[:2] == ["run", "screen"]
        and len(a) > 5
        and a[-2] == "--lines"
        and a[-1].isdigit()
        and all(tickets._ID_RE.fullmatch(x) for x in a[2:-2])
    ):  # several sessions' last lines (one tmux call); one ticket keeps the command's own answer
        from orch import runwatch

        return {"screens": runwatch.tails(root, a[2:-2], int(a[-1]))}
    if a == ["review", "list"]:
        return _plain(root, review_cards(root))
    if a == ["review", "list", "--answered"]:
        return _plain(root, review_answered(root))
    raise NotHere(" ".join(argv))
