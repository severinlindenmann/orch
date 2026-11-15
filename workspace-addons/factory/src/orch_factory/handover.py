"""Hand one task of a run to another connected workspace (#816 part B).

Everything goes through core's own commands: `orch relay delegate ... --group` for the task and
`orch relay group share` for each file (core applies its path rule and the shared secret scan; no checker here).
The state of the task is read from the group's task card (`orch relay group list`); `ext.factory.handover` on the
crew ticket is only a cache for the page. `handover.json` in the Factory folder is bookkeeping for idempotence (what
was sent, what was shared), never an authority."""

import json
import os
import stat
from pathlib import Path

from . import authority, orchcli
from .render import clean
from .store import Refused, handover_file_ok, read_bytes

FILE = "handover.json"
DIRECTORY = (".agents", "skills", "orch-relay", "workspaces.json")
TERMINAL = ("done", "failed", "denied", "not_needed")
KNOWN = ("waiting_start", "waiting_allow", "queued", "working", "review", "done", "failed", "denied")
NOT_NEEDED = "not_needed"
NO_LONGER = "No longer needed: {title}. Please do not start it."


def _entries(root):
    path = Path(root).absolute().joinpath(*DIRECTORY)
    try:
        data = json.loads(read_bytes(path))
    except (OSError, ValueError, UnicodeError):
        return []
    items = data.get("workspaces") if isinstance(data, dict) else None
    return [w for w in items if isinstance(w, dict)] if isinstance(items, list) else []


def workspace(root, ws):
    """The directory entry of a workspace this one may hand a task to, else None."""
    for w in _entries(root):
        can = w.get("can_send")
        if w.get("id") == ws and isinstance(can, dict) and can.get("delegate"):
            return w
    return None


def _plain_file(root, rel):
    """A regular file inside the workspace, reached without a symbolic link (core's group share checks the rest)."""
    if not handover_file_ok(rel):
        return False
    path = Path(root).absolute()
    info = None
    for part in Path(rel).parts:
        path = path / part
        try:
            info = os.lstat(path)
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode):
            return False
    return info is not None and stat.S_ISREG(info.st_mode)


def check_freeze(root, p):
    """Refuse a proposal whose hand-over cannot work, in plain words, before anything is frozen."""
    slugs = {t["slug"] for t in p["tasks"]}
    for h in p.get("handovers", []):
        task = clean(h["task"], 48)
        if h["task"] not in slugs:
            raise Refused(
                f"The hand-over names '{task}', which is not one of the tasks. Name a task of the plan.",
                "invalid",
            )
        if not h["workspace"].startswith("ws_") or workspace(root, h["workspace"]) is None:
            raise Refused(
                f"'{task}' goes to a workspace you cannot hand tasks to. "
                "Pick one from the connected workspaces (orch relay refresh updates the list) or do it here.",
                "invalid",
            )
        for f in (h.get("sends") or {}).get("files", []):
            if not _plain_file(root, f):
                raise Refused(
                    f"'{task}' sends {clean(f, None)}, which is not a file in this workspace. "
                    "Remove it from the list or create the file first.",
                    "invalid",
                )


# ---- which tasks ------------------------------------------------------------------------------------------


def of(d, task):
    """The hand-over of a task of a started order, or None (also None once the person took it back)."""
    for h in d.get("proposal", {}).get("handovers", []):
        if h["task"] == task and task not in taken_back(d):
            return h
    return None


def taken_back(d):
    """Hand-over tasks the person took back: a person-accepted change with `takes_back` ("Do it here instead")."""
    names = {h["task"] for h in d.get("proposal", {}).get("handovers", [])}
    return {
        e["data"]["takes_back"]
        for e in d.get("ents", [])
        if e["row"]["kind"] == "factory:change"
        and e["q"].get("answer") == "Accept"
        and str(e["q"].get("answered_by", "")).startswith("human:")
        and e["data"].get("takes_back") in names
    }


def cached(ticket):
    h = ticket.get("ext", {}).get("factory", {}).get("handover")
    return h if isinstance(h, dict) else None


def delegated(ticket):
    """True while this crew ticket's work happens at another workspace (its time is theirs, not counted here)."""
    h = cached(ticket)
    return h is not None and h.get("state") != NOT_NEEDED


# ---- bookkeeping -------------------------------------------------------------------------------------------


