"""Earlier chat sessions of a ticket: list them and read one back as plain turns (read-only).

The ticket already remembers each helper session (tickets.record_session). The conversation itself stays in
the tool's own folder; this module only reads it, where the adapter says it is (adapters.history_file).
Nothing is written, copied or sent anywhere. A tool whose conversation cannot be found (or keeps none, like a
generic command) answers "not found".
"""

from __future__ import annotations

import json
from pathlib import Path

from orch import adapters
from orch.session_ids import valid_session_id

MAX_TURNS = 400  # turns returned for one session
MAX_TEXT = 4000  # characters kept of one turn
MAX_BYTES = 20 * 1024 * 1024  # a larger file is not read
_SKIP_START = ("<system-reminder", "<command-", "<local-command", "Caveat:", "<user-prompt-submit-hook")


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


def read(agent: str, sid: str, environ: dict | None = None, root: Path | None = None) -> dict:
    """{found, turns[{role: user|helper, text, at}], more} of one session (found False: file gone)."""
    hit = adapters.history_file(agent, sid, root, environ)
    if hit is None:
        return {"found": False, "turns": [], "more": False}
    f, lines = hit
    pick = _chat_turn if lines == "chat" else _items_turn
    turns: list[dict] = []
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
                    if len(turns) >= MAX_TURNS:
                        more = True
                        break
                    turns.append(t)
    except OSError:
        return {"found": False, "turns": [], "more": False}
    return {"found": True, "turns": turns, "more": more}


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
        first = next((t["text"] for t in h["turns"] if t["role"] == "user"), "")
        out.append(
            {
                "agent": agent,
                "label": _label(agent, root),
                "id": sid,
                "host": s.get("host"),
                "last_used": s.get("last_used"),
                "title": " ".join(first.split())[:100],
                "turns": len(h["turns"]),
                "readable": h["found"],
                "current": bool(s.get("current")),
            }
        )
    out.sort(key=lambda x: x.get("last_used") or "", reverse=True)
    return out


def _label(agent: str, root: Path | None) -> str:
    try:
        return adapters.load(agent, root)["label"]
    except Exception:  # noqa: BLE001 - an agent that is gone still shows under its name
        return agent
