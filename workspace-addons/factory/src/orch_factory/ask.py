"""Ask another workspace for its view at a stop (#816 A). Everything goes through the core CLI (orchcli): a small
"ask" sub-ticket of the order carries the one line and the ticked items, the core's group share does the path rule and
the secret scan. Nothing here reads or writes a core ticket file, and nothing here can answer the stop: an answer from
the other workspace is text to read (the page shows it cleaned), never a stop answer."""

import json
import re
from pathlib import Path

from . import authority, commands, orchcli
from .render import clean
from .store import Refused, Store

PERSON = commands.PERSON
TARGET = re.compile(
    r"(t_[a-z0-9]{6,16}):s([1-9][0-9]{0,3}):(ws_[a-z0-9]{6,32}):(-|[0-9]{1,2}(?:,[0-9]{1,2}){0,11})"
)
QUESTION = "What would you change before this ships?"
WORKSPACES = ".agents/skills/orch-relay/workspaces.json"
DIRECTORY_MAX = 256 * 1024
FINISHED = ("done", "dropped")
NOT_DELIVERED = "Factory: not delivered"
QUEUED = "Factory: queued"
PARTIAL = "Factory: partly sent"
CARD = "Factory: card sent"
QUESTION_SENT = "Factory: question sent"
SAVED = "Factory: picture saved · "
SENT = "Factory: picture sent · "
OFFLINE = "Can't reach"  # core: "Can't reach <host> right now."
KEPT = "is kept and goes out"  # core's words when the relay is unreachable: the message waits in the outbox
SCAN_STEP, SCAN_CHUNK = 900_000, 1_000_000  # core's scan takes 1 MB of text; chunks overlap
LINES_MAX = 3


def _directory(root):
    """The relay's workspace list (a file orch writes into its skill folder); nothing when relay is off."""
    path = Path(root) / WORKSPACES
    try:
        # core links this skill folder itself; the file only names workspaces
        raw = path.read_bytes()[: DIRECTORY_MAX + 1]
        value = json.loads(raw) if len(raw) <= DIRECTORY_MAX else None
    except (OSError, ValueError, UnicodeError, Refused):
        return []
    rows = value.get("workspaces") if isinstance(value, dict) else None
    return (
        [w for w in rows if isinstance(w, dict) and isinstance(w.get("id"), str)]
        if isinstance(rows, list)
        else []
    )


def names(root):
    return {w["id"]: clean(w.get("name") or w["id"], 60) for w in _directory(root)}


def reach(root):
    """Workspaces that may get group messages: connected both ways for text (core's rule for joining a group)."""
    out = []
    for w in _directory(root):
        sends, takes = w.get("can_send"), w.get("accepts_from")
        if isinstance(sends, dict) and isinstance(takes, dict) and sends.get("text") and takes.get("text"):
            out.append(
                {
                    "ws": w["id"],
                    "name": clean(w.get("name") or w["id"], 60),
                    "description": clean(w.get("description") or "", 120),
                }
            )
    return out


def _x(ticket):
    x = (ticket.get("ext") or {}).get("factory") if isinstance(ticket, dict) else None
    return x if isinstance(x, dict) else {}


def asks_of(tickets, order, n=None):
    """The ask sub-tickets of an order (of one stop), derived from the tickets every time: no cache."""
    return [
        t
        for t in tickets
        if _x(t).get("role") == "ask"
        and _x(t).get("order") == order
        and t.get("parent") == order
        and (n is None or _x(t).get("stop") == n)
    ]


def live_asks(tickets, order, n):
    return [t for t in asks_of(tickets, order, n) if t.get("status") not in FINISHED]


def has_ask(tickets, order, n):
    """Autopilot never decides a stop the person asked about."""
    return bool(live_asks(tickets, order, n))


def label_of(proposal, stage):
    for x in proposal["line"]:
        if x["stage"] == stage and x.get("label"):
            return clean(x["label"], 60)
    return "Ship it?" if stage == "ship" else clean(stage.replace("-", " ").capitalize(), 60)


def _image_names(data, indexes):
    """(item index, name) of the pictures of these stop items, each name once."""
    from .pageapi import IMAGE_NAME

    seen, out = set(), []
    for i in indexes:
        item = data["items"][i]
        for key in ("before", "after"):
            name = item.get(key)
            if isinstance(name, str) and IMAGE_NAME.fullmatch(name) and name not in seen:
                seen.add(name)
                out.append((i, name))
    return out


