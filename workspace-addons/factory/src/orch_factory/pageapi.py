"""The JSON answers of the Factory page (read only). Every state comes from flow.derive / authority / autopilot,
never from the ext cache or raw journal rows. Shapes: contracts/addons/factory/README.md, section Page."""

from __future__ import annotations

import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path

from . import ask, authority, autopilot, flow, handover, orchcli, render, service
from .render import clean
from .store import Refused, Store, clock, no_links

MAX_DRAFT = 256 * 1024
MAX_IMAGE = 10 * 1024 * 1024
ORDER_ID = re.compile(r"t_[a-z0-9]{6,16}")
IMAGE_NAME = re.compile(r"(?:s[1-9][0-9]{0,3}/)?[A-Za-z0-9._-]{1,80}\.(png|jpg|jpeg|webp|gif)")
IMAGE_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}
CHANGE_STATES = {"Accept": "accepted", "Edit": "edit", "Save for later": "later"}
ACTIVITY_MAX = 50
DECISIONS_MAX = 100


def _iso(when):
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(value, cap=120):
    return clean(value, cap) if isinstance(value, str) else ""


def _order_tickets(tickets):
    return [t for t in tickets if t.get("ext", {}).get("factory", {}).get("role") == "order"]


def _lead(d):
    return [e for e in d["ents"] if e["row"]["kind"] in authority.LEAD]


def _open_question(e):
    q = e["q"]
    kind = e["row"]["kind"].split(":")[1]
    out = {
        "q": q["id"],
        "kind": kind,
        "text": q.get("text", ""),
        "options": list(q.get("options") or []),
    }
    if kind in ("stop", "change"):
        out["data"] = e[
            "data"
        ]  # frozen structured data: the page titles the question from it, never the raw text
    return out


def _plain_questions(ticket):
    """The questions your helper asked on the order itself (no Factory kind) that still wait for you: the draft's open
    questions as cards, each with its options and its suggestion. Text from the record is cut and cleaned."""
    out = []
    for q in ticket.get("questions") or []:
        if not isinstance(q, dict) or q.get("kind") is not None or q.get("answer") is not None:
            continue
        if not isinstance(q.get("id"), str):
            continue
        options = [_text(o, 80) for o in (q.get("options") or []) if isinstance(o, str)][:6]
        rec = _text(q.get("recommended"), 80) if q.get("recommended") else None
        out.append({"q": q["id"], "text": _text(q.get("text"), 300), "options": options, "recommended": rec})
    return out[:10]


def _labelled(line, proposal):
    """Stage items with the proposal's own `label` when it gave one (a short, plain name for the owner)."""
    labels = {x["stage"]: x["label"] for x in (proposal or {}).get("line", []) if x.get("label")}
    return [{**x, "label": _text(labels[x["stage"]], 60)} if x["stage"] in labels else x for x in line]


def _eta(d, proposal):
    eta = (proposal.get("time") or {}).get("eta_to") if proposal else None
    for e in sorted(d["ents"], key=lambda x: x["n"]):
        if (
            e["row"]["kind"] == "factory:change"
            and authority.human(e["q"])
            and e["q"]["answer"] == "Accept"
            and e["data"].get("new_eta")
        ):
            eta = e["data"]["new_eta"]
    return eta


