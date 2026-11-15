"""orch init: merge the work-check reminder hooks into an agent tool's local settings file.

Which tool, which file and which events is data (agents/reminder.json: `reminder.settings_file`,
`reminder_hooks`); nothing here names a tool. The file is the tool's own local (not committed)
settings and may hold the person's keys: only our hook entries are added or refreshed, everything
else is kept. A file that is not valid JSON of the expected shape, is a link, or is tracked by the
team's git is left exactly as it is and the person gets one warning line. The write is atomic (temp
file made with O_EXCL, renamed over: a link at the destination is replaced, never followed) and re-
checked just before the rename.

The hook command runs this very orch again: `"<abs python>" -I -m orch work-check --hook <tool>`.
- absolute interpreter, forward slashes, double-quoted: the same line works under bash (Git Bash on
  Windows) and cmd. An interpreter path with a character either shell would treat specially
  (" % $ ` !) is not written: the person gets a warning instead;
- `-I`: isolated, which also keeps the cwd and PYTHONPATH off sys.path;
- no shell tricks to hide errors: `orch work-check --hook` itself always exits 0 and prints nothing else.
At init the exact command is run once (`--version`): an orch that `-I` cannot import (a pip --user or
PYTHONPATH install) gets a warning and nothing is written.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from orch import harness
from orch.errors import Refused

TIMEOUT = 5
_OURS = re.compile(r" (?:-I )?(?:-P )?-m orch work-check --hook [a-z][a-z0-9-]*(?: 2>/dev/null \|\| true)?$")
_BAD = set('"%$`!\n\r\0')


def orch_argv(*args: str) -> list[str]:
    """`orch <args>` as a hook's argv: the ONE place that says how a hook starts orch (the check below runs
    the same prefix). `-I -P`: isolated, no cwd on sys.path; orch needs Python 3.11+, which knows `-P`.
    ValueError for an interpreter path no shell can carry safely."""
    exe = sys.executable.replace("\\", "/")
    if not exe or _BAD & set(exe):
        raise ValueError("the Python path has a character a hook command cannot carry safely")
    return [exe, "-I", "-P", "-m", "orch", *args]


def command_line(argv: list[str]) -> str:
    """A hook argv as the command line the tool runs: the interpreter double-quoted, the rest plain words."""
    return " ".join([f'"{argv[0]}"', *argv[1:]])


def hook_argv(tool: str) -> list[str]:
    """The work-check hook as an argv."""
    return orch_argv("work-check", "--hook", tool)


def hook_command(tool: str) -> str:
    """The work-check hook command for `tool` (an adapter name): the argv, the interpreter double-quoted."""
    return command_line(hook_argv(tool))


def record_hook_argv() -> list[str]:
    """The record hook as an argv (contracts/activity.md: the wiring calls exactly `orch record hook`)."""
    return orch_argv("record", "hook")


def record_hook_command() -> str:
    return command_line(record_hook_argv())


def can_import(root: Path | None) -> bool:
    """The hook's interpreter and flags (same argv up to `work-check`) can import orch (not so for a pip
    --user or PYTHONPATH install)."""
    try:
        argv = orch_argv("--version")
        r = subprocess.run(argv, cwd=root, capture_output=True, timeout=10)
    except (ValueError, OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


_IMPORT_OK: dict = {}


def can_import_cached() -> bool:
    """can_import once per process and interpreter (the reminder hooks of a run are gated on it)."""
    key = sys.executable
    if key not in _IMPORT_OK:
        _IMPORT_OK[key] = can_import(None)
    return _IMPORT_OK[key]


def tools(root: Path) -> list[tuple[str, dict]]:
    """(name, adapter data) of every detected tool that has reminder hooks and a local settings file."""
    from orch import adapters, skills

    out = []
    for n in skills.detected_agents(root):
        a = adapters.load(n)
        if a.get("reminder_hooks") and (a.get("reminder") or {}).get("settings_file"):
            out.append((n, a))
    return out


def settings_files(root: Path) -> list[str]:
    return [a["reminder"]["settings_file"] for _, a in tools(root)]


def _ours(entry) -> bool:
    return (
        isinstance(entry, dict)
        and entry.get("type") == "command"
        and isinstance(entry.get("command"), str)
        and bool(_OURS.search(entry["command"]))
    )


def merge(doc: dict, events: list[str], command: str) -> dict:
    """The document with our entries in place (a validation problem raises ValueError)."""
    hooks = doc.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks is not an object")
    for event in events:
        groups = hooks.get(event, [])
        if not isinstance(groups, list) or not all(isinstance(g, dict) for g in groups):
            raise ValueError(f"hooks.{event} is not a list of objects")
        if any(("hooks" in g and not isinstance(g["hooks"], list)) for g in groups):
            raise ValueError(f"hooks.{event}[].hooks is not a list")
    out = {**doc, "hooks": {**hooks}}
    for event in events:
        groups = [dict(g) for g in hooks.get(event, [])]
        found = False
        for g in groups:
            if "hooks" not in g:
                continue
            inner = []
            for h in g["hooks"]:
                if _ours(h):
                    if not found:
                        inner.append({**h, "command": command, "timeout": TIMEOUT})
                    found = True  # a second copy of ours is dropped
                else:
                    inner.append(h)
            g["hooks"] = inner
        if not found:  # our own group: no matcher of somebody else's applies to it
            groups.append({"hooks": [{"type": "command", "command": command, "timeout": TIMEOUT}]})
        out["hooks"][event] = groups
    return out


def _sig(path: Path):
    st = path.stat()
    return (st.st_mtime_ns, st.st_size)


def _ensure_one(root: Path, rel: str, tool: str, events: list[str]) -> str | None:
    path = root / rel
    left = "orch left it as it is."
    if harness.is_link(path.parent) or harness.is_link(path):
        return f"{rel} is a link: orch left it as it is."
    if path.exists() and not path.is_file():
        return f"{rel} is not a regular file: orch left it as it is."
    if harness.is_tracked(root, rel):
        return f"{rel} is part of your team's files (tracked by git): {left}"
    try:
        command = hook_command(tool)
    except ValueError:
        return f"{rel}: the Python path has a character a hook cannot carry safely: {left}"
    if not can_import(root):
        return f"{rel}: the hook could not start orch with python -I (a --user or PYTHONPATH install): {left}"
    for attempt in (0, 1):
        try:
            before = _sig(path) if path.is_file() else None
            raw = path.read_bytes().decode("utf-8") if path.is_file() else ""
        except (OSError, UnicodeDecodeError):
            return f"{rel} cannot be read: {left}"
        try:
            doc = json.loads(raw) if raw.strip() else {}
            if not isinstance(doc, dict):
                raise ValueError("not an object")
            new = merge(doc, events, command)
        except (ValueError, RecursionError):
            return f"{rel} is not what orch expects (valid JSON with hooks as a list): {left}"
        if new == doc and path.is_file():
            break
        try:
            now = _sig(path) if path.is_file() else None
            if now != before:  # the tool wrote it meanwhile: read it again, once
                if attempt == 0:
                    continue
                return f"{rel} keeps changing: {left}"
            harness.write_text(path, json.dumps(new, indent=2, ensure_ascii=False) + "\n", mode=0o600)
        except (Refused, OSError):
            return f"{rel} could not be written: {left}"
        break
    try:
        harness.exclude_set(root, f"{tool}-settings", [rel])  # local, like orch's other files
    except (Refused, OSError, UnicodeDecodeError):
        pass
    return None


def ensure_each(root: Path) -> list[tuple[str, str, str | None]]:
    """(tool name, settings file, warning or None) for every detected tool that has reminder hooks."""
    return [
        (
            name,
            a["reminder"]["settings_file"],
            _ensure_one(root, a["reminder"]["settings_file"], name, list(a["reminder_hooks"])),
        )
        for name, a in tools(root)
    ]


def ensure(root: Path) -> list[str]:
    """Put the hooks in place for every detected tool that has them; returns the warning lines."""
    return [w for _, _, w in ensure_each(root) if w]


def unmerge(doc: dict) -> dict:
    """The document without our hook entries (the reverse of merge). A group that only held ours goes with
    them, an event with no group left goes, and `hooks` goes when empty; everything else stays as it was."""
    hooks = doc.get("hooks")
    if not isinstance(hooks, dict):
        return doc
    out_hooks = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            out_hooks[event] = groups
            continue
        kept = []
        for g in groups:
            inner = g.get("hooks") if isinstance(g, dict) else None
            if not isinstance(inner, list) or not any(_ours(h) for h in inner):
                kept.append(g)
                continue
            rest = [h for h in inner if not _ours(h)]
            if rest:
                kept.append({**g, "hooks": rest})
        if kept or not groups:
            out_hooks[event] = kept
    out = {k: v for k, v in doc.items() if k != "hooks"}
    if out_hooks:
        out = {**doc, "hooks": out_hooks}
    return out


def has_ours(doc: object) -> bool:
    hooks = doc.get("hooks") if isinstance(doc, dict) else None
    if not isinstance(hooks, dict):
        return False
    return any(
        _ours(h)
        for groups in hooks.values()
        if isinstance(groups, list)
        for g in groups
        if isinstance(g, dict) and isinstance(g.get("hooks"), list)
        for h in g["hooks"]
    )


def remove_one(root: Path, rel: str) -> str | None:
    """Take our entries out of one settings file. Returns what happened ("removed", "deleted") or None when
    there was nothing of ours. The file goes only when nothing else is left in it; a file that is a link, not
    valid JSON, or that changes while we read it is left alone (a Refused says so)."""
    path = root / rel
    if harness.is_link(path.parent) or harness.is_link(path) or not path.is_file():
        return None
    for attempt in (0, 1):
        try:
            before = _sig(path)
            doc = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        if not has_ours(doc):
            return None
        new = unmerge(doc)
        if _sig(path) != before:
            if attempt == 0:
                continue
            raise Refused(f"{rel} keeps changing: orch left it as it is.")
        if new:
            harness.write_text(path, json.dumps(new, indent=2, ensure_ascii=False) + "\n", mode=0o600)
            return "removed"
        path.unlink()
        return "deleted"
    return None


def remove_each(root: Path) -> list[tuple[str, str]]:
    """(settings file, "removed" | "deleted") for every tool orch has hook entries for, detected or not."""
    from orch import adapters

    out = []
    seen = set()
    for n in adapters.builtin_names():
        a = adapters.load(n)
        rel = (a.get("reminder") or {}).get("settings_file")
        if a.get("reminder_hooks") and rel and rel not in seen:
            seen.add(rel)
            done = remove_one(root, rel)
            if done:
                out.append((rel, done))
    return out