def _read(store, order, name):
    from .pageapi import MAX_IMAGE, _read_regular

    try:
        data = _read_regular(store.path(f"stops/{order}/{name}"), MAX_IMAGE)
    except (OSError, Refused):
        return None
    return data if len(data) <= MAX_IMAGE else None


def _scan(root, data):
    """None when clean, else the plain reason. The core's own scan (`orch secret scan`), in overlapping chunks."""
    for start in range(0, max(len(data), 1), SCAN_STEP):
        try:
            orchcli.call(root, "secret", "scan", data=data[start : start + SCAN_CHUNK])
        except Refused as error:
            if getattr(error, "found", None):
                return "looks like it holds a password or a key"
            raise
    return None


def scan_stop(root, order, n):
    """The page's dialog check: the exact card title, line and question that will be sent, and per item the checklist
    text that will be sent and its pictures' scan: {"title", "line", "question", "items": [{"i", "title", "check",
    "files": [{"name", "ok", "why"?}]}]}. Read only."""
    from . import flow

    store = Store(root)
    ticket = commands.order_ticket(root, order)
    d = flow.derive(root, store, ticket)
    e = next((x for x in d["ents"] if x["row"]["kind"] == "factory:stop" and x["n"] == n), None)
    if e is None:
        return None
    out = []
    stop_items = e["data"]["items"]
    shown = texts(d["proposal"], e["data"]["stage"], stop_items, list(range(len(stop_items))))
    for i, item in enumerate(stop_items):
        files = []
        for _, name in _image_names(e["data"], [i]):
            data = _read(store, order, name)
            why = "is missing or too big" if data is None else _scan(root, data)
            files.append({"name": name, "ok": why is None, **({"why": why} if why else {})})
        out.append({"i": i, "title": clean(item["title"]), "check": shown["checks"][i], "files": files})
    return {"title": shown["title"], "line": shown["line"], "question": shown["question"], "items": out}


def ask(root, order, n, ws, items, by, pictures=True):
    if not isinstance(by, str) or not PERSON.fullmatch(by):
        raise Refused("Only a person's click asks another workspace. Agents never do.", "refused")
    from . import flow

    store = Store(root)
    with store.locked():
        ticket = commands.order_ticket(root, order)
        tickets = orchcli.tickets(root)
        d = flow.started_state(root, store, ticket, tickets)
        order = d["tid"]
        e = d["open"]
        if not e or e["row"]["kind"] != "factory:stop" or e["n"] != n:
            raise Refused("That stop is not waiting for your answer.", "not_allowed")
        who = {r["ws"]: r for r in reach(root)}.get(ws)
        if who is None:
            raise Refused("That workspace is not connected to this one for group messages.", "not_allowed")
        if any(_x(t).get("ws") == ws for t in live_asks(tickets, order, n)):
            raise Refused(
                f"You already asked {who['name']} about this stop. Wait for the answer.", "conflict"
            )
        stop = e["data"]
        if not items and not pictures:
            pass
        if any(i < 0 or i >= len(stop["items"]) for i in items) or len(set(items)) != len(items):
            raise Refused("Pick items of this stop.", "invalid")
        files = []
        for _, name in _image_names(stop, items) if pictures else []:
            data = _read(store, order, name)
            if data is None:
                raise Refused(
                    f"A picture of this stop is missing or too big: {name}. Nothing was sent.", "refused"
                )
            why = _scan(root, data)
            if why:  # before anything leaves: the whole ask is refused
                raise Refused(f"{name} {why}, so nothing was sent. Untick it or remove it first.", "refused")
            files.append((name, data))
        text = texts(d["proposal"], stop["stage"], stop["items"], items)
        ext = {"role": "ask", "order": order, "stop": n, "ws": ws}
        sub = orchcli.call(
            root, "ticket", "new", text["title"], "--parent", order,
            "--ext", "factory=" + json.dumps(ext), write=True, by=by,
        )  # fmt: skip
        sid = sub["id"]
        try:  # only this machine so far: a failure here means nothing left
            orchcli.call(root, "ticket", "summary", sid, text["line"], write=True, by=by)
            for check in text["checks"]:
                orchcli.call(root, "check", "add", sid, check, write=True, by=by)
            orchcli.call(root, "ask", sid, QUESTION, write=True, by=by)
            for name, data in files:
                att = orchcli.call(
                    root, "ticket", "attach", sid, f"--name={name.rsplit('/', 1)[-1]}",
                    data=data, write=True, by=by,
                )  # fmt: skip
                _note(root, sid, f"{SAVED}{att['path']}")
        except Refused as error:
            _note(root, sid, f"{NOT_DELIVERED} · {clean(str(error), 200)}")
            _drop(root, sid)
            raise
        state, said = deliver(root, sid, ws, who["name"], by)
        if state == "failed":
            raise Refused(said, "refused")
        store.journal_append({"type": "asked", "order": order, "why": f"ask s{n} {ws} {sid}"})
        orchcli.call(
            root, "log", order, f"Asked {who['name']} for a view on {text['label']}", write=True, by=by
        )
        out = {"order": order, "stop": n, "ws": ws, "ticket": sid, "state": state}
        return {**out, "pictures": len(files), "items": len(items), **({"said": said} if said else {})}


