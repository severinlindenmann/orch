"""Idea, draft and proposal lifecycle. All mutations run under the Factory writer lock."""

import json
import re

from . import authority, orchcli
from .render import START_OPTIONS, question_text
from .store import Refused, Store, digest


def order_ticket(root, order):
    ticket = orchcli.ticket(root, order)
    if ticket.get("ext", {}).get("factory", {}).get("role") != "order":
        raise Refused("This ticket is not a Factory order.", "invalid")
    return ticket


ADOPTABLE = {"open", "ready", "waiting", "active"}  # active: the helper adopts the ticket it was started on


def idea(root, title, data, ticket_id=None):
    """A new order, or (`--ticket`) an existing ticket turned into one: e.g. the ticket the owner made from Chat
    while asking for a Factory run. Its note becomes draft v1 when no draft text is given."""
    store = Store(root)
    with store.locked():
        if ticket_id is not None:
            return _adopt(root, store, ticket_id, data)
        ticket = orchcli.call(root, "ticket", "new", title, write=True)
        path = f"drafts/{ticket['id']}/v1.md"
        store.write(path, data, frozen=True)
        orchcli.set_ext(root, ticket, role="order", kind="run", stage="draft", draft=1)
    return {"order": ticket["id"], "draft": str(store.path(path))}


IDEA_MAX = 500
# The start text of an idea-box order: the agent reads the ticket's note when it starts. Without it a neutral idea ("a
# newsletter template") reads like a normal task and gets built (release-22 walk, WLK-15).
ORDER_NOTE = (  # the start text; the person's whole idea follows it in the note (core adds no plan line to add-on tickets)
    "This ticket is a Factory order: write a short draft with orch factory draft, ask the open questions, "
    "then wait. Don't build it; the person presses Plan the run."
)
PERSON = re.compile(r"human:[A-Za-z0-9_.@ -]{1,64}")


def _idea_title(text):
    """The order's title: the idea's first words (at most 80 characters, cut at a word), never starting with "-"."""
    title = text if len(text) <= 80 else text[:80].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"
    return title.lstrip("-– ") or "Idea"


def idea_act(root, text, by):
    """The Factory page's idea box (`orch factory act idea --by human:<name> -- <text>`, run by the dashboard for the
    person who pressed the button): a new order whose draft v1 is the idea, recorded as that person, then the
    manager run is started to write the first real draft. `--by` is a record, never proof: the dashboard runs this
    only for a click with a page session. Agents file ideas with `orch factory idea` as themselves."""
    if not isinstance(by, str) or not PERSON.fullmatch(by):
        raise Refused("Only a person's click files an idea here. Agents use orch factory idea.", "refused")
    text = " ".join(str(text or "").split())
    if not text:
        raise Refused("Write your idea first.", "invalid")
    if len(text) > IDEA_MAX:
        raise Refused(f"An idea here has at most {IDEA_MAX} characters.", "invalid")
    store = Store(root)
    with store.locked():
        ticket = orchcli.call(
            root,
            "ticket",
            "new",
            _idea_title(text),
            f"--note={ORDER_NOTE} The person's idea: {text}",
            write=True,
            by=by,
        )
        store.write(f"drafts/{ticket['id']}/v1.md", text.encode() + b"\n", frozen=True)
        orchcli.set_ext(root, ticket, by=by, role="order", kind="run", stage="draft", draft=1, idea_box=True)
    try:  # the agent writes the first real draft; when no agent can start, the idea is still saved
        orchcli.call(root, "run", "start", ticket["id"], write=True, by=by)
        started = True
    except Refused:
        started = False
    words = (
        "Idea saved. Your agent is writing the first draft."
        if started
        else "Idea saved. Start your agent on it to get the first draft."
    )
    return {"order": ticket["id"], "started": started, "text": words}


def _adopt(root, store, ticket_id, data):
    ticket = orchcli.ticket(root, ticket_id)
    ext = ticket.get("ext", {}).get("factory")
    if ext:
        if ext.get("role") == "order":
            return {"order": ticket["id"], "draft": None, "adopted": False}  # already an order: idempotent
        raise Refused("This ticket is a crew task of a Factory order.", "invalid")
    if ticket.get("parent"):
        raise Refused("A sub-ticket cannot become a Factory order.", "invalid")
    if ticket.get("status") not in ADOPTABLE:
        raise Refused(
            "Only an open ticket (not in review, done or dropped) can become a Factory order.", "invalid"
        )
    text = data or str(ticket.get("note") or ticket.get("title") or "").encode()
    path = f"drafts/{ticket['id']}/v1.md"
    store.write(path, text, frozen=True)
    orchcli.set_ext(root, ticket, role="order", kind="run", stage="draft", draft=1)
    return {"order": ticket["id"], "draft": str(store.path(path)), "adopted": True}


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
    authority.check_frozen("run", value)
    return value


def propose(root, order, data):
    p = proposal(data)
    store = Store(root)
    with store.locked():
        ticket = order_ticket(root, order)
        order = ticket["id"]
        if authority.order_kind(authority.entries(store, ticket)) == "autopilot":
            raise Refused("This is an autopilot order. Use orch factory autopilot.", "invalid")
        # Read-only commands never log. A mutating proposal records ignored agent answers in core history.
        for q in authority.questions(store, ticket):
            if q.get("answer") is not None and authority.who(q).startswith("agent:"):
                text = f"Factory ignored the agent answer to {q['id']}; a person must press Start."
                if not any(h.get("text") == text for h in authority.history(ticket)):
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
        # The person may have pressed Start since the ticket was read: look again right before hiding anything.
        ticket = order_ticket(root, order)
        if authority.from_ticket(store, ticket):
            raise Refused("This order has started. Make a change proposal.")
        for q in authority.questions(store, ticket):
            if q.get("kind") == "factory:start" and q.get("action") != action and not authority.human(q):
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
