"""Parked tickets (ORCH-2431): the ONE rule for "this ticket asks nothing of the person now".

A ticket is parked while it sits in Backlog, or while it waits on a time that has not come, on another
ticket that is not finished, or on something outside (`orch ticket wait --until <time>`, `--on ticket:<key>`,
`--on external:<what>`). A parked ticket gives no row in `orch needs`, on Home or Review and is not in the
Needs you number. Nothing is lost: its questions and rows are kept on the ticket and show again as soon as
the wait ends, a person brings it back (`orch ticket wait <key> --clear`) or it moves to To do; `orch needs
--parked` and Home list what is parked, with the reason.

Not parked: a wait on a question (that is the row), a helper that could not start (`start`), a wait on a pull
request, and a wait whose time has passed or whose ticket is finished (the wait ended: the rows are back).

Pure over ticket dicts and index rows (status + waiting_on); nothing is stored.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

KINDS = ("time", "ticket", "external")  # the waits that park a ticket
ENDED = ("review", "done", "dropped")  # the other ticket is finished: the wait on it ended (as tend wakes it)
BACKLOG = "backlog"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def lookup(rows: Iterable[dict]) -> Callable[[str], str | None]:
    """ref (ticket id or key, any case) -> that ticket's status, over these tickets or index rows."""
    by: dict[str, str | None] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        for k in (r.get("id"), r.get("key")):
            if isinstance(k, str) and k:
                by[k.casefold()] = r.get("status")
    return lambda ref: by.get(str(ref).strip().casefold())


def why(ticket: dict, now: str | None = None, status_of: Callable[[str], str | None] | None = None):
    """{kind: backlog|time|ticket|external, ref?, until?} while the ticket is parked, else None.
    now: UTC "YYYY-MM-DDTHH:MM:SSZ"; status_of: see `lookup` (without it a wait on a ticket counts as still
    on)."""
    if not isinstance(ticket, dict) or ticket.get("general") is True:
        return None
    status = ticket.get("status")
    if status == "open":
        return {"kind": BACKLOG}
    w = ticket.get("waiting_on")
    if status != "waiting" or not isinstance(w, dict) or w.get("kind") not in KINDS:
        return None
    if w.get("start") is True:  # its helper could not start: that needs the person
        return None
    until = w.get("until")
    if isinstance(until, str) and until < (now or _now()):
        return None  # the time has come
    if w["kind"] == "ticket" and status_of is not None and status_of(w.get("ref") or "") in ENDED:
        return None  # the ticket it waited on is finished
    out = {"kind": w["kind"]}
    if isinstance(w.get("ref"), str) and w["ref"].strip():
        out["ref"] = w["ref"].strip()
    if isinstance(until, str):
        out["until"] = until
    return out


def reason(p: dict) -> str:
    """The reason in plain words, one line (R7.1)."""
    if p["kind"] == BACKLOG:
        return "In Backlog"
    ref = p.get("ref")
    if p["kind"] == "time":
        from orch.net import when

        return f"Until {when(p['until'])}" + (f": {ref}" if ref else "")
    if p["kind"] == "ticket":
        return f"Until {ref} is finished"
    return f"Until you bring it back: {ref}" if ref else "Until you bring it back"


def ids(root: Path, now: str | None = None) -> set[str]:
    """The ids of every parked ticket, from the ticket index (no ticket file is read)."""
    from orch import ticketindex

    rows = ticketindex.rows(root)
    status_of, now = lookup(rows), now or _now()
    return {r["id"] for r in rows if why(r, now, status_of)}


def without(tickets: list[dict], now: str | None = None) -> list[dict]:
    """These tickets minus the parked ones (a wait on a ticket is looked up among them)."""
    status_of, now = lookup(tickets), now or _now()
    return [t for t in tickets if not why(t, now, status_of)]


def back_cli(key: str, p: dict) -> str:
    """The one line that brings a parked ticket back."""
    return f"orch ticket status {key} ready" if p["kind"] == BACKLOG else f"orch ticket wait {key} --clear"


def rows(root: Path, now: str | None = None) -> list[dict]:
    """What is parked, so nothing is lost: [{ticket, key, title, kind, reason, questions, cli, ref?, until?}],
    the one that comes back first on top. A ticket in Backlog is listed only when it holds something back
    (an open question or finished work to bring back): Backlog itself is the list of the rest."""
    from orch import ticketindex

    index = ticketindex.rows(root)
    status_of, now = lookup(index), now or _now()
    out = []
    for r in index:
        p = why(r, now, status_of)
        if not p or (p["kind"] == BACKLOG and not (r.get("questions_open") or r.get("bring_back"))):
            continue
        key = r.get("key") or r["id"]
        out.append(
            {
                **p,
                "ticket": r["id"],
                "key": key,
                "title": " ".join(str(r.get("title") or key).split())[:200] or key,
                "reason": reason(p),
                "questions": int(r.get("questions_open") or 0),
                "cli": back_cli(key, p),
            }
        )
    out.sort(key=lambda x: (x.get("until") or "9999", x["key"]))
    return out
