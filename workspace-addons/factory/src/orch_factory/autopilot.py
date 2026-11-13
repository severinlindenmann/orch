"""Autopilot: a grant exists only from a person's Start; decide works only inside it, at read time too."""

import json
from datetime import datetime, timedelta

from . import authority, commands, orchcli
from .render import clean
from .store import Refused, Store, clock, validate

ALWAYS = "Only routine and taste stop items inside a valid grant can be decided by Factory."


answered_at = authority.answered_at


def grants_of(store, ticket):
    result = []
    for e in authority.entries(store, ticket):
        q = e["q"]
        if e["row"]["kind"] == "factory:autopilot" and authority.human(q) and q["answer"] == "Start":
            at = answered_at(ticket, q)
            if at is None:  # no timestamp, no grant
                continue
            limits = e["data"]["limits"]
            result.append(
                {
                    "order": ticket["id"],
                    "q": q["id"],
                    "by": q["answered_by"],
                    "from": at,
                    "until": at + timedelta(days=limits["days"]),
                    "may": e["data"]["may_decide"],
                    "limits": limits,
                }
            )
    return result


def grants(store, tickets):
    result = []
    for t in tickets:
        if t.get("ext", {}).get("factory", {}).get("role") != "order":
            continue
        try:
            result += grants_of(store, t)
        except Refused:
            continue  # a broken order gives no grant
    return result


def first_orders(grant, decided_rows):
    """Orders this grant may decide for: the first max_orders distinct orders decided after the grant began,
    in journal order (decision rows before the person's Start never count)."""
    seen = []
    for r in decided_rows:
        try:
            when = datetime.fromisoformat(r["at"])
        except (KeyError, ValueError):
            continue
        if grant["from"] <= when < grant["until"] and r["order"] not in seen:
            seen.append(r["order"])
    return seen[: grant["limits"]["max_orders"]]


def check(entry, answer, granted, at, order=None, decided_rows=None):
    """Raise unless a grant covers every item of this stop and the answer is not the ship decision."""
    data = entry["data"]
    if not data["items"]:
        raise Refused("A stop with nothing to decide is always yours.", "not_allowed")
    options = [o for o in authority.render("factory:stop", data, entry["n"])[1]]
    if data["stage"] == "ship" or "Ship it" in options:
        raise Refused("The ship decision is always yours.", "not_allowed")
    if answer not in options:
        raise Refused("That is not one of the answers offered.", "not_allowed")
    if any(i["tag"] == "cant-undo" for i in data["items"]):
        raise Refused("Something here cannot be undone, so it is always yours to decide.", "not_allowed")
    live = [g for g in granted if g["from"] <= at < g["until"]]
    if not live:
        raise Refused("There is no autopilot you approved that is still running.", "not_allowed")
    live = [g for g in live if all(i["tag"] in g["may"] for i in data["items"])]
    if not live:
        raise Refused("Your autopilot does not cover this kind of decision.", "not_allowed")
    if order is not None:
        rows = list(decided_rows or [])
        live = [g for g in live if order in first_orders(g, rows + [{"order": order, "at": at.isoformat()}])]
        if not live:
            raise Refused("The autopilot already covers as many orders as you allowed.", "not_allowed")
    return live


def allowed(entry, answer, granted, at, order=None, decided_rows=None):
    try:
        check(entry, answer, granted, at, order, decided_rows)
    except Refused:
        return False
    return True


def parse(data):
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError):
        raise Refused("The autopilot must be valid JSON.", "invalid") from None
    validate(value, "autopilot")
    return value


def propose(root, order, data):
    from . import flow

    value = parse(data)
    store = Store(root)
    with store.locked():
        ticket = commands.order_ticket(root, order)
        order = ticket["id"]
        # The kind comes from the first recorded lead question, never from the ext cache.
        if authority.order_kind(authority.entries(store, ticket)) == "run":
            raise Refused(
                "This order already has a run proposal. Use a new order for an autopilot.", "conflict"
            )
        info = flow.freeze_ask(
            root,
            store,
            ticket,
            "factory:autopilot",
            data,
            value,
            ext={"kind": "autopilot", "stage": "proposed"},
        )
        return info


def decide(root, order, qid, answer, why):
    from . import flow

    why = clean(why, 200)
    if not why:
        raise Refused("Say in a few words why you decided this.", "invalid")
    store = Store(root)
    with store.locked():
        ticket = commands.order_ticket(root, order)
        tickets = orchcli.tickets(root)
        entry = next((e for e in authority.entries(store, ticket) if e["q"]["id"] == qid), None)
        if entry is None or entry["row"]["kind"] != "factory:stop":
            raise Refused("That is not a stop Factory asked you about.", "not_allowed")
        rows = [r for r in store.journal_read() if r["type"] == "decided"]
        done = next((r for r in rows if r["order"] == ticket["id"] and r["q"] == qid), None)
        if done:
            if done["answer"] == answer:
                return {"order": ticket["id"], "q": qid, "answer": answer, "by": "agent:factory"}
            raise Refused("This was already decided differently.", "not_allowed")
        d = flow.derive(root, store, ticket, tickets)
        if d["phase"] != "started" or d["open"] is None or d["open"]["q"]["id"] != qid:
            raise Refused("That stop is not waiting for a decision now.", "not_allowed")
        if entry["q"].get("answer") is not None:
            raise Refused("A person or an earlier decision already answered this.", "not_allowed")
        check(entry, answer, grants(store, tickets), clock(), ticket["id"], rows)
        store.journal_append(
            {
                "type": "decided",
                "order": ticket["id"],
                "q": qid,
                "answer": answer,
                "by": "agent:factory",
                "why": why,
            }
        )
        orchcli.call(root, "log", ticket["id"], f"Decided by agent:factory · {why}", write=True)
        return {"order": ticket["id"], "q": qid, "answer": answer, "by": "agent:factory"}
