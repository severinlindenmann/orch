"""Who is using this dashboard ("You: Anna"): a name only, no password and no rights, just who did what.

The list of names is kept in the workspace, .orch/run/dashboard/people.json (local, never synced; an agent may edit it,
it only lists names). WHO is chosen is machine-local under the orch home (people.json there, keyed by the workspace's real
path) and is only set by the dashboard's person action, so a file an agent writes cannot change who an action is recorded
as. No password, attribution only. The chosen person is the actor of everything done from this dashboard (`--by human:<name>`); with nobody chosen it stays the computer's user."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

MAX_PEOPLE = 20
_BAD = re.compile(r"[^A-Za-z0-9_.@ -]")


class BadName(ValueError):
    pass


def clean_name(value) -> str:
    """One short plain name; letters, digits, space and _ . @ - only (it ends up in `--by human:<name>`)."""
    name = " ".join(_BAD.sub("", value).split())[:40] if isinstance(value, str) else ""
    if not name:
        raise BadName("Type a name.")
    return name


def _path(root: Path) -> Path:
    return root / ".orch" / "run" / "dashboard" / "people.json"


def _read(root: Path) -> dict:
    try:
        d = json.loads(_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _home_file() -> Path:
    from orch import addons

    return addons.home() / "people.json"


def _key(root: Path) -> str:
    from orch.config import _perm_key

    return _perm_key(root)


def _chosen(root: Path):
    try:
        d = json.loads(_home_file().read_text(encoding="utf-8"))
        return d.get(_key(root)) if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001 - no usable orch home: nobody chosen
        return None


def _choose(root: Path, name: str) -> None:
    p = _home_file()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        d = d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        d = {}
    d[_key(root)] = name
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def load(root: Path | None) -> dict:
    """{"me": name or None, "people": [names]} (me is always in the list)."""
    d = _read(root) if root else {}
    people = []
    for n in d.get("people") if isinstance(d.get("people"), list) else []:
        try:
            n = clean_name(n)
        except BadName:
            continue
        if n not in people:
            people.append(n)
    me = _chosen(root) if root else None
    try:
        me = clean_name(me) if me is not None else None
    except BadName:
        me = None
    if me and me not in people:
        people.insert(0, me)
    return {"me": me, "people": people[:MAX_PEOPLE]}


def current(root: Path | None) -> str | None:
    return load(root)["me"]


def _write(root: Path, doc: dict) -> None:
    p = _path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def choose(root: Path, name, add: bool = False) -> dict:
    """Make `name` the person using this dashboard. `add`: a new name is allowed (Add person); otherwise the
    name must already be in the list."""
    name = clean_name(name)
    cur = load(root)
    if name not in cur["people"]:
        if not add:
            raise BadName("That person is not in the list.")
        if len(cur["people"]) >= MAX_PEOPLE:
            raise BadName("That is enough people for one workspace.")
        cur["people"].append(name)
    _write(root, {"people": cur["people"]})
    _choose(root, name)
    return load(root)
