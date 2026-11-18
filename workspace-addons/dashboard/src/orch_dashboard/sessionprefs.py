"""Pins and own names of sessions in the new Focus (ORCH-361, draft D).

Kept in the workspace, .orch/run/dashboard/sessions.json, so every browser and every reload of this workspace's
dashboard shows the same pins and names (issue 1351: the browser kept them per port). Local, never synced; it holds
only session ids, a pin choice and a short name. Written only by the dashboard's session.pin and session.name ops.

    {"pins": {"t_7k3f9q": true, "t_manager1": false}, "names": {"t_7k3f9q": "Price list"}}

A session without a ticket (kind empty, chat, terminal, manager; ORCH-364) is pinned until the person unpins it, so
only a choice is stored, never the default. GET /api/sessions adds "pinned" and "name" to every session.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

NAME_MAX = 60  # the draft's input has maxlength 60
KEEP = 400  # choices kept per kind; the oldest go first
SID = re.compile(r"t_[a-z0-9]{6,16}")
_LOCK = threading.Lock()


class BadPref(ValueError):
    pass


def _path(root: Path) -> Path:
    return root / ".orch" / "run" / "dashboard" / "sessions.json"


def read(root: Path) -> dict:
    """{"pins": {id: bool}, "names": {id: str}}; a missing or broken file is empty."""
    try:
        d = json.loads(_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    pins = d.get("pins") if isinstance(d.get("pins"), dict) else {}
    names = d.get("names") if isinstance(d.get("names"), dict) else {}
    return {
        "pins": {k: v for k, v in pins.items() if SID.fullmatch(str(k)) and isinstance(v, bool)},
        "names": {
            k: clean_name(v)
            for k, v in names.items()
            if SID.fullmatch(str(k)) and isinstance(v, str) and clean_name(v)
        },
    }


def clean_name(value) -> str:
    """One line of at most NAME_MAX characters; empty means "use the title"."""
    if not isinstance(value, str):
        return ""
    return "".join(c for c in " ".join(value.split()) if c.isprintable()).strip()[:NAME_MAX]


def _sid(value) -> str:
    if not isinstance(value, str) or not SID.fullmatch(value):
        raise BadPref("Choose a session.")
    return value


def _write(root: Path, d: dict) -> None:
    p = _path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _keep(m: dict, sid: str, value) -> dict:
    m = {k: v for k, v in m.items() if k != sid}
    if value is not None:
        m[sid] = value  # newest last, so the oldest choices fall away first
    return dict(list(m.items())[-KEEP:])


def set_pin(root: Path, sid, pinned) -> dict:
    """Pin or unpin one session; returns the stored choices."""
    sid = _sid(sid)
    if not isinstance(pinned, bool):
        raise BadPref("Say pin or unpin.")
    with _LOCK:
        d = read(root)
        d["pins"] = _keep(d["pins"], sid, pinned)
        _write(root, d)
    return d


def set_name(root: Path, sid, name) -> dict:
    """Give one session its own name; an empty name (or the title itself) goes back to the title."""
    sid = _sid(sid)
    if name is not None and not isinstance(name, str):
        raise BadPref("Type a name.")
    with _LOCK:
        d = read(root)
        d["names"] = _keep(d["names"], sid, clean_name(name) or None)
        _write(root, d)
    return d


def apply(root: Path, sessions: list[dict]) -> list[dict]:
    """Add "pinned" and "name" to every session: the stored choice, else pinned for a session without a ticket."""
    d = read(root)
    for s in sessions:
        sid = s.get("id")
        choice = d["pins"].get(sid)
        s["pinned"] = choice if isinstance(choice, bool) else bool(s.get("kind"))
        name = d["names"].get(sid) or ""
        s["name"] = name if name and name != s.get("title") else None
    return sessions