def _load(store):
    try:
        data = json.loads(store.read(FILE))
    except (FileNotFoundError, ValueError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(store, data):
    store.write(FILE, json.dumps(data).encode())


# ---- state from the relay ------------------------------------------------------------------------------------


def _group(root, crew_id):
    groups = orchcli.call(root, "relay", "group", "list")
    for g in groups.get("hosted", []) if isinstance(groups, dict) else []:
        if g.get("ticket") == crew_id:
            return g
    return None


def _group_tasks(root, crew_id):
    g = _group(root, crew_id)
    return [t for t in (g or {}).get("tasks", []) if isinstance(t, dict)]


def _only_member(root, crew_id, ws):
    """The group holds the receiving workspace and nobody else (besides this one): a file shared into it reaches only
    the workspace the person saw on the Start screen, and the task found there is the one sent to it."""
    g = _group(root, crew_id)
    members = {
        m.get("ws")
        for m in (g or {}).get("members", [])
        if isinstance(m, dict) and not m.get("host") and not m.get("left_at")
    }
    tasks = [t for t in (g or {}).get("tasks", []) if isinstance(t, dict)]
    if members != {ws} or not tasks or any(t.get("ws") != ws for t in tasks):
        raise Refused(
            "The group of this task has someone else in it, so no file was shared. "
            "Ask the owner whether to do it here instead.",
            "refused",
        )


def _card_clean(root, crew_id, t):
    """The hand-over card is built from the crew ticket: it must carry only the frozen brief (title; no summary, open
    question or checklist written since), so nothing an agent added after Start reaches the other workspace."""
    ticket = orchcli.ticket(root, crew_id)
    open_question = any(
        q.get("answer") is None and q.get("kind") is None for q in ticket.get("questions") or []
    )
    if (
        clean(ticket.get("title"), 200) != clean(t["title"], 200)
        or ticket.get("summary")
        or ticket.get("checklist")
        or open_question
    ):
        raise Refused(
            "The task card was changed after you pressed Start (summary, question or checklist). "
            "Nothing was sent. Ask the manager to reset the card to the plan.",
            "refused",
        )


def _set_cache(root, crew_id, **fields):
    for _ in range(2):
        ticket = orchcli.ticket(root, crew_id)
        now = dict(cached(ticket) or {})
        if all(now.get(k) == v for k, v in fields.items()):
            return
        try:
            orchcli.set_ext(root, ticket, handover={**now, **fields})
            return
        except Refused as error:
            if error.code != "conflict":
                raise


def relay_state(status):
    """A relay task status as the cached state. The relay's wait-for-the-other-side's-allow status is the only
    `waiting_*` besides `waiting_start`, and maps to `waiting_allow`. Anything unknown is None: the page shows it
    as unknown and the cache keeps its last state (fail closed, never a crash)."""
    if status in KNOWN:
        return status
    if isinstance(status, str) and status.startswith("waiting_") and status != "waiting_start":
        return "waiting_allow"
    return None


def state_of(root, crew, ws, delegate=None):
    """The relay task status of the delegate on this crew ticket, or None while it is not known."""
    mine = [t for t in _group_tasks(root, crew["id"]) if t.get("ws") == ws]
    if delegate:
        mine = [t for t in mine if t.get("delegate") == delegate] or mine
    state = mine[-1].get("status") if mine else None
    return relay_state(state)


# ---- crew start ---------------------------------------------------------------------------------------------


def _brief(d, t, h):
    p = d["proposal"]
    proves = [p["done_means"][i] for i in t.get("proves", []) if i < len(p["done_means"])]
    text = f"{clean(h['why'], 120)} Part of '{clean(p['title'], 80)}': {clean(p['goal'], 120)}"
    return text, [clean(x, 200) for x in proves][:20]


SCAN_MAX = 1024 * 1024  # `orch secret scan` takes at most 1 MB; core's group share scans a bigger file itself


def _read_file(root, rel):
    """The text of a hand-over file for the scanner (final path part opened without following a link)."""
    fd = os.open(Path(root).absolute() / rel, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise Refused(f"{clean(rel, None)} is not a file in this workspace. Nothing was sent.", "refused")
        data = stream.read(SCAN_MAX + 1)
    return None if len(data) > SCAN_MAX else data.decode("utf-8", "replace")


def scan_files(root, files):
    """The shared secret scanner (`orch secret scan`) over every file BEFORE anything leaves: a hit refuses the crew
    start with the scanner's own words. Core's group share scans again at share time (second line)."""
    for f in files:
        try:
            text = _read_file(root, f)
        except OSError:
            raise Refused(
                f"{clean(f, None)} is not a file in this workspace. Nothing was sent.", "refused"
            ) from None
        if text is None:
            continue
        try:
            orchcli.call(root, "secret", "scan", stdin=text)
        except Refused as error:
            if error.code == "too_large":
                continue
            raise Refused(f"{clean(f, None)}: {error} Nothing was sent.", error.code) from None


def start(root, store, d, t, crew, h):
    """`crew start` for a hand-over task. Safe to repeat: the delegate goes out once, each file once."""
    ws = h["workspace"]
    entry = workspace(root, ws)
    if entry is None:
        raise Refused(
            "That workspace cannot be handed tasks any more. Ask the owner to do it here instead.", "refused"
        )
    files = (h.get("sends") or {}).get("files", [])
    for f in files:
        if not _plain_file(root, f):
            raise Refused(
                f"{clean(f, None)} is not a file in this workspace any more. Nothing was sent.", "refused"
            )
    book = _load(store)
    mine = book.get(crew["id"]) or {}
    first = not mine.get("sent")
    starter = authority.who(d["start"]["q"]) if d.get("start") else ""
    if not starter.startswith("human:"):
        raise Refused(
            "A person has to press Start on this order before a task goes to another workspace.",
            "not_allowed",
        )
    if first:
        _card_clean(root, crew["id"], t)
        scan_files(root, files)  # nothing is sent when a file looks like a secret
        text, checks = _brief(d, t, h)
        sent = orchcli.call(
            root,
            "relay",
            "delegate",
            ws,
            clean(t["title"], 200),
            "--text",
            text,
            *[x for c in checks for x in ("--check", c)],
            "--ticket",
            crew["id"],
            "--group",
            write=True,
        )
        mine = {"sent": (sent.get("id") if isinstance(sent, dict) else None) or "sent", "shared": []}
        book[crew["id"]] = mine
        _save(store, book)  # before anything else: a second crew start never sends a second delegate
        _set_cache(root, crew["id"], ws=ws, name=clean(entry.get("name") or ws, 64), state="waiting_start")
    todo = [f for f in files if f not in mine["shared"]]
    if todo and not _group_tasks(root, crew["id"]):
        raise Refused(
            f"{clean(entry.get('name') or ws, 60)} could not join the group, so the files were not sent. "
            "The task itself went out. Ask the owner whether to do it here instead.",
            "refused",
        )
    for f in todo:
        _only_member(root, crew["id"], ws)
        # the click was the person's Start: recorded as the person who pressed it (no proof plumbing here)
        orchcli.call(root, "relay", "group", "share", crew["id"], f, "--click", write=True, by=starter)
        mine["shared"].append(f)
        _save(store, book)
    return {"ws": ws, "name": entry.get("name"), "sent": first, "files": list(mine["shared"])}


# ---- state, result, take back -------------------------------------------------------------------------------


def _undelivered(root, message):
    try:
        waiting = orchcli.call(root, "relay", "outbox").get("waiting", [])
    except Refused:
        return False
    return any(isinstance(m, dict) and m.get("id") == message for m in waiting)


def settle(root, store, d):
    """Bring every hand-over of a started order up to date: the cached state, the result of a finished one (evidence
    on the crew ticket, ticket done), and a taken-back one (the other side is told once). Returns
    ({task: state}, changed)."""
    states, changed = {}, False
    book = _load(store)
    back = taken_back(d)
    for h in d.get("proposal", {}).get("handovers", []):
        crew = d["crew"].get(h["task"])
        mine = book.get(crew["id"]) if crew else None
        if crew is None or not mine or not mine.get("sent"):
            continue
        shown = cached(crew) or {}
        if h["task"] in back:
            if not mine.get("told"):
                state = state_of(root, crew, h["workspace"], mine.get("sent"))
                if state not in ("done", "failed", "denied"):
                    # core has no way to take a message out of the outbox: an undelivered delegate is followed by
                    # the same text and is told in the same order (reported as a follow-up)
                    mine["undelivered"] = _undelivered(root, mine["sent"])
                    title = clean(crew.get("title") or h["task"], 120)
                    orchcli.call(
                        root, "relay", "group", "say", crew["id"], NO_LONGER.format(title=title), write=True
                    )
                mine["told"] = True
                _save(store, book)
                _set_cache(root, crew["id"], state=NOT_NEEDED)
                changed = True
            states[h["task"]] = NOT_NEEDED
            continue
        state = state_of(root, crew, h["workspace"], mine.get("sent")) or shown.get("state")
        if state is None:
            continue
        states[h["task"]] = state
        if shown.get("state") != state:
            _set_cache(root, crew["id"], state=state)
            changed = True
        if state == "done" and crew.get("status") != "done":
            who = clean(shown.get("name") or h["workspace"], 60)
            orchcli.call(
                root,
                "log",
                crew["id"],
                f"{who} reports it done: {clean(crew['title'], 120)}. Check the result before you rely on it.",
                write=True,
            )
            try:
                orchcli.call(root, "ticket", "status", crew["id"], "done", write=True)
            except Refused:
                orchcli.call(root, "log", crew["id"], "Factory could not mark this task done.", write=True)
            changed = True
    return states, changed