def texts(proposal, stage, stop_items, indexes):
    """EXACTLY what the group card carries, for the dialog's preview and for the send (one function): the card
    title, the fixed line, one checklist text per ticked item (and the question, which is fixed)."""
    title = clean(proposal["title"], 70)
    label = label_of(proposal, stage)
    return {
        "title": f"Your view: {title} · {label}",
        "line": f"{title} · {label}: what would you change before this ships?"[:200],
        "label": label,
        "checks": [clean(stop_items[i]["title"], 120) for i in indexes],
        "question": QUESTION,
    }


def _history_texts(ticket):
    return [
        h["text"] for h in authority.history(ticket) if isinstance(h, dict) and isinstance(h.get("text"), str)
    ]


def deliver(root, sid, ws, name, by=None):
    """The steps that need the relay, each recorded on the ask ticket when done, so a retry (the watcher's next pass,
    `orch factory reconcile`) goes on where it stopped: the card, each saved picture, the question. Returns
    (state, text): delivered | queued (the relay was not reachable, it goes on later) | partial (some went out and
    then it failed: said = what went out) | failed (nothing went out; said = why)."""
    t = orchcli.ticket(root, sid)
    lines = _history_texts(t)
    saved = [x[len(SAVED) :] for x in lines if x.startswith(SAVED)]
    sent = [x[len(SENT) :] for x in lines if x.startswith(SENT)]
    by = by if isinstance(by, str) and PERSON.fullmatch(by) else "agent:factory"

    def went():
        have = [x for x in lines if x == CARD or x.startswith(SENT)]
        if not have:
            return ""
        pics = [x for x in lines if x.startswith(SENT)]
        return "the card with the ticked items" + (
            f" and {len(pics)} of {len(saved)} pictures" if saved else ""
        )

    try:
        if CARD not in lines:
            orchcli.call(root, "relay", "group", "add", sid, ws, write=True, by=by)
            _note(root, sid, CARD)
            lines.append(CARD)
        for path in saved:
            if path not in sent:
                orchcli.call(root, "relay", "group", "share", sid, path, "--click", write=True, by=by)
                _note(root, sid, f"{SENT}{path}")
                lines.append(f"{SENT}{path}")
        if QUESTION_SENT not in lines:
            q = next((x for x in t.get("questions") or [] if x.get("kind") is None), None)
            if q is None:
                raise Refused("The question is missing on the ask ticket.")
            try:
                orchcli.call(root, "relay", "group", "ask", sid, ws, q["id"], write=True, by=by)
                kept = False
            except Refused as error:
                if KEPT not in str(error):
                    raise
                kept = True  # the question waits in core's outbox and goes out with the next relay command
            _note(root, sid, QUESTION_SENT)
            if kept:
                _note(root, sid, f"{QUEUED} · {name} is offline. It goes out when it is back.")
            return "queued" if kept else "delivered", ""
    except Refused as error:
        if OFFLINE in str(error):  # not reachable now: the steps left go on later
            if not any(x.startswith(QUEUED) for x in lines):
                _note(
                    root, sid, f"{QUEUED} · {name} can't be reached now. It goes out when the relay is back."
                )
            return "queued", ""
        done = went()
        if done:
            said = f"Only part of it went out: {done}. The rest did not: {clean(str(error), 160)}"
            _note(root, sid, f"{PARTIAL} · {said}")
        else:
            said = clean(str(error), 200)
            _note(root, sid, f"{NOT_DELIVERED} · {said}")
        _drop(root, sid)
        return ("partial", said) if done else ("failed", said)
    return "delivered", ""


