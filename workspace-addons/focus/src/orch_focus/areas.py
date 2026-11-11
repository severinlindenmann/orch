"""Areas: where work happens (a folder, a single file or a process step). Agents suggest, a person accepts.

Stored in `.orch/addons/focus/areas.toml`:

    [[area]]
    id = "a1"
    name = "Offsite"
    path = "offsite/"
    state = "suggested"        # or "accepted"; only a click on the Focus page makes it accepted
    tickets = ["t_abc123"]     # tickets set to this area (`orch focus area set`)

Nothing here follows a symlink, reads outside `.orch/addons/focus`, or trusts the file: a bad file reads as
"no areas", a bad row is skipped. Paths are workspace-relative and never leave the workspace.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
import threading
import tomllib
from pathlib import Path

from . import runfiles

AREA_ID = re.compile(r"a[0-9]{1,4}")
TICKET = re.compile(r"t_[a-z0-9]{6,16}")
MAX_AREAS = 50
MAX_FILE = 64 * 1024
MAX_TICKETS = 200
STATES = ("suggested", "accepted")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f<>]")
_lock = threading.Lock()


class BadArea(ValueError):
    """The request does not make an area (plain words, shown to the person)."""


def _dir(root: Path, create: bool) -> Path:
    d = Path(root)
    for part in (".orch", "addons", "focus"):
        d = d / part
        if create and not runfiles.is_link(d):
            runfiles.mkdir_private(d, root)
        if runfiles.is_link(d) or (create and not d.is_dir()):
            raise BadArea("Focus cannot use its areas file here.")
    return d


def _file(root: Path, create: bool = False) -> Path:
    return _dir(root, create) / "areas.toml"


def clean_name(value) -> str:
    name = " ".join(str(value or "").split())
    if not 1 <= len(name) <= 40 or _CONTROL.search(name):
        raise BadArea("An area name is 1 to 40 characters.")
    return name


def clean_path(value) -> str:
    """A workspace-relative folder or file: no drive, no `..`, no absolute path, no control characters."""
    p = str(value or "").strip().replace("\\", "/")
    if not 1 <= len(p) <= 200 or _CONTROL.search(p) or p.startswith(("/", "~")) or re.match(r"[A-Za-z]:", p):
        raise BadArea("An area path is a folder or file inside this workspace.")
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts or ".." in parts or parts[0] == ".orch" or parts[0] == ".git":
        raise BadArea("An area path is a folder or file inside this workspace.")
    return "/".join(parts) + ("/" if p.endswith("/") else "")


def _row(raw) -> dict | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not AREA_ID.fullmatch(raw["id"]):
        return None
    try:
        name, path = clean_name(raw.get("name")), clean_path(raw.get("path"))
    except BadArea:
        return None
    state = (
        raw.get("state") if raw.get("state") in STATES else "suggested"
    )  # fail closed: never accepted by default
    tickets = [t for t in raw.get("tickets") or [] if isinstance(t, str) and TICKET.fullmatch(t)][
        :MAX_TICKETS
    ]
    return {"id": raw["id"], "name": name, "path": path, "state": state, "tickets": tickets}


def load(root: Path) -> list[dict]:
    try:
        p = _file(root)
        if p.is_symlink():
            return []
        fd = os.open(p, os.O_RDONLY | runfiles.NOFOLLOW)
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                return []
            doc = tomllib.loads(f.read(MAX_FILE).decode("utf-8"))
    except (OSError, ValueError, BadArea, UnicodeError, RecursionError):
        return []
    rows = (_row(r) for r in doc.get("area") or [] if isinstance(r, dict))
    seen: set[str] = set()
    out = []
    for r in rows:
        if r and r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return out[:MAX_AREAS]


def _q(text: str) -> str:
    """A TOML basic string (escapes backslash, quote and control characters; names/paths were already cleaned)."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _save(root: Path, areas: list[dict]) -> None:
    out = []
    for a in areas:
        out += [
            "[[area]]", f"id = {_q(a['id'])}", f"name = {_q(a['name'])}", f"path = {_q(a['path'])}",
            f"state = {_q(a['state'])}", "tickets = [" + ", ".join(_q(t) for t in a["tickets"]) + "]", "",
        ]  # fmt: skip
    p = _file(root, create=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".toml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    os.replace(tmp, p)


def _next_id(areas: list[dict]) -> str:
    used = {int(a["id"][1:]) for a in areas}
    return "a" + str(next(n for n in range(1, MAX_AREAS + 2) if n not in used))


def add(root: Path, name, path) -> dict:
    """A new area, always `suggested`: an agent or the CLI can only suggest. Same name and path again: that area."""
    name, path = clean_name(name), clean_path(path)
    with _lock:
        areas = load(root)
        for a in areas:
            if a["path"] == path or a["name"].lower() == name.lower():
                return a
        if len(areas) >= MAX_AREAS:
            raise BadArea("There are already too many areas. Remove one first.")
        area = {"id": _next_id(areas), "name": name, "path": path, "state": "suggested", "tickets": []}
        _save(root, [*areas, area])
        return area


def _find(areas: list[dict], area_id) -> dict:
    for a in areas:
        if a["id"] == area_id:
            return a
    raise BadArea("There is no such area.")


def accept(root: Path, area_id) -> dict:
    """Only the Focus page calls this (a person's click)."""
    with _lock:
        areas = load(root)
        a = _find(areas, area_id)
        a["state"] = "accepted"
        _save(root, areas)
        return a


def remove(root: Path, area_id) -> None:
    with _lock:
        areas = load(root)
        a = _find(areas, area_id)
        _save(root, [x for x in areas if x is not a])


def set_ticket(root: Path, ticket, area_ref) -> dict:
    """Put a ticket in an area (by id or by name); a ticket is in one area at most."""
    if not isinstance(ticket, str) or not TICKET.fullmatch(ticket):
        raise BadArea("That is not a ticket.")
    with _lock:
        areas = load(root)
        want = str(area_ref or "").strip().lower()
        a = next((x for x in areas if x["id"] == want or x["name"].lower() == want), None)
        if a is None:
            raise BadArea("There is no such area.")
        for x in areas:
            x["tickets"] = [t for t in x["tickets"] if t != ticket]
        a["tickets"] = [*a["tickets"], ticket][-MAX_TICKETS:]
        _save(root, areas)
        return a


def strip(root: Path, live: list[dict]) -> list[dict]:
    """The areas for the page. `who` = the agents of live cards whose ticket is in the area; `quiet` = none."""
    out = []
    for a in load(root):
        who = sorted({c["agent"] for c in live if c["ticket"] in a["tickets"]})
        out.append({**{k: a[k] for k in ("id", "name", "path", "state")}, "who": who, "quiet": not who})
    return out