def _summary(ticket, d, root=None):
    """One order summary from a derived state `d`."""
    leads = _lead(d)
    proposal = d.get("proposal") or (leads[-1]["data"] if leads else None)
    kind, phase = d["kind"], "draft"
    if leads:
        phase = {"started": "started", "edit": "edit", "parked": "parked"}.get(d["phase"], "proposed")
    if phase == "started":
        if kind == "run" and d["shipped"]:
            phase = "shipped"
        elif kind == "autopilot" and not any(
            clock() < g["until"] for g in autopilot.grants_of(d["store"], ticket)
        ):
            phase = "cancelled"
    if ticket.get("status") == "dropped" and phase != "shipped":
        phase = "cancelled"
    started_run = d["phase"] == "started" and kind == "run"
    cap = d["cap"] if started_run else ((proposal or {}).get("budget") or {}).get("active_min_cap", 0)
    used = d["used"] if started_run else 0
    if started_run:
        line = d["line"]
    else:
        line = [
            {"stage": x["stage"], "stop": x["stop"], "state": "todo"}
            for x in (proposal or {}).get("line", [])
        ]
    line = _labelled(line, proposal)
    open_ = None
    if started_run and d["open"]:
        open_ = _open_question(d["open"])
    elif leads and d["phase"] != "started":
        latest = leads[-1]
        if latest["q"].get("answer") is None:
            open_ = _open_question(latest)
    stage = "shipped" if phase == "shipped" else (d["stage"] if started_run else None)
    return {
        "id": ticket["id"],
        "title": _text((proposal or {}).get("title") or ticket.get("title") or "Untitled") or "Untitled",
        "kind": kind,
        "phase": phase,
        "stage": stage,
        "line": line,
        "budget": {"used": used, "cap": cap, "warn": cap > 0 and used * 5 >= cap * 4},
        "eta": _eta(d, proposal),
        "due": (proposal or {}).get("due"),
        "open": open_,
        "owner_min": ((proposal or {}).get("time") or {}).get("owner_min"),
        "working": _working(root, ticket, phase),
        "agent_draft": _agent_draft(ticket),
        "draft_v": _draft_v(ticket),
        "questions": _plain_questions(ticket),
    }


IDLE = ("idle", "attention")  # a live session whose turn ended, or that waits for a person


def _working(root, ticket, phase):
    """An agent works on the order right now. Core keeps the ticket Working while a run is on it (Ready again when a
    one-step run ends), but a LIVE session stays open after its turn: idle at the prompt, or asking the person
    (attention). For a draft that turn's end is what counts, so the draft waits for you: Plan the run / Ask for changes
    (sent into that same session). Asked only for an order in draft that is Working (one `orch run status`)."""
    if ticket.get("status") != "active":
        return False
    if phase != "draft" or root is None:
        return True
    try:
        st = orchcli.call(root, "run", "status", ticket["id"])
    except Refused:
        return True  # unreadable: as core says (Working)
    claim = st.get("claim") if isinstance(st.get("claim"), dict) else {}
    if not st.get("running"):
        return False
    return not (claim.get("mode") == "live" and (claim.get("live") or {}).get("state") in IDLE)


def _agent_draft(ticket):
    """The newest draft is the agent's: an idea-box order starts with the person's own words as v1, so only v2 and later
    count (an order an agent filed with `orch factory idea` has the agent's v1). Until then Plan the run is not offered."""
    x = (ticket.get("ext") or {}).get("factory") or {}
    v = _draft_v(ticket) or 0
    return v >= (2 if x.get("idea_box") is True else 1)


def _draft_v(ticket):
    """The newest draft version (from the ext cache; only used for a link, the draft itself is read from its file)."""
    v = ((ticket.get("ext") or {}).get("factory") or {}).get("draft")
    return v if type(v) is int and v > 0 else None


def _broken(ticket, error):
    return {
        "id": ticket["id"],
        "title": _text(ticket.get("title") or "Untitled") or "Untitled",
        "kind": "run",
        "phase": "broken",
        "stage": None,
        "line": [],
        "budget": {"used": 0, "cap": 0, "warn": False},
        "eta": None,
        "due": None,
        "open": None,
        "owner_min": None,
        "working": False,
        "agent_draft": False,
        "draft_v": None,
        "questions": [],
        "problem": _text(str(error), 200),
    }


def _derive(root, store, ticket, tickets):
    d = flow.derive(root, store, ticket, tickets)
    d["store"] = store
    return d


def _day(row):
    try:
        return datetime.fromisoformat(row["at"]).astimezone().date()
    except (KeyError, TypeError, ValueError):
        return None


def _decisions(journal, ok):
    rows = [
        {"order": r["order"], "q": r["q"], "answer": r.get("answer"), "why": r.get("why", ""), "at": r["at"]}
        for r in journal
        if r["type"] == "decided" and r["q"] in ok
    ]
    return rows[::-1][:DECISIONS_MAX]


def _grants(store, tickets, journal):
    now = clock()
    return [
        {
            "order": g["order"],
            "until": _iso(g["until"]),
            "may": list(g["may"]),
            "limits": g["limits"],
            "live": g["from"] <= now < g["until"],
        }
        for g in autopilot.grants(store, tickets, journal)
    ]