def resume(root, tickets):
    """Go on with asks that waited for the relay (the watcher's pass, `orch factory reconcile`). Never raises."""
    n = names(root)
    for t in tickets:
        x = _x(t)
        if x.get("role") != "ask" or t.get("status") in FINISHED:
            continue
        lines = _history_texts(t)
        if any(h.startswith(QUEUED) for h in lines) and QUESTION_SENT not in lines:
            try:
                deliver(root, t["id"], x.get("ws"), n.get(x.get("ws")) or str(x.get("ws")))
            except Refused:
                continue


def _note(root, sid, text):
    try:
        orchcli.call(root, "log", sid, text, write=True)
    except Refused:
        pass


def _drop(root, sid):
    try:
        orchcli.call(root, "ticket", "status", sid, "dropped", write=True)
    except Refused:
        pass


def close_for_stop(root, tickets, order, n):
    """The stop was answered (by a person): its ask sub-tickets are closed, the other side's card shows it closed.
    The one call flow makes. A failure to close never stops the run."""
    for t in live_asks(tickets, order, n):
        _drop(root, t["id"])


def parse_target(target):
    m = TARGET.fullmatch(str(target))
    if not m:
        raise Refused("That is not something this action can work on.", "invalid")
    items = [] if m[4] == "-" else [int(x) for x in m[4].split(",")]
    return m[1], int(m[2]), m[3], items


def act(root, target, by):
    """`orch factory act ask --by human:<name> -- <order>:s<N>:<ws>:<items>` (manifest [acts.ask], who = people)."""
    order, n, ws, items = parse_target(target)
    return ask(root, order, n, ws, items, by)


# ---- what the page shows ----------------------------------------------------------------------------------


def _lines(text):
    rows = [clean(x, 300) for x in str(text).splitlines()]
    rows = [x for x in rows if x]
    return "\n".join(rows[:LINES_MAX]), len(rows) > LINES_MAX


def _reply(text, at, by, name):
    shown, more = _lines(text)
    return {"text": shown, "at": at, "by": by, "name": name, **({"more": True} if more else {})}


def view(root, tickets, order, n, name_of, outbox=None):
    """`stops[].asks` for one stop: a row per ask sub-ticket, state and the other side's replies (untrusted text)."""
    out = []
    for t in sorted(asks_of(tickets, order, n), key=lambda x: str(x.get("created_at") or x["id"])):
        ws = _x(t).get("ws")
        name = name_of.get(ws) or clean(str(ws), 60)
        history = [h for h in authority.history(t) if isinstance(h, dict) and isinstance(h.get("text"), str)]
        at = next((h.get("at") for h in history if h.get("text", "").startswith(("Asked", "Created"))), None)
        replies = []
        q = next((x for x in t.get("questions") or [] if x.get("kind") is None), None)
        if q and q.get("answer") is not None:
            helper = authority.who(q).startswith("agent:")
            when = next(
                (h.get("at") for h in history if h.get("text") == f"Answered {q['id']}: {q['answer']}"), None
            )
            replies.append(_reply(q["answer"], when, "helper" if helper else "person", name))
        for h in (
            history
        ):  # the other side's group texts: their history lines are `Group: <text>` by agent:<their name>
            if (
                h.get("chat_message") is True
                and h.get("by") == f"agent:{name}"
                and h["text"].startswith("Group: ")
            ):
                replies.append(_reply(h["text"][7:], h.get("at"), "person", name))
        failed = any(h["text"].startswith(NOT_DELIVERED) for h in history)
        partial = any(h["text"].startswith(PARTIAL) for h in history)
        queued = any(h["text"].startswith(QUEUED) for h in history)
        complete = any(h["text"] == QUESTION_SENT for h in history)
        if failed:
            state = "failed"
        elif partial:
            state = "partial"
        elif t.get("status") in FINISHED:
            state = "closed"
        elif replies:
            state = "answered"
        elif queued and (
            not complete or outbox is None or any(m.get("to") == ws for m in outbox)
        ):  # still waiting for the relay, or sent and not yet taken
            state = "queued"
        else:
            state = "delivered"
        row = {"ws_name": name, "at": at, "state": state, "replies": replies}
        if state in ("failed", "partial"):  # what went out, or why not (our own words from the ask ticket)
            marker = PARTIAL if state == "partial" else NOT_DELIVERED
            row["note"] = clean(
                next(x["text"] for x in history if x["text"].startswith(marker)).split(" · ", 1)[-1], 240
            )
        out.append(row)
    return out
