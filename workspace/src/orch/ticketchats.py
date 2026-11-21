"""The list of ticket chats (team chat step 1, ORCH-1167): every ticket that has chat lines or an open
question, newest first, with its last line and an unread count per reader. `orch chat list` prints it; the
dashboard data carries it for the Chats page and the app's Ticket chats list.

One thread per ticket, keyed by the ticket id: the messages are the ticket's own history lines that carry
`chat_message: true` (tickets.add_history), so there is no second store. Unread needs no sign-in yet: a read
cursor per reader (the dashboard, a paired phone, the command line) is kept on this computer under .orch/run
(machine state, never synced); step 3 moves it to the person."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from orch import history, net, tickets
from orch.errors import Refused

READER_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
DEFAULT_READER = "you"
LAST_CLIP = 160
# Lines written before core put chat_message on every line (the same cut as the dashboard's
# mobile.is_chat_entry): only a person's dashboard line counts then; a later line without the flag never.
CHAT_FLAG_SINCE = "2026-11-08T14:15:00+00:00"


def _reads_path(root: Path) -> Path:
    return root / ".orch" / "run" / "chat-reads.json"


def _reader(reader: str | None) -> str:
    r = (reader or DEFAULT_READER).strip().lower()
    if not READER_RE.fullmatch(r):
        raise Refused("A reader is 1 to 40 lowercase letters, digits, - or _.")
    return r


def _when(at) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo is not None else None


def is_chat_line(e) -> bool:
    """A history line that is a chat message (the core's chat_message flag). A line from before the flag
    existed counts only when a person wrote it on the dashboard."""
    if not isinstance(e, dict) or not isinstance(e.get("text"), str) or not e["text"].strip():
        return False
    if "chat_message" in e:
        return e["chat_message"] is True
    at = _when(e.get("at"))
    if at is None or at >= datetime.fromisoformat(CHAT_FLAG_SINCE):
        return False
    return e.get("via") == tickets.PERSON_VIA and history.is_person_line(e)


def _open_questions(t: dict) -> list[dict]:
    return [
        q
        for q in t.get("questions") or []
        if isinstance(q, dict) and q.get("answer") is None and q.get("kind") in (None, "plain")
    ]


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= LAST_CLIP else text[: LAST_CLIP - 1].rstrip() + "…"


def reads(root: Path, reader: str | None = None) -> dict[str, dict]:
    """{ticket id: {"at": time read up to, "lines": chat lines seen}} for one reader."""
    d = net.read_json(_reads_path(root), {})
    mine = d.get(_reader(reader)) if isinstance(d, dict) else None
    out = {}
    for k, v in (mine or {}).items() if isinstance(mine, dict) else ():
        if isinstance(v, dict) and _when(v.get("at")) and isinstance(v.get("lines"), int) and v["lines"] >= 0:
            out[k] = {"at": v["at"], "lines": v["lines"]}
    return out


def _chat_lines(root: Path, t: dict) -> list[dict]:
    """The ticket's chat lines as shown, in history order (the order they were written)."""
    return [e for e in history.lines(root, t) if is_chat_line(e) and _when(e.get("at"))]


def _name(v) -> str | None:
    """A typed name as shown: cleaned again on reading (a ticket file may be edited by hand)."""
    try:
        return tickets.clean_by_name(v) if isinstance(v, str) else None
    except Refused:
        return None


def _row(root: Path, t: dict, mark: dict | None) -> dict | None:
    lines = _chat_lines(root, t)
    asks = [q for q in _open_questions(t) if isinstance(q.get("text"), str)]
    if not lines and not asks:
        return None
    # a question from before asked_at existed falls back to when the ticket was made: a fixed time, so a later
    # edit of the ticket never makes it new again
    events = [(_when(e["at"]), "line", e, i) for i, e in enumerate(lines)]
    events += [(_when(q.get("asked_at")) or _when(t.get("created_at")), "question", q, -1) for q in asks]
    events = [x for x in events if x[0] is not None]
    if not events:
        return None
    events.sort(key=lambda x: x[0])
    at, kind, last, _ = events[-1]
    read_at = _when(mark["at"]) if mark else None

    def new(x) -> bool:
        if mark is None:
            return True
        # a line counts by its place: times are whole seconds, so a line written in the second the reader
        # looked would hide behind the mark; a question counts by the time it was asked
        return x[3] >= mark["lines"] if x[1] == "line" else x[0] > read_at

    # unread: lines someone else wrote (a helper, a phone, a peer) and open questions after the reader's mark;
    # the person's own lines are never unread for them
    unread = sum(1 for x in events if new(x) and (x[1] == "question" or not history.is_person_line(x[2])))
    name = _name(last.get("by_name")) if kind == "line" else None
    return {
        "id": t["id"],
        "key": t.get("key") or t["id"],
        "title": t.get("title") or "",
        "status": t.get("status"),
        "last_at": at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last": {
            "kind": kind,
            "id": last.get("id"),  # a chat line's stable id, a question's q-id
            "by": last.get("by") if kind == "line" else None,
            # the typed name, shown as typed and "not signed in" (contracts/history.md, chat lines)
            **({"by_name": name} if name else {}),
            "text": _clip(last["text"]),
        },
        "lines": len(lines),
        "open_questions": len(asks),
        "unread": unread,
    }


def chats(root: Path, reader: str | None = None) -> list[dict]:
    """Every ticket with chat lines or an open question, newest first (last line or question), with an unread
    count for `reader`. Hidden tickets (the workspace Chat, Manager, sessions) are not ticket chats."""
    marks = reads(root, reader)
    out = []
    for t in tickets.list_all(root):
        row = _row(root, t, marks.get(t["id"]))
        if row:
            out.append(row)
    out.sort(key=lambda r: (r["last_at"], r["id"]), reverse=True)
    return out


def mark_read(root: Path, ref: str, reader: str | None = None, at: str | None = None) -> dict:
    """The reader has seen the ticket's chat up to now (or `at`): its unread count starts again from there."""
    r = _reader(reader)
    tid = tickets.resolve(root, ref)
    t = tickets.load(root, tid)
    if tickets.is_hidden(t):
        raise Refused("That is not a ticket chat.")
    when = _when(at) if at else datetime.now(UTC)
    if when is None:
        raise Refused("A time looks like 2026-11-21T08:00:00Z.")
    lines = _chat_lines(root, t)
    seen = len(lines) if not at else sum(1 for e in lines if _when(e["at"]) <= when)
    mark = {"at": when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "lines": seen}
    with tickets._locked(root, "chat-reads"):
        d = net.read_json(_reads_path(root), {})
        d = d if isinstance(d, dict) else {}
        mine = d.get(r) if isinstance(d.get(r), dict) else {}
        old = mine.get(t["id"]) if isinstance(mine.get(t["id"]), dict) else {}
        old_at, old_lines = _when(old.get("at")), old.get("lines") if isinstance(old.get("lines"), int) else 0
        mine[t["id"]] = {  # a mark never moves back
            "at": mark["at"] if old_at is None or when > old_at else old["at"],
            "lines": max(seen, old_lines),
        }
        d[r] = mine
        net.write_json(_reads_path(root), d)
    return {"ticket": t["id"], "key": t.get("key") or t["id"], "reader": r, "read_at": mine[t["id"]]["at"]}
