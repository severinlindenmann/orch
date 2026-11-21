"""Turn off / Turn on, for this workspace only. Two places, nothing is moved or deleted:

1. `.orch/skills-off.json` (orch.skills-off/1, read by the core's linking): orch's own skills and the admin's shared
   skills are links orch makes; a name on this list is not linked (the files stay).
2. The helper tool's own per-folder switches, named in the agents data (`files.folder_switches` of its adapter):
   a skills object (name -> "off"), `permissions.deny` ("mcp__<server>__*") and a rules-file list (a rules file by
   its full path). orch writes only the entries it records in `.orch/addons/skills/owned.json` and removes only
   those; everything else in the file stays as it is. An entry somebody wrote by hand is shown as off and is not
   changed by orch.

Every file is reached only through real folders inside the workspace (a link anywhere on the way is refused), is
replaced through a fresh temporary file next to it, and the settings file is replaced only when nobody changed it
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

OFF_SCHEMA = "orch.skills-off/1"
OWNED_SCHEMA = "orch.skills-owned/1"
OWNED = Path(".orch") / "addons" / "skills" / "owned.json"
LOCK = Path(".orch") / "addons" / "skills" / ".lock"
MAX_BYTES = 1024 * 1024
KINDS = ("skills", "deny", "rules")


class Refused(Exception):
    """A plain-words refusal (exit 2)."""


def tool() -> dict | None:
    """The built-in helper tool with per-folder switches (agents data, files.folder_switches): {"name", "label",
    "settings" (a Path inside the folder), "skills", "rules_exclude", "home_rules"}; None when no tool has them."""
    try:
        from orch import adapters

        for n in adapters.builtin_names():
            a = adapters.load(n)
            fs = (a.get("files") or {}).get("folder_switches")
            if isinstance(fs, dict):
                return {**fs, "name": n, "label": a["label"], "settings": Path(fs["settings"])}
    except Exception:  # noqa: BLE001  no core or bad agents data: nothing can be switched in the tool
        return None
    return None


def mcp_rule(server: str) -> str:
    """The deny rule for every tool of one MCP server (tools name MCP tools mcp__<server>__<tool>; letters,
    digits, dashes and underscores stay, anything else becomes _)."""
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", server) + "__*"


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


def _write(root: Path, rel: Path, doc: dict, expect: bytes | None | bool = True) -> None:
    """Replace root/rel through a fresh temporary file. With expect (bytes, or None = must still be missing) the
    file is replaced only when it still holds exactly that."""
    path = safe_path(root, rel)
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    safe_path(root, rel)  # the folders just made are real folders too
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
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
                if time.time() - lock.stat().st_mtime > 300:  # left by a process that died (a delete copies)
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


def skill_places() -> tuple[Path, ...]:
    """The workspace folders helpers read skills from: .agents/skills, then each built-in tool's own skills folder
    (agents data, files.skills_link)."""
    out = [Path(".agents") / "skills"]
    try:
        from orch import adapters

        for n in adapters.builtin_names():
            link = (adapters.load(n).get("files") or {}).get("skills_link")
            if link and Path(link) not in out:
                out.append(Path(link))
    except Exception:  # noqa: BLE001, S110  no core: the shared folder only
        pass
    return tuple(out)


def reads_shared(name: str) -> bool:
    """True when the tool reads .agents/skills itself (it has no skills folder of its own that orch links)."""
    try:
        from orch import adapters

        return not (adapters.load(name).get("files") or {}).get("skills_link")
    except Exception:  # noqa: BLE001
        return False


def instruction_files() -> tuple[str, ...]:
    """The rules files helpers read in a workspace: the guide files, each tool's local file, then AGENTS.local.md."""
    out = ["AGENTS.md"]
    try:
        from orch import adapters

        out += [f for f in adapters.GUIDE_FILES if f not in out]
        for n in adapters.builtin_names():
            out += [f for f in ((adapters.load(n).get("files") or {}).get("instructions_link") or {}) if f not in out]
    except Exception:  # noqa: BLE001, S110  no core: AGENTS.md only
        pass
    return (*out, "AGENTS.local.md")


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


# ---- 2. the helper tool's per-folder settings-------------------------------------------------------------------


def _owned(root: Path) -> dict:
    try:
        doc, _ = _read(root, OWNED)
    except Refused:
        doc = {}
    if doc.get("schema") != OWNED_SCHEMA:
        doc = {}
    return {k: [v for v in doc.get(k, []) if isinstance(v, str)] for k in KINDS}


