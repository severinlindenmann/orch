"""Sign-in state of connected services, as the helper tool itself reports it (ORCH-842).

A tool keeps a service's web sign-in in its own store; orch cannot read it from a file. The core already asks the
tool through its own list command (tool data `connection_check`, health.py) and reads only each service's state
word. That command starts every service's program, so it runs only when a person presses "Check sign-in", never
on a page load. The answer is kept in `.orch/addons/skills/signin.json` with its time (names and states only). The
sign-in itself happens in the tool; orch cannot do it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import switches
from .switches import Refused

CACHE = Path(".orch") / "addons" / "skills" / "signin.json"
SCHEMA = "orch.skills-signin/1"
WORDS = {"needs authentication": "needs-sign-in", "failed": "failed", "connected": "connected"}
TEXT = {
    "connected": "Signed in and working (checked {at})",
    "needs-sign-in": "Needs a sign-in. {how} (checked {at})",
    "failed": "Could not reach it (checked {at})",
}


def checker(tools_here: dict[str, dict]) -> tuple[str, dict] | None:
    """The first tool used here that can report sign-ins: (name, tool)."""
    for name, tool in tools_here.items():
        if isinstance(tool.get("connection_check"), dict) and tool.get("binary"):
            return name, tool
    return None


def read(root: Path) -> dict:
    """{"checked_at": str | None, "servers": {name: state}} (never raises)."""
    try:
        doc, _ = switches._read(root, CACHE)
    except Refused:
        doc = {}
    if doc.get("schema") != SCHEMA or not isinstance(doc.get("servers"), dict):
        return {"checked_at": None, "servers": {}}
    servers = {k: v for k, v in doc["servers"].items() if isinstance(k, str) and v in TEXT}
    return {"checked_at": doc.get("checked_at") if isinstance(doc.get("checked_at"), str) else None, "servers": servers}


def check(root: Path, now: str, tool: dict, names: list[str]) -> dict:
    """Ask the tool once (through the core) and keep the answer. Refused when it is not installed or says nothing."""
    from orch import health

    label = tool["label"]
    exe = shutil.which(tool["binary"])
    if not exe:
        raise Refused(f"{label} is not installed on this computer, so orch cannot ask it about the sign-in state.")
    says = health._conn_states(Path(root), exe, tool["connection_check"]["list"], names)
    if names and not says:
        raise Refused(
            f"{label} reported no service as connected, needing a sign-in or failed. It may still wait for you "
            f"to allow them: start {label} in this folder once, then check again."
        )
    doc = {"schema": SCHEMA, "checked_at": now, "servers": {n: WORDS[w] for n, w in says.items() if w in WORDS}}
    with switches._locked(root):
        switches._write(root, CACHE, doc)
    return doc


def how(tool: dict | None, name: str) -> str:
    sign_in = ((tool or {}).get("connection_check") or {}).get("sign_in")
    return sign_in.format(name=name) if sign_in else "Sign in again in your helper tool."


def text(state: str, at: str | None, tool: dict | None, name: str) -> str:
    return TEXT[state].format(at=(at or "")[:16].replace("T", " "), how=how(tool, name).rstrip("."))
