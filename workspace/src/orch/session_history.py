"""Earlier chat sessions of a ticket: list them, read one back as plain turns, and reopen one.

The ticket remembers each helper session, the last tickets.SESSIONS_KEPT per ticket (tickets.record_session).
The conversation itself stays in the tool's own folder; this module only reads it, where the adapter says it
is (adapters.history_file). Nothing is copied or sent anywhere. A tool whose conversation cannot be found (or
keeps none, like a generic command) answers "not found".

Reopen (`reopen`) only changes which remembered id the next start of the helper continues; it starts nothing
itself. `orch run start <ticket> --session <id>` reopens and starts in one step.
"""

from __future__ import annotations

import json
import os
from collections import deque
from pathlib import Path

from orch import adapters
from orch.session_ids import valid_session_id

MAX_TURNS = 400  # turns returned for one session
MAX_TEXT = 4000  # characters kept of one turn
MAX_BYTES = 20 * 1024 * 1024  # a larger file is not read
_SKIP_START = ("<system-reminder", "<command-", "<local-command", "Caveat:", "<user-prompt-submit-hook")
# what orch types (or the tool writes) as a "user" line by itself: its notices, the task text of a start, the
# summary after the conversation was compacted. Never a person's words, so never a session's title.
ORCH_TYPED = (
    "Your task for orch ticket ",
    "New input on orch ticket ",
    "Work on orch ticket ",
    "This session is being continued from a previous conversation",
)
TITLE_MAX = 100


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") in ("text", "input_text", "output_text"):
                parts.append(str(b.get("text") or ""))
        return "\n".join(p for p in parts if p)
    return ""


def _turn(role: str, text: str, at) -> dict | None:
    text = text.strip()
    if not text or (role == "user" and text.startswith(_SKIP_START)):
        return None
    return {"role": role, "text": text[:MAX_TEXT], "at": at if isinstance(at, str) else None}


def _chat_turn(ev: dict) -> dict | None:
    if ev.get("type") not in ("user", "assistant") or ev.get("isSidechain") or ev.get("isMeta"):
        return None
    m = ev.get("message")
    if not isinstance(m, dict):
        return None
    role = "user" if ev["type"] == "user" else "helper"
    return _turn(role, _text(m.get("content")), ev.get("timestamp"))


def _items_turn(ev: dict) -> dict | None:
    p = ev.get("payload")
    if ev.get("type") != "response_item" or not isinstance(p, dict) or p.get("type") != "message":
        return None
    role = {"user": "user", "assistant": "helper"}.get(p.get("role"))
    return _turn(role, _text(p.get("content")), ev.get("timestamp")) if role else None


def read(agent: str, sid: str, environ: dict | None = None, root: Path | None = None, last: int = 0) -> dict:
    """{found, turns[{role: user|helper, text, at}], more} of one session (found False: file gone).
    `last` > 0 keeps the newest `last` turns instead of the first MAX_TURNS (the Focus chat, ORCH-2204);
    `more` then says older turns were left out."""
    hit = adapters.history_file(agent, sid, root, environ)
    if hit is None:
        return {"found": False, "turns": [], "more": False}
    f, lines = hit
    pick = _chat_turn if lines == "chat" else _items_turn
    turns: list[dict] | deque = deque(maxlen=last) if last > 0 else []
    seen = 0
    more = False
    try:
        if f.stat().st_size > MAX_BYTES:
            return {"found": True, "turns": [], "more": True}
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                t = pick(ev) if isinstance(ev, dict) else None
                if t:
                    if not last and len(turns) >= MAX_TURNS:
                        more = True
                        break
                    seen += 1
                    turns.append(t)
    except OSError:
        return {"found": False, "turns": [], "more": False}
    if last > 0:
        more = seen > last
    return {"found": True, "turns": list(turns), "more": more}