def _entries(settings: dict, kind: str, spec: dict) -> list[str]:
    if kind == "skills":
        ov = settings.get(spec["skills"])
        return sorted(k for k, v in ov.items() if v == "off") if isinstance(ov, dict) else []
    if kind == "deny":
        perms = settings.get("permissions")
        deny = perms.get("deny") if isinstance(perms, dict) else None
        return [d for d in deny if isinstance(d, str)] if isinstance(deny, list) else []
    ex = settings.get(spec["rules_exclude"])
    return [e for e in ex if isinstance(e, str)] if isinstance(ex, list) else []


def tool_state(root: Path) -> dict:
    """{kind: {entry: "orch" | "hand"}} of what is off in the tool's local settings here (read only, never raises).
    A recorded entry that is no longer in the file does not count: a line written by hand later stays "hand"."""
    spec = tool()
    try:
        if spec is None:
            raise Refused("no tool")
        settings, _ = _read(root, spec["settings"])
    except Refused:
        return {k: {} for k in KINDS}
    owned = _owned(root)
    return {k: {e: ("orch" if e in owned[k] else "hand") for e in _entries(settings, k, spec)} for k in KINDS}


def set_tool(root: Path, kind: str, entry: str, on: bool) -> bool:
    """Off: add orch's entry (and record it). On: remove it only when orch wrote it. True when it changed."""
    spec = tool()
    if spec is None or kind not in KINDS or not entry or len(entry) > 4096:
        raise Refused("That is not something orch can turn off here.")
    where = spec["settings"]
    with _locked(root):
        settings, raw = _read(root, where)
        owned = _owned(root)
        stale = {k: [e for e in owned[k] if e not in _entries(settings, k, spec)] for k in KINDS}
        if any(stale.values()):  # a recorded line somebody removed: forget it, so a later hand-written one stays
            owned = {k: [e for e in owned[k] if e not in stale[k]] for k in KINDS}
            _write(root, OWNED, {"schema": OWNED_SCHEMA, **owned})
        present = entry in _entries(settings, kind, spec)
        if on:
            if not present:
                return False
            if entry not in owned[kind]:
                raise Refused(
                    f"It was turned off by hand in {where.as_posix()}; orch leaves that alone. "
                    "Remove the line there to turn it on."
                )
            _change(settings, kind, entry, add=False, spec=spec)
            _write(root, where, settings, expect=raw)  # the line goes first; its record after
            owned[kind].remove(entry)
            _write(root, OWNED, {"schema": OWNED_SCHEMA, **owned})
        else:
            if present:
                return False
            before = list(owned[kind])
            owned[kind] = sorted(set(owned[kind]) | {entry})
            _write(root, OWNED, {"schema": OWNED_SCHEMA, **owned})  # the record first: a crash leaves no orphan line
            _change(settings, kind, entry, add=True, spec=spec)
            try:
                _write(root, where, settings, expect=raw)
            except Refused:  # not written: take the record back, so a line someone adds now stays theirs
                owned[kind] = before
                _write(root, OWNED, {"schema": OWNED_SCHEMA, **owned})
                raise
    return True


def _change(settings: dict, kind: str, entry: str, add: bool, spec: dict) -> None:
    where = spec["settings"].as_posix()
    key = spec["skills"] if kind == "skills" else spec["rules_exclude"] if kind == "rules" else "deny"
    if kind == "skills":
        ov = settings.get(key)
        if not isinstance(ov, dict):
            if ov is not None:
                raise Refused(f"{key} in {where} is not an object. Fix it first.")
            ov = settings[key] = {}
        if add:
            ov[entry] = "off"
        else:
            ov.pop(entry, None)
            if not ov:
                settings.pop(key)
        return
    if kind == "deny":
        perms = settings.setdefault("permissions", {})
        if not isinstance(perms, dict):
            raise Refused(f"permissions in {where} is not an object. Fix it first.")
        lst = perms.setdefault("deny", [])
    else:
        lst = settings.setdefault(key, [])
    if not isinstance(lst, list):
        raise Refused(f"{key} in {where} is not a list. Fix it first.")
    if add:
        lst.append(entry)
        return
    lst[:] = [x for x in lst if x != entry]
    if not lst:
        if kind == "deny":
            settings["permissions"].pop("deny")
            if not settings["permissions"]:
                settings.pop("permissions")
        else:
            settings.pop(key)
