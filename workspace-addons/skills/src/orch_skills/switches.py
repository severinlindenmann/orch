"""Turn off / Turn on, for this workspace only. Two kinds of place, nothing is moved or deleted:

1. `.orch/skills-off.json` (orch.skills-off/1, read by the core's linking): orch's own skills and the admin's shared
   skills are links orch makes; a name on this list is not linked (the files stay).
2. Each helper tool's own per-folder settings file, as the core's tool data describes it (agents/switches.json,
   `adapters.folder_switches()`; jsonswitch.py and tomlswitch.py write them). orch writes only the entries it records
   in `.orch/addons/skills/owned.json` and removes only those; everything else in the file stays as it is. An entry
   somebody wrote by hand is shown as off and is not changed by orch.

Every file is reached only through real folders inside the workspace (a link anywhere on the way is refused), is
replaced through a fresh temporary file next to it, and a settings file is replaced only when nobody changed it
since it was read (an editor or the tool saving at the same moment wins; orch asks to try again).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

from . import adapters

OFF_SCHEMA = "orch.skills-off/1"
OWNED_SCHEMA = "orch.skills-owned/2"
OWNED = Path(".orch") / "addons" / "skills" / "owned.json"
LOCK = Path(".orch") / "addons" / "skills" / ".lock"
MAX_BYTES = 1024 * 1024


class Refused(Exception):
    """A plain-words refusal (exit 2)."""


def safe_id(name: str) -> str:
    """A name as one plain token: letters, digits, dashes and underscores stay, anything else becomes _."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def _is_link(p: Path) -> bool:
    try:
        return p.is_symlink() or bool(getattr(os.lstat(p), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def safe_path(root: Path, rel: Path) -> Path:
    """root/rel when no part of the way (the folders and the file) is a link; else refused."""
    p = Path(root)
    for part in Path(rel).parts:
        if part in ("", ".", ".."):
            raise Refused("That path is not inside this workspace.")
        p = p / part
        if _is_link(p):
            raise Refused(f"{p.relative_to(root)} is a link; orch will not write through it. Nothing was changed.")
    return p


def _read(root: Path, rel: Path) -> tuple[dict, bytes | None]:
    """(object, the exact bytes read or None when missing). A file that is not a JSON object is refused."""
    path = safe_path(root, rel)
    if not path.exists():
        return {}, None
    try:
        if path.stat().st_size > MAX_BYTES:
            raise Refused(f"{rel} is too big to change safely. Nothing was changed.")
        raw = path.read_bytes()
        doc = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise Refused(f"{rel} is not readable JSON. Fix it first; nothing was changed.") from None
    if not isinstance(doc, dict):
        raise Refused(f"{rel} is not a settings object. Fix it first; nothing was changed.")
    return doc, raw


def _write(root: Path, rel: Path, doc: dict | str, expect: bytes | None | bool = True) -> None:
    """Replace root/rel through a fresh temporary file (an object as JSON, a str as it is). With expect (bytes, or
    None = must still be missing) the file is replaced only when it still holds exactly that."""
    path = safe_path(root, rel)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    safe_path(root, rel)  # the folders just made are real folders too
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="" if isinstance(doc, str) else None) as f:
            f.write(doc if isinstance(doc, str) else json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        if expect is not True:
            now = path.read_bytes() if path.exists() else None
            if now != expect:
                raise Refused(f"{rel} was changed by someone else just now. Try again.")
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


@contextlib.contextmanager
def _locked(root: Path, wait: float = 5.0):
    """One change at a time from orch in this workspace (two dashboard tabs, a helper and the page)."""
    lock = safe_path(root, LOCK)
    lock.parent.mkdir(parents=True, exist_ok=True)
    safe_path(root, LOCK)
    end = time.monotonic() + wait
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
            break
        except FileExistsError:
            with contextlib.suppress(OSError):
                if time.time() - lock.stat().st_mtime > 30:  # left by a process that died
                    lock.unlink()
                    continue
            if time.monotonic() > end:
                raise Refused("Another change is being saved. Try again in a moment.") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            lock.unlink()


# ---- 1. the core's off list -------------------------------------------------------------------------------


def set_linked(root: Path, name: str, on: bool) -> bool:
    """Put a skill name on or off the core's off list and let the core relink. True when it changed."""
    from orch import skills

    if name in skills.ALWAYS_ON and not on:
        raise Refused(f"{name} is always on: helpers need it to work tickets.")
    with _locked(root):
        doc, raw = _read(root, skills.OFF_FILE)
        names = set(skills.off_names(root)) if doc else set()
        before = set(names)
        (names.discard if on else names.add)(name)
        if names != before:
            _write(root, skills.OFF_FILE, {"schema": OFF_SCHEMA, "skills": sorted(names)}, expect=raw)
    if names == before:
        return False
    skills.apply_agent_files(root)  # links go (or come back) at once; an orch update keeps them that way
    return True


# ---- 2. what orch wrote into the tools' own settings -------------------------------------------------------


def _owned(root: Path) -> dict[str, dict[str, list[str]]]:
    """{tool: {switch kind: [entries orch wrote]}}."""
    try:
        doc, _ = _read(root, OWNED)
    except Refused:
        doc = {}
    if doc.get("schema") != OWNED_SCHEMA or not isinstance(doc.get("tools"), dict):
        return {}
    out: dict[str, dict[str, list[str]]] = {}
    for tool, kinds in doc["tools"].items():
        if isinstance(tool, str) and isinstance(kinds, dict):
            out[tool] = {
                k: [e for e in v if isinstance(e, str)]
                for k, v in kinds.items()
                if isinstance(k, str) and isinstance(v, list)
            }
    return out


def owned(root: Path, tool: str, kind: str) -> list[str]:
    return list(_owned(root).get(tool, {}).get(kind, []))


def set_owned(root: Path, tool: str, kind: str, entries: list[str]) -> None:
    doc = _owned(root)
    doc.setdefault(tool, {})[kind] = sorted(set(entries))
    _write(root, OWNED, {"schema": OWNED_SCHEMA, "tools": doc})
