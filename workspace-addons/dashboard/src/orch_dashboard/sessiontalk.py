"""The helper's real conversation for a Focus pane's Chat view (ORCH-2204, read-only).

orch reads the newest turns of the ticket's session in use from the tool's own saved conversation
(orch.session_history, where the adapter says it is); nothing is copied or stored. A tool that keeps no readable
conversation (or a file that is gone) answers {"available": false}: the Chat then shows the ticket's summary and
says so. orch's own notices to the helper (its start text, "New input on ...") are left out: the person's messages
come from the ticket, where orch keeps them. Each answer is kept while the file stays the same, so polling panes
read a long conversation only when it grew.
"""

from __future__ import annotations

from pathlib import Path

TURNS = 60  # turns returned, the newest
TEXT = 2000  # characters of one turn
_CACHE: dict[tuple, dict] = {}
_CACHE_MAX = 32
NONE = {"available": False, "turns": [], "more": False}


def _current(ticket: dict) -> tuple[str, str] | None:
    """(agent, session id) of the session in use: the newest one the ticket remembers."""
    from orch.session_ids import valid_session_id

    best = None
    for s in ticket.get("sessions") or []:
        if (
            not isinstance(s, dict)
            or not isinstance(s.get("agent"), str)
            or not valid_session_id(s.get("id"))
        ):
            continue
        if best is None or str(s.get("last_used") or "") > str(best.get("last_used") or ""):
            best = s
    return (best["agent"], best["id"]) if best else None


def _cut(text: str) -> str:
    return text if len(text) <= TEXT else text[: TEXT - 1].rstrip() + "…"


def talk(root: Path, tid: str) -> dict:
    """{"available": bool, "turns": [{w: "h"|"y", text, at}], "more": bool}, oldest first."""
    try:
        from orch import adapters, session_history, tickets
    except ImportError:
        return dict(NONE)
    try:
        cur = _current(tickets.load(root, tid))
        if cur is None:
            return dict(NONE)
        hit = adapters.history_file(cur[0], cur[1], root)
        if hit is None:
            return dict(NONE)
        st = hit[0].stat()
    except Exception:  # noqa: BLE001 - an unknown ticket or an odd file is simply no conversation
        return dict(NONE)
    key = (str(root), tid, *cur, st.st_mtime_ns, st.st_size)
    if key in _CACHE:
        return _CACHE[key]
    h = session_history.read(cur[0], cur[1], root=root, last=TURNS * 3)
    if not h["found"] or (h["more"] and not h["turns"]):  # gone, or too big to read
        return dict(NONE)
    turns = []
    for t in h["turns"]:
        if t["role"] == "user" and t["text"].startswith(session_history.ORCH_TYPED):
            continue
        turns.append({"w": "y" if t["role"] == "user" else "h", "text": _cut(t["text"]), "at": t.get("at")})
    out = {"available": True, "turns": turns[-TURNS:], "more": h["more"] or len(turns) > TURNS}
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = out
    return out
