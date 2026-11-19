"""Turn off / Turn on, for this workspace only. Two places, nothing is moved or deleted:

1. `.orch/skills-off.json` (orch.skills-off/1, read by the core's linking): orch's own skills and the admin's shared
   skills are links orch makes; a name on this list is not linked (the files stay).
2. Claude Code's own per-folder switches in `.claude/settings.local.json`: `skillOverrides` ("off"),
   `permissions.deny` ("mcp__<server>__*") and `claudeMdExcludes` (a rules file by its full path). orch writes only
   the entries it records in `.orch/addons/skills/owned.json` and removes only those; everything else in the file
   stays as it is. An entry somebody wrote by hand is shown as off and is not changed by orch.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
from pathlib import Path

OFF_SCHEMA = "orch.skills-off/1"
OWNED_SCHEMA = "orch.skills-owned/1"
SETTINGS = Path(".claude") / "settings.local.json"
OWNED = Path(".orch") / "addons" / "skills" / "owned.json"
LOCK = Path(".orch") / "addons" / "skills" / ".lock"
MAX_BYTES = 1024 * 1024
KINDS = ("skillOverrides", "deny", "claudeMdExcludes")


class Refused(Exception):
    """A plain-words refusal (exit 2)."""


def mcp_rule(server: str) -> str:
    """The deny rule for every tool of one MCP server (Claude writes tool names as mcp__<server>__<tool>; letters,
    digits, dashes and underscores stay, anything else becomes _)."""
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", server) + "__*"


def _is_link(p: Path) -> bool:
    try:
        return p.is_symlink() or bool(getattr(os.lstat(p), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def _read(path: Path, what: str) -> dict:
    if _is_link(path):
        raise Refused(f"{what} is a link; orch will not write through it. Nothing was changed.")
    if not path.exists():
        return {}
    try:
        if path.stat().st_size > MAX_BYTES:
            raise Refused(f"{what} is too big to change safely. Nothing was changed.")
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise Refused(f"{what} is not readable JSON. Fix it first; nothing was changed.") from None
    if not isinstance(doc, dict):
        raise Refused(f"{what} is not a settings object. Fix it first; nothing was changed.")
    return doc


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@contextlib.contextmanager
def _locked(root: Path, wait: float = 5.0):
    """One change at a time in this workspace (two dashboard tabs, a helper and the page)."""
    lock = root / LOCK
    lock.parent.mkdir(parents=True, exist_ok=True)
    end = time.monotonic() + wait
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
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


def off_list(root: Path) -> list[str]:
    from orch import skills

    return sorted(skills.off_names(root))


def set_linked(root: Path, name: str, on: bool) -> bool:
    """Put a skill name on or off the core's off list and let the core relink. True when it changed."""
    from orch import skills

    if name in skills.ALWAYS_ON and not on:
        raise Refused(f"{name} is always on: helpers need it to work tickets.")
    with _locked(root):
        path = root / skills.OFF_FILE
        doc = _read(path, ".orch/skills-off.json") if path.exists() else {}
        names = set(skills.off_names(root)) if doc else set()
        before = set(names)
        (names.discard if on else names.add)(name)
        if names != before:
            _write(path, {"schema": OFF_SCHEMA, "skills": sorted(names)})
    if names == before:
        return False
    skills.apply_agent_files(root)  # links go (or come back) at once; an orch update keeps them that way
    return True


# ---- 2. Claude Code's per-folder settings -------------------------------------------------------------------


def _owned(root: Path) -> dict:
    doc = _read(root / OWNED, ".orch/addons/skills/owned.json")
    if doc and doc.get("schema") != OWNED_SCHEMA:
        doc = {}
    return {k: [v for v in doc.get(k, []) if isinstance(v, str)] for k in KINDS}


def _entries(settings: dict, kind: str) -> list[str]:
    if kind == "skillOverrides":
        ov = settings.get("skillOverrides")
        return sorted(k for k, v in ov.items() if v == "off") if isinstance(ov, dict) else []
    if kind == "deny":
        perms = settings.get("permissions")
        deny = perms.get("deny") if isinstance(perms, dict) else None
        return [d for d in deny if isinstance(d, str)] if isinstance(deny, list) else []
    ex = settings.get("claudeMdExcludes")
    return [e for e in ex if isinstance(e, str)] if isinstance(ex, list) else []


def claude_state(root: Path) -> dict:
    """{kind: {entry: "orch" | "hand"}} of what is off in Claude's local settings here (read only, never raises)."""
    try:
        settings, owned = _read(root / SETTINGS, ".claude/settings.local.json"), _owned(root)
    except Refused:
        return {k: {} for k in KINDS}
    return {k: {e: ("orch" if e in owned[k] else "hand") for e in _entries(settings, k)} for k in KINDS}


def set_claude(root: Path, kind: str, entry: str, on: bool) -> bool:
    """Off: add orch's entry (and record it). On: remove it only when orch wrote it. True when it changed."""
    if kind not in KINDS or not entry or len(entry) > 4096:
        raise Refused("That is not something orch can turn off here.")
    with _locked(root):
        settings = _read(root / SETTINGS, ".claude/settings.local.json")
        owned = _owned(root)
        present = entry in _entries(settings, kind)
        if on:
            if not present:
                return False
            if entry not in owned[kind]:
                raise Refused(
                    "It was turned off by hand in .claude/settings.local.json; orch leaves that alone. "
                    "Remove the line there to turn it on."
                )
            _change(settings, kind, entry, add=False)
            owned[kind].remove(entry)
        else:
            if present:
                return False
            _change(settings, kind, entry, add=True)
            owned[kind].append(entry)
        _write(root / SETTINGS, settings)
        _write(root / OWNED, {"schema": OWNED_SCHEMA, **{k: sorted(set(v)) for k, v in owned.items()}})
    return True


def _change(settings: dict, kind: str, entry: str, add: bool) -> None:
    if kind == "skillOverrides":
        ov = settings.get("skillOverrides")
        if not isinstance(ov, dict):
            if ov is not None:
                raise Refused("skillOverrides in .claude/settings.local.json is not an object. Fix it first.")
            ov = settings["skillOverrides"] = {}
        if add:
            ov[entry] = "off"
        else:
            ov.pop(entry, None)
            if not ov:
                settings.pop("skillOverrides")
        return
    if kind == "deny":
        perms = settings.setdefault("permissions", {})
        if not isinstance(perms, dict):
            raise Refused("permissions in .claude/settings.local.json is not an object. Fix it first.")
        lst = perms.setdefault("deny", [])
    else:
        lst = settings.setdefault("claudeMdExcludes", [])
    if not isinstance(lst, list):
        raise Refused(f"{kind} in .claude/settings.local.json is not a list. Fix it first.")
    if add:
        lst.append(entry)
    else:
        lst[:] = [x for x in lst if x != entry]
        if not lst:
            (settings["permissions"] if kind == "deny" else settings).pop("deny" if kind == "deny" else kind)
            if kind == "deny" and not settings["permissions"]:
                settings.pop("permissions")
