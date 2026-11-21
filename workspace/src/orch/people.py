"""Who is working here: the person picked in the dashboard ("You: Severin"), and who a helper works for.

A name only, no password and no rights (attribution, not security). The pick is machine-local, in the orch
home (people.json, keyed by the workspace's real path); only the dashboard's person action writes it
(orch_dashboard.people). Every place that records a person reads it through this module:

  - a person at the terminal (no agent around) is `human:<pick>`, else `human:<computer login>`
    (tickets.current_actor);
  - a helper is `agent:<tool>`; its history lines carry `for: <person>` when a person started its run, and no
    `for` when it runs on its own (automation, factory, reviewer): shown as "Agent - <person>" and "Agent";
  - a new ticket's owner is that person by default (tickets.create).
"""

from __future__ import annotations

import getpass
import json
import os
import re
from pathlib import Path

_BAD = re.compile(r"[^A-Za-z0-9_.@ -]")
_bound: Path | None = None  # the workspace of this process (cli binds it once it found the root)


def bind(root: Path | None) -> None:
    global _bound
    _bound = Path(root) if root is not None else None


def bound() -> Path | None:
    if _bound is not None:
        return _bound
    env = os.environ.get("ORCH_ROOT")
    return Path(env) if env else None


def clean(value) -> str | None:
    """One short plain name (it ends up in human:<name>), or None."""
    name = " ".join(_BAD.sub("", value).split())[:40] if isinstance(value, str) else ""
    return name or None


def home_file() -> Path:
    from orch import addons

    return addons.home() / "people.json"


def key(root: Path) -> str:
    from orch.config import _perm_key

    return _perm_key(Path(root))


def chosen(root: Path | None = None) -> str | None:
    """The person picked in the dashboard for this workspace, or None (nobody picked, no usable orch home)."""
    root = root if root is not None else bound()
    if root is None:
        return None
    try:
        d = json.loads(home_file().read_text(encoding="utf-8"))
        return clean(d.get(key(root))) if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001 - no usable orch home: nobody picked
        return None


def login() -> str:
    try:
        return _BAD.sub("_", getpass.getuser())[:64]
    except Exception:  # noqa: BLE001
        return ""


def person_actor(root: Path | None = None, fallback: str = "user") -> str:
    """`human:<pick>`, else `human:<computer login>`, else `human:<fallback>`: a person acting here."""
    return "human:" + (chosen(root) or login() or fallback)


def _run_starter(root: Path) -> str | None:
    """The `by` of the run this process belongs to (ORCH_RUN / ORCH_TICKET), or None."""
    run, tid = os.environ.get("ORCH_RUN"), os.environ.get("ORCH_TICKET")
    if not run or not tid or not re.fullmatch(r"t_[a-z0-9]{6,16}", tid):
        return None
    from orch import runs

    rec = runs.read(root, tid)
    if not rec or rec.get("run") != run:
        return None
    by = rec.get("by")
    return by if isinstance(by, str) else ""


def acting_for(root: Path | None = None) -> str | None:
    """The person a helper in this process works for, or None when it runs on its own.

    A run orch started: the person who started it (its record's by is human:<name>); started by automation,
    factory, the reviewer or orch itself: nobody. A helper a person started by hand (no ORCH_RUN): the
    pick."""
    root = root if root is not None else bound()
    if root is None:
        return None
    try:
        by = _run_starter(Path(root))
    except Exception:  # noqa: BLE001 - an unreadable run record: nobody (never guess a person)
        return None
    if by is None:
        return None if os.environ.get("ORCH_RUN") else chosen(root)
    if by.startswith("human:") and len(by) > len("human:"):
        return clean(by[len("human:") :])
    return None


def owner_for(root: Path | None, by: str) -> str | None:
    """The default owner of a ticket made by `by`: the person picked in the dashboard when it is them
    (human:<pick>), or the person a helper works for. None when nobody is picked (a bare computer login or
    a word such as human:owner is no owner) or the helper runs on its own."""
    if not isinstance(by, str):
        return None
    if by.startswith("human:"):
        name = clean(by[len("human:") :])
        return name if name and name == chosen(root) else None
    if by.startswith("agent:"):
        return acting_for(root)
    return None
