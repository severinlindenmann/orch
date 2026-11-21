"""The permission mode a session without a ticket starts in (ORCH-818): the Manager, the Empty helper and the
Chat helper. The Start choice offers the tool's own modes (the adapter's permission_choices: Default, Accept
edits, Auto, Bypass permissions, or a tool's ORCH-604 levels), within what the workspace allows.

- The ladder: ask < edits < auto < full. workspace.permissions (config.permissions: ask | auto | full) is both
  the default and the most a session may get here; a mode above it is refused.
- The choice is remembered per session kind, on this machine in the orch home (never in the workspace, like
  permissions.json), and every later start of that session (`orch run start`, the idle close, tend) uses it.
- Raising a session above its remembered mode (or above the workspace default when nothing is remembered)
  needs the signed-in person: the dashboard's one-time person grant (ownerpick.person_granted). A helper's
  shell, a script or a phone without the owner's sign-in may keep or lower it, never raise it.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from orch import adapters, config
from orch.errors import Refused

MODES = ("ask", "edits", "auto", "full")
RANK = {m: i for i, m in enumerate(MODES)}
KINDS = ("manager", "empty", "chat")  # the plain terminal runs no tool
# a hidden ticket's kind (tickets.hidden_kind) -> the session kind here
_FROM_HIDDEN = {"manager": "manager", "empty": "empty", "general": "chat"}
WORDS = {"ask": "Default", "edits": "Accept edits", "auto": "Auto", "full": "Bypass permissions"}
FULL_KEY = "_full_warned"

NOT_ALLOWED = (
    "{label} is not allowed in this workspace. A person can allow it in Settings "
    "(orch config set workspace.permissions full)."
)
NEEDS_PERSON = (
    "Only the signed-in person can raise the {title} to {label}: start it from the dashboard. "
    "Nothing was started."
)


def kind_of(ticket: dict) -> str | None:
    from orch import tickets

    return _FROM_HIDDEN.get(tickets.hidden_kind(ticket) or "")


def most(root: Path) -> str:
    """The most a session may get here: the workspace setting (ask | auto | full)."""
    return config.permissions(root)


def allowed(root: Path, mode: str) -> bool:
    return mode in RANK and RANK[mode] <= RANK[most(root)]


def _file() -> Path:
    from orch import addons

    return addons.home() / "session-modes.json"


def _read_all() -> dict:
    try:
        doc = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _mine(root: Path) -> dict:
    v = _read_all().get(config._perm_key(root))  # noqa: SLF001 - the same per-workspace key as permissions.json
    return v if isinstance(v, dict) else {}


def _write_mine(root: Path, mine: dict) -> None:
    doc = _read_all()
    doc[config._perm_key(root)] = mine  # noqa: SLF001
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(doc, indent=1).encode("utf-8"))
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


def remembered(root: Path, kind: str) -> str | None:
    v = _mine(root).get(kind)
    return v if v in RANK else None


def current(root: Path, kind: str) -> str:
    """The mode this session kind starts in now: its remembered choice, capped at what the workspace allows;
    else the workspace setting."""
    top = most(root)
    v = remembered(root, kind)
    if v is None or RANK[v] > RANK[top]:
        return top
    return v


def full_warned(root: Path) -> bool:
    return _mine(root).get(FULL_KEY) is True


def resolve(root: Path, kind: str, wanted: str | None, person: bool) -> str:
    """The mode a start of this session kind may use. wanted None: the current one. Refused above what the
    workspace allows, and when it raises the session without the signed-in person."""
    if kind not in KINDS:
        raise Refused(f"The {kind} has no permission mode.")
    base = current(root, kind)
    if wanted is None:
        return base
    if wanted not in RANK:
        raise Refused(f"'{wanted}' is not a permission mode. Pick one of: {', '.join(MODES)}.")
    if not allowed(root, wanted):
        raise Refused(NOT_ALLOWED.format(label=WORDS[wanted]))
    if RANK[wanted] > RANK[base] and not person:
        from orch import sessions

        raise Refused(NEEDS_PERSON.format(title=sessions.TITLES[kind], label=WORDS[wanted]))
    return wanted


def remember(root: Path, kind: str, mode: str) -> None:
    """Keep the choice for this session kind; the first Bypass permissions start marks the warning as seen."""
    mine = dict(_mine(root))
    if mine.get(kind) == mode and (mode != "full" or mine.get(FULL_KEY) is True):
        return
    mine[kind] = mode
    if mode == "full":
        mine[FULL_KEY] = True
    _write_mine(root, mine)


def for_ticket(root: Path, ticket: dict) -> str | None:
    """The mode a start of this hidden ticket uses (runs.plan), None for any other ticket (the workspace
    setting, as before)."""
    kind = kind_of(ticket)
    return current(root, kind) if kind else None


def tool_mode(name: str, mode: str, root: Path | None = None) -> str:
    """The adapter's own mode for an orch mode: the highest of the tool's choices at or below it (a tool
    without Accept edits gets its level below). A tool without choices keeps the mode."""
    ch = [c["mode"] for c in choices_for(name, root)]
    if not ch or mode in ch:
        return mode
    below = [m for m in ch if RANK[m] <= RANK[mode]]
    return max(below, key=RANK.__getitem__) if below else mode  # never a choice above the allowed mode


def choices_for(name: str, root: Path | None = None) -> list[dict]:
    """The tool's modes for the Start choice: [{mode, label}] from the adapter's permission_choices."""
    out = []
    for c in adapters.load(name, root).get("permission_choices") or []:
        if isinstance(c, dict) and c.get("mode") in RANK:
            out.append({"mode": c["mode"], "label": str(c.get("label") or WORDS[c["mode"]])})
    return out


def label(name: str, mode: str, root: Path | None = None) -> str:
    """The mode in words for the pane header, in the tool's own words."""
    m = tool_mode(name, mode, root)
    for c in choices_for(name, root):
        if c["mode"] == m:
            return c["label"]
    return WORDS.get(m, m)


def offer(root: Path, kind: str, name: str | None = None) -> dict:
    """What the Start choice shows for this session kind: {current, label, choices: [{mode, label, allowed}],
    full_warned}."""
    name = name or adapters.chosen(root)
    cur = tool_mode(name, current(root, kind), root)
    return {
        "current": cur,
        "label": label(name, cur, root),
        "choices": [{**c, "allowed": allowed(root, c["mode"])} for c in choices_for(name, root)],
        "full_warned": full_warned(root),
    }