def _all(root):
    """(summaries, ok decided question ids, store, tickets, journal): one pass over every order."""
    store = Store(root)
    tickets = orchcli.tickets(root)
    journal = store.journal_read()
    summaries, ok = [], set()
    for t in _order_tickets(tickets):
        try:
            d = _derive(root, store, t, tickets)
        except Refused as error:
            summaries.append(_broken(t, error))
            continue
        summaries.append(_summary(t, d, root))
        ok |= d["decided_ok"]
    return summaries, ok, store, tickets, journal


def _day_limit(root, store, tickets, journal):
    status = autopilot.day_status(root, store, tickets, journal)
    if status is None:
        return None
    return {**status, "warning": autopilot.day_warning(status)}


def home(root):
    summaries, ok, store, tickets, journal = _all(root)
    grants = _grants(store, tickets, journal)
    auto = None
    if grants:
        today = datetime.now().astimezone().date()
        auto = {
            "on": any(g["live"] for g in grants),
            "until": max(g["until"] for g in grants),
            "decided_today": sum(
                1 for r in journal if r["type"] == "decided" and r["q"] in ok and _day(r) == today
            ),
        }
    return {
        "generated_at": _iso(clock()),
        "orders": summaries,
        "autopilot": auto,
        "day_limit": _day_limit(root, store, tickets, journal),
        "watcher": service.running_pid(root, clean=False) is not None,
    }


def autopilot_view(root):
    _, ok, store, tickets, journal = _all(root)
    return {"grants": _grants(store, tickets, journal), "decisions": _decisions(journal, ok)}


def _drafts(store, order):
    base = store.path(f"drafts/{order}")
    found = []
    try:
        names = list(base.iterdir())
    except OSError:
        return []
    for p in names:
        m = re.fullmatch(r"v([1-9][0-9]*)\.md", p.name)
        if not m:
            continue
        try:
            st = p.lstat()
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            found.append({"v": int(m[1]), "at": _iso(datetime.fromtimestamp(st.st_mtime, UTC))})
    return sorted(found, key=lambda x: x["v"])


def _tiny(d):
    out = []
    for r in d["rows"]:
        if r["type"] == "tiny-change":
            m = re.match(r"(\d+) min: (.*)", r.get("why", ""), re.DOTALL)
            out.append({"what": _text(m[2], 200) if m else "", "minutes": int(m[1]) if m else 0})
    return out


def _stops(d, root=None, tickets=()):
    out = []
    outbox = None
    named = ask.names(root) if root is not None else {}
    for e in sorted((e for e in d["ents"] if e["row"]["kind"] == "factory:stop"), key=lambda e: e["n"]):
        eff = d["effective"](e)
        if eff:
            state, answer, by = ("decided" if eff[1] == "agent:factory" else "answered"), eff[0], eff[1]
        elif e["q"].get("answer") is not None:
            state, answer, by = "ignored", None, authority.who(e["q"]) or None
        else:
            state, answer, by = "open", None, None
        asks = ask.view(root, tickets, d["tid"], e["n"], named, outbox) if root is not None else []
        if any(a["state"] == "queued" for a in asks) and outbox is None:
            outbox = _outbox(root)  # one look at what waits to be sent, only when an ask says it is queued
            asks = ask.view(root, tickets, d["tid"], e["n"], named, outbox)
        out.append(
            {
                "n": e["n"],
                "stage": e["data"]["stage"],
                "data": e["data"],
                "state": state,
                "answer": answer,
                "by": by,
                "asks": asks,
                "autopilot_waits": state == "open"
                and any(a["state"] != "failed" and a["state"] != "closed" for a in asks),
            }
        )
    return out


def _outbox(root):
    try:
        return orchcli.call(root, "relay", "outbox").get("waiting") or []
    except Refused:
        return []


def reach(root):
    """Workspaces a stop may be shared with (empty when the relay is off, so the page shows no button)."""
    return ask.reach(root)


def scan(root, order_id, n):
    if not ORDER_ID.fullmatch(order_id):
        return None
    try:
        return ask.scan_stop(root, order_id, n)
    except Refused:
        return None


