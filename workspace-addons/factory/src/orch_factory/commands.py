"""Idea, draft and proposal lifecycle. All mutations run under the Factory writer lock."""

import json

from . import authority, orchcli
from .render import START_OPTIONS, question_text
from .store import Refused, Store, digest, validate


def order_ticket(root, order):
    ticket = orchcli.ticket(root, order)
    if ticket.get("ext", {}).get("factory", {}).get("role") != "order":
        raise Refused("This ticket is not a Factory order.", "invalid")
    return ticket


def idea(root, title, data):
    store = Store(root)
    with store.locked():
        ticket = orchcli.call(root, "ticket", "new", title, write=True)
        path = f"drafts/{ticket['id']}/v1.md"
        store.write(path, data, frozen=True)
        orchcli.set_ext(root, ticket, role="order", kind="run", stage="draft", draft=1)
    return {"order": ticket["id"], "draft": str(store.path(path))}


def draft(root, order, data):
    store = Store(root)
    with store.locked():
        ticket = order_ticket(root, order)
        order = ticket["id"]
        n = store.next_version("drafts", order, "v", "md")
        path = f"drafts/{order}/v{n}.md"
        store.write(path, data, frozen=True)
        orchcli.set_ext(root, ticket, draft=n)
    return {"order": order, "draft": str(store.path(path))}


def proposal(data):
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError):
        raise Refused("The proposal must be valid JSON.", "invalid") from None
    validate(value, "proposal")
    if value["line"][-1]["stage"] != "ship" or value["line"][-1]["stop"] is not True:
        raise Refused("The last stage must be ship, with a stop for you.", "invalid")
    stages = {x["stage"] for x in value["line"]}
    if any(t["stage"] not in stages for t in value["tasks"]):
        raise Refused("Every task must belong to a stage in the line.", "invalid")
    if any(i >= len(value["done_means"]) for t in value["tasks"] for i in t.get("proves", [])):
        raise Refused("A task refers to a done-means point that does not exist.", "invalid")
    return value


def propose(root, order, data):
    p = proposal(data)
    store = Store(root)
    with store.locked():
        ticket = order_ticket(root, order)
        order = ticket["id"]
        if ticket["ext"]["factory"].get("kind") == "autopilot":
            raise Refused("This is an autopilot order. Use orch factory autopilot.", "invalid")
        # Read-only commands never log. A mutating proposal records ignored agent answers in core history.
        for q in authority.questions(store, ticket):
            if q.get("answer") is not None and str(q.get("answered_by") or "").startswith("agent:"):
                text = f"Factory ignored the agent answer to {q['id']}; a person must press Start."
                if not any(h.get("text") == text for h in ticket.get("history", [])):
                    orchcli.call(root, "log", order, text, write=True)
                    ticket = order_ticket(root, order)
        if authority.from_ticket(store, ticket):
            raise Refused("This order has started. Make a change proposal.")
        ext = ticket["ext"]["factory"]
        if ext["stage"] in ("running", "waiting", "shipped"):
            # The cache cannot grant authority. Leave evidence without inventing a journal event kind.
            orchcli.call(
                root, "log", order, "Factory refused: stage cache disagrees with Start authority.", write=True
            )
            raise Refused("The Factory stage disagrees with its Start answers.", "conflict")
        rows = [r for r in store.journal_read() if r["order"] == order]
        previous = next((r for r in reversed(rows) if r["type"] == "proposed"), None)
        h = digest(data)
        same = previous is not None and previous["hash"] == h
        if same:
            path = previous["file"]
            if store.read(path) != data:
                raise Refused("The frozen proposal has changed.", "tampered")
            n = int(path.rsplit("/p", 1)[1].removesuffix(".json"))
            recorded = next(
                (
                    r
                    for r in reversed(rows)
                    if r["type"] == "asked" and r.get("file") == path and r.get("hash") == h
                ),
                None,
            )
            if recorded:
                qs = authority.questions(store, ticket)
                if not any(q["id"] == recorded["q"] for q in qs):
                    raise Refused("The recorded Factory question is missing.", "tampered")
                return {"order": order, "proposal": n, "question": recorded["q"], "file": path, "hash": h}
        else:
            n = store.next_version("proposals", order, "p", "json")
            path = f"proposals/{order}/p{n}.json"
            store.write(path, data, frozen=True)
            store.journal_append({"type": "proposed", "order": order, "file": path, "hash": h})
        action = {"order": order, "file": path, "hash": h}
        # Retrying an interrupted proposal also finishes superseding the previous open question.
        for q in authority.questions(store, ticket):
            if (
                q.get("kind") == "factory:start"
                and q.get("action") != action
                and (q.get("answer") is None or not str(q.get("answered_by") or "").startswith("human:"))
            ):
                store.journal_append(
                    {"type": "superseded", "order": order, "q": q["id"], "kind": "factory:start"}
                )
        orchcli.set_ext(
            root,
            ticket,
            stage="proposed",
            proposal={"n": n, "hash": h},
            budget=p["budget"],
            line=[{"stage": x["stage"], "stop": x["stop"], "state": "todo"} for x in p["line"]],
        )
        q = orchcli.call(
            root,
            "ask",
            order,
            question_text(p, n),
            "--kind",
            "factory:start",
            *[x for o in START_OPTIONS for x in ("--option", o)],
            "--action",
            json.dumps(action),
            write=True,
        )
        if q.get("kind") != "factory:start" or q.get("action") != action:
            raise Refused("Orch returned a question for a different proposal.", "conflict")
        store.journal_append({"type": "asked", **action, "q": q["id"], "kind": "factory:start"})
        return {"order": order, "proposal": n, "question": q["id"], "file": path, "hash": h}


def describe(store, ticket):
    ext = ticket.get("ext", {}).get("factory", {})
    qs = authority.questions(store, ticket)
    return {
        "order": ticket["id"],
        "title": ticket["title"],
        "stage": ext.get("stage"),
        "proposal": ext.get("proposal", {}).get("n"),
        "questions": [q for q in qs if q.get("answer") is None],
        "started": authority.from_ticket(store, ticket),
    }


def show(root, order):
    return describe(Store(root), order_ticket(root, order))


def listing(root):
    store = Store(root)
    return [
        describe(store, t)
        for t in orchcli.tickets(root)
        if t.get("ext", {}).get("factory", {}).get("role") == "order"
    ]
