"""Earlier chat sessions of a ticket: list them and read one back as plain turns (read-only).

The ticket already remembers each helper session (tickets.record_session). The conversation itself stays in
the tool's own folder; this module only reads it: Claude keeps <home>/projects/<folder>/<id>.jsonl, Codex
keeps <home>/sessions/Y/M/D/rollout-...-<id>.jsonl. Nothing is written, copied or sent anywhere. A tool whose
conversation cannot be found (or keeps none, like a generic command) answers "not found".
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from orch.session_ids import valid_session_id

MAX_TURNS = 400  # turns returned for one session
MAX_TEXT = 4000  # characters kept of one turn
MAX_BYTES = 20 * 1024 * 1024  # a larger file is not read
_SKIP_START = ("<system-reminder", "<command-", "<local-command", "Caveat:", "<user-prompt-submit-hook")


def _home(env: dict, var: str, default: str) -> Path:
    return Path(env.get(var) or Path(env.get("HOME") or Path.home()) / default)


def find_file(agent: str, sid: str, environ: dict | None = None) -> Path | None:
    """The tool's saved conversation file for this session id, or None."""
    if not valid_session_id(sid):
        return None
    env = dict(os.environ if environ is None else environ)
    try:
        if agent == "claude":
            base = _home(env, "CLAUDE_CONFIG_DIR", ".claude") / "projects"
            for d in base.iterdir():
                f = d / f"{sid}.jsonl"
                if d.is_dir() and not d.is_symlink() and f.is_file() and not f.is_symlink():
                    return f
        elif agent == "codex":
            base = _home(env, "CODEX_HOME", ".codex") / "sessions"
            for f in base.glob(f"*/*/*/rollout-*-{sid}.jsonl"):
                if f.is_file() and not f.is_symlink():
                    return f
    except OSError:
        return None
    return None


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


def _claude_turn(ev: dict) -> dict | None:
    if ev.get("type") not in ("user", "assistant") or ev.get("isSidechain") or ev.get("isMeta"):
        return None
    m = ev.get("message")
    if not isinstance(m, dict):
        return None
    role = "user" if ev["type"] == "user" else "helper"
    return _turn(role, _text(m.get("content")), ev.get("timestamp"))


def _codex_turn(ev: dict) -> dict | None:
    p = ev.get("payload")
    if ev.get("type") != "response_item" or not isinstance(p, dict) or p.get("type") != "message":
        return None
    role = {"user": "user", "assistant": "helper"}.get(p.get("role"))
    return _turn(role, _text(p.get("content")), ev.get("timestamp")) if role else None


def read(agent: str, sid: str, environ: dict | None = None) -> dict:
    """{found, turns[{role: user|helper, text, at}], more} of one session (found False: file gone)."""
    f = find_file(agent, sid, environ)
    if f is None:
        return {"found": False, "turns": [], "more": False}
    pick = _claude_turn if agent == "claude" else _codex_turn
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


def sessions(ticket: dict, environ: dict | None = None) -> list[dict]:
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
        h = read(agent, sid, environ)
        first = next((t["text"] for t in h["turns"] if t["role"] == "user"), "")
        out.append(
            {
                "agent": agent,
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
