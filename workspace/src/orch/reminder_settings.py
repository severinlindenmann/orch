"""orch init: merge the work-check reminder hooks into an agent tool's local settings file.

Which tool, which file and which events is data (agents/reminder.json: `reminder.settings_file`,
`reminder_hooks`); nothing here names a tool. The file is the tool's own local (not committed)
settings and may hold the person's keys: only our hook entries are added or refreshed, everything
else is kept. A file that is not valid JSON of the expected shape, is a link, or is tracked by the
team's git is left exactly as it is and the person gets one warning line. The write is atomic (temp
file made with O_EXCL, renamed over: a link at the destination is replaced, never followed) and re-
checked just before the rename.

The hook command runs this very orch again:
`<abs python> -I -P -m orch work-check --hook <tool> 2>/dev/null || true`.
- absolute interpreter, forward slashes, POSIX quoting (shlex) on every OS: the tool runs hooks through a
  POSIX shell (Git Bash on Windows);
- `-I -P` (isolated, no cwd on sys.path). The interpreter is the one running `orch init`, and orch
  needs Python 3.11+, which knows `-P`: an old interpreter never answers with the exit code that blocks;
- `2>/dev/null || true`: a removed venv or an uninstalled orch never shows an error on every prompt.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

from orch import harness
from orch.errors import Refused

TIMEOUT = 5
_OURS = re.compile(r"\borch work-check --hook [a-z][a-z0-9-]*\b")
_BARE = re.compile(r"^orch work-check --hook ([a-z][a-z0-9-]*)$")
ENDING = " 2>/dev/null || true"


def hook_command(tool: str) -> str:
    """The shell command of the hook for `tool` (a built-in adapter name)."""
    exe = sys.executable.replace("\\", "/")
    return shlex.join([exe, "-I", "-P", "-m", "orch", "work-check", "--hook", tool]) + ENDING


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
    if harness._tracked(root, rel):
        return f"{rel} is part of your team's files (tracked by git): {left}"
    command = hook_command(tool)
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


def ensure(root: Path) -> list[str]:
    """Put the hooks in place for every detected tool that has them; returns the warning lines."""
    out = []
    for name, a in tools(root):
        w = _ensure_one(root, a["reminder"]["settings_file"], name, list(a["reminder_hooks"]))
        if w:
            out.append(w)
    return out