def sessions(ticket: dict, environ: dict | None = None, root: Path | None = None) -> list[dict]:
    """The ticket's recorded sessions, newest first, each with its first line."""
    out = []
    entries = []
    for s in ticket.get("sessions") or []:
        entries.append({**s, "current": True})
        entries += [{**e, "agent": s.get("agent"), "host": s.get("host")} for e in s.get("earlier") or []]
    for s in entries:
        sid, agent = s.get("id"), s.get("agent")
        if not valid_session_id(sid) or not isinstance(agent, str):
            continue
        h = read(agent, sid, environ, root)
        out.append(
            {
                "agent": agent,
                "label": _label(agent, root),
                "id": sid,
                "host": s.get("host"),
                "last_used": s.get("last_used"),
                "title": _title(h["turns"], ticket, h["more"]),
                "turns": len(h["turns"]),
                "readable": h["found"],
                "current": bool(s.get("current")),
                # a person can continue it on this computer (the one in use is continued by a plain start)
                "reopenable": h["found"] and not s.get("current"),
            }
        )
    out.sort(key=lambda x: x.get("last_used") or "", reverse=True)
    return out


def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())[:TITLE_MAX]


def _sec(at) -> str:
    """An ISO time cut to the second, so the tool's '...:43.065Z' and orch's '...:43Z' compare as text."""
    return at[:19] if isinstance(at, str) and len(at) >= 19 else ""


def _title(turns: list[dict], ticket: dict, more: bool = False) -> str:
    """A plain line for what a session did (ORCH-678): the first thing a person wrote in it; for a helper
    session, which only ever gets orch's own notices, the steps of the ticket it finished (or started) while
    the session ran (the newest one), else the ticket's title. Never orch's notice text with its ticket id
    and command."""
    person = next(
        (t["text"] for t in turns if t["role"] == "user" and not t["text"].startswith(ORCH_TYPED)), ""
    )
    if person:
        return _one_line(person)
    plain = _one_line(ticket.get("title") or "")
    times = [_sec(t.get("at")) for t in turns if _sec(t.get("at"))]
    if not times:
        return plain
    lo, hi = min(times), max(times)
    if more:  # only the first MAX_TURNS were read: the session went on after the last one we have
        hi = "~"
    done, doing = [], []
    for c in ticket.get("checklist") or []:
        if not isinstance(c, dict) or not str(c.get("text") or "").strip():
            continue
        if c.get("done"):
            # evidence of this session only: a step proved again later still belongs to this one
            ats = [
                a
                for e in c.get("evidence") or []
                if isinstance(e, dict) and lo <= (a := _sec(e.get("at"))) <= hi
            ]
            if ats:
                done.append((max(ats), c["text"]))
        elif c.get("state") == "doing" and lo <= _sec(c.get("at")) <= hi:
            doing.append(c["text"])
    steps = [t for _, t in sorted(done)] or doing
    return _one_line(steps[-1]) if steps else plain


def _label(agent: str, root: Path | None) -> str:
    try:
        return adapters.load(agent, root)["label"]
    except Exception:  # noqa: BLE001 - an agent that is gone still shows under its name
        return agent


def reopen(root: Path, tid: str, sid: str, by: str) -> dict:
    """Make the remembered session `sid` the one the next start of the helper continues. Only a person picks
    it, only while no helper works on the ticket, and only a conversation that is on this computer. Returns
    the session's row of `sessions` (its agent is the tool that must continue it)."""
    from orch import runs, tickets
    from orch.errors import Refused

    # a helper's own --by human:<x> counts for nothing: under an agent tool or inside a run it is the helper
    if not str(by or "").startswith("human:") or tickets.agent_tool() or os.environ.get("ORCH_RUN"):
        raise Refused("Only a person can pick the conversation a helper continues.")
    if not valid_session_id(sid):
        raise Refused("That is not a session id. List them: orch run history <ticket>")
    t = tickets.load(root, tid)
    rec = next((r for r in sessions(t, root=root) if r["id"] == sid), None)
    if rec is None:
        raise Refused("That session does not belong to this ticket. List them: orch run history <ticket>")
    run = runs.read(root, tid)
    if run and isinstance(run.get("pid"), int) and runs.state(run) == "alive":
        raise Refused("A helper is working on this ticket. Stop it first, then continue the other chat.")
    if not rec["readable"]:
        raise Refused("That conversation is not on this computer, so it cannot be continued.")
    if not rec["current"]:
        tickets.record_session(root, tid, rec["agent"], sid, runs.host())
    return rec
