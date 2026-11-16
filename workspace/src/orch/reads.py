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

from orch import history, review, tickets
from orch.errors import Refused


class NotHere(LookupError):
    """This argv is not answered in-process: run the command."""


def ticket_rows(root: Path, status: str | None = None, all_: bool = False) -> list[dict]:
    """`orch ticket list` rows, before the JSON shaping: the visible tickets, sorted by status, with children
    counts and the quiet mark."""
    from orch.cli import visible

    everything = tickets.list_all(root)
    ts = [
        visible(root, t)
        for t in everything
        if (t["status"] == status if status else all_ or t["status"] not in ("done", "dropped"))
    ]
    ts.sort(key=lambda t: tuple(tickets.STATUS_WORDS).index(t["status"]))
    for t in ts:
        t["children"] = tickets.children_counts(everything, t["id"])
        if quiet := tickets.quiet_since(t):
            t["quiet_since"] = quiet
    return ts


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
    from orch.cli_review import answered

    return answered(root)


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
    if a == ["review", "list"]:
        return _plain(root, review_cards(root))
    if a == ["review", "list", "--answered"]:
        return _plain(root, review_answered(root))
    raise NotHere(" ".join(argv))