def _changes(d):
    out = []
    for e in sorted((e for e in d["ents"] if e["row"]["kind"] == "factory:change"), key=lambda e: e["n"]):
        q = e["q"]
        state = CHANGE_STATES.get(q.get("answer"), "open") if authority.human(q) else "open"
        out.append(
            {
                "n": e["n"],
                "title": _text(e["data"]["title"]),
                "adds_min": e["data"].get("adds_min", 0),
                "state": state,
            }
        )
    return out


def _crew(d, root, store):
    out = []
    handovers = {h["task"]: h for h in d.get("proposal", {}).get("handovers", [])}
    for slug, task in d["tasks"].items():
        t = d["crew"].get(slug)
        row = {
            "ticket": t["id"] if t else None,
            "title": _text(task["title"]),
            "role": task["role"],
            "agent": task.get("agent"),
            "status": (t.get("status") if t else None) or ("open" if t else "todo"),
        }
        h = handover.of(d, slug)
        if h is not None:
            mine = handover.cached(t) if t else None
            name = handover.display_name(root, h["workspace"])
            state = (mine or {}).get("state")
            row["with"] = {
                "name": name,
                "state": state,
                "words": render.handover_words(name, state) if state else "Goes to " + name,
                "since": handover.sent_at(store, t["id"]) if t else None,
            }
        elif slug in handovers and t and handover.cached(t):
            row["with"] = {
                "name": handover.cached(t).get("name"),
                "state": "not_needed",
                "words": "Done here instead",
                "since": None,
            }
        out.append(row)
    return out


def _activity(ticket):
    lines = [
        {"at": h.get("at"), "text": _text(h.get("text"), 300)}
        for h in authority.history(ticket)
        if isinstance(h, dict)
        and isinstance(h.get("text"), str)
        and (h["text"].startswith("Factory") or h["text"].startswith("Decided by agent:factory"))
    ]
    return lines[-ACTIVITY_MAX:]


def order(root, order_id):
    """The order page answer, or None when this is no Factory order."""
    if not ORDER_ID.fullmatch(order_id):
        return None
    store = Store(root)
    tickets = orchcli.tickets(root)
    ticket = next((t for t in _order_tickets(tickets) if t["id"] == order_id), None)
    if ticket is None:
        return None
    try:
        d = _derive(root, store, ticket, tickets)
    except Refused as error:
        return {**_broken(ticket, error), "proposal": None, "drafts": _drafts(store, order_id)}
    leads = _lead(d)
    proposal = d.get("proposal") or (leads[-1]["data"] if leads else None)
    return {
        **_summary(ticket, d, root),
        "proposal": proposal,
        "drafts": _drafts(store, order_id),
        "crew": _crew(d, root, store),
        "handover": handover.lines(root, proposal) if proposal and proposal.get("kind") == "run" else [],
        "changes": _changes(d),
        "tiny": _tiny(d),
        "stops": _stops(d, root, tickets),
        "activity": _activity(ticket),
    }


def _read_regular(path: Path, cap: int):
    """The bytes of a regular file (no link anywhere on the way, never follows one), at most cap+1 bytes."""
    no_links(path)
    # O_NONBLOCK: a FIFO planted in the folder must fail the regular-file check, never block the open
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise OSError("not a regular file")
        return stream.read(cap + 1)


def draft(root, order_id, v):
    """{"v", "text"} (plain text, at most 256 KB; "truncated" when longer), or None."""
    if not ORDER_ID.fullmatch(order_id) or not re.fullmatch(r"[1-9][0-9]{0,5}", v):
        return None
    try:
        data = _read_regular(Store(root).path(f"drafts/{order_id}/v{v}.md"), MAX_DRAFT)
    except (OSError, Refused):
        return None
    out = {"v": int(v), "text": data[:MAX_DRAFT].decode("utf-8", "replace")}
    if len(data) > MAX_DRAFT:
        out["truncated"] = True
    return out


def image(root, order_id, name):
    """(bytes, content type) of a stop image, or None. Only names of IMAGE_NAME inside stops/<id>/."""
    if not ORDER_ID.fullmatch(order_id) or not IMAGE_NAME.fullmatch(name):
        return None
    try:
        data = _read_regular(Store(root).path(f"stops/{order_id}/{name}"), MAX_IMAGE)
    except (OSError, Refused):
        return None
    if len(data) > MAX_IMAGE:
        return None
    return data, IMAGE_TYPES[name.rsplit(".", 1)[1].lower()]
