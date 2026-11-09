"""orch init: merge the work-check reminder hooks into the project's `.claude/settings.local.json`.

The file is Claude Code's own local (not committed) settings and may hold the person's keys: only our two
hook entries are added or refreshed, everything else is kept. A file that is not valid JSON of the expected
shape is left exactly as it is and the person gets one warning line. The hook command runs this very orch
again (`<python> -P -m orch work-check --hook claude`, the form every orch respawn uses), with an absolute
path, quoted for the shell, so no folder or PATH entry can substitute another program. Writes are atomic and
keep the file's mode."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

from orch import harness, procs
from orch.errors import Refused

REL = ".claude/settings.local.json"
EVENTS = ("SessionStart", "UserPromptSubmit")
TIMEOUT = 5
TAIL = ["work-check", "--hook", "claude"]


def applies(root: Path) -> bool:
    """Claude is this machine's or this folder's agent (the only built-in tool with local settings files)."""
    from orch import skills

    return "claude" in skills.detected_agents(root)


def hook_command() -> str:
    """The shell command of the hook: absolute interpreter, -P, -m orch, each part quoted."""
    argv = procs.orch_python_argv(*TAIL)
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def _ours(entry) -> bool:
    """One of our hook entries (whatever path an earlier install used)."""
    return (
        isinstance(entry, dict)
        and entry.get("type") == "command"
        and isinstance(entry.get("command"), str)
        and entry["command"].rstrip().endswith("orch " + " ".join(TAIL))
    )


def merge(doc: dict, command: str) -> dict:
    """The document with our entries in place (new keys only; a validation problem raises ValueError)."""
    hooks = doc.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks is not an object")
    for event in EVENTS:
        groups = hooks.get(event, [])
        if not isinstance(groups, list) or not all(isinstance(g, dict) for g in groups):
            raise ValueError(f"hooks.{event} is not a list of objects")
        if any(("hooks" in g and not isinstance(g["hooks"], list)) for g in groups):
            raise ValueError(f"hooks.{event}[].hooks is not a list")
    out = {**doc, "hooks": {**hooks}}
    for event in EVENTS:
        groups = [dict(g) for g in hooks.get(event, [])]
        found = False
        for g in groups:
            inner = []
            for h in g.get("hooks", []):
                if _ours(h):
                    if not found:
                        inner.append({**h, "command": command, "timeout": TIMEOUT})
                    found = True  # a second copy of ours is dropped
                else:
                    inner.append(h)
            if "hooks" in g:
                g["hooks"] = inner
        if not found:
            groups.append({"hooks": [{"type": "command", "command": command, "timeout": TIMEOUT}]})
        out["hooks"][event] = groups
    return out


def ensure(root: Path) -> str | None:
    """Put the hooks in place; returns one warning line when the file was left alone, else None."""
    path = root / REL
    if harness.is_link(root / ".claude") or harness.is_link(path):
        return f"{REL} is a link: orch left it as it is."
    if path.exists() and not path.is_file():
        return f"{REL} is not a regular file: orch left it as it is."
    try:
        raw = path.read_bytes().decode("utf-8") if path.is_file() else ""
    except (OSError, UnicodeDecodeError):
        return f"{REL} cannot be read: orch left it as it is."
    try:
        doc = json.loads(raw) if raw.strip() else {}
        if not isinstance(doc, dict):
            raise ValueError("not an object")
        new = merge(doc, hook_command())
    except ValueError:
        return f"{REL} is not what orch expects (valid JSON with hooks as a list): orch left it as it is."
    if new != doc or not path.is_file():
        text = json.dumps(new, indent=2, ensure_ascii=False) + "\n"
        try:
            harness.write_text(path, text, mode=0o600)  # atomic; an existing file keeps its mode
        except (Refused, OSError):
            return f"{REL} could not be written: orch left it as it is."
    try:
        harness.exclude_set(root, "claude-settings", [REL])  # local, like orch's other files
    except (Refused, OSError, UnicodeDecodeError):
        pass
    return None
