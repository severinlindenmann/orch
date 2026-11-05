"""`.orch/config.toml`: read it, and change the few keys orch owns ([workspace] agent, [agents.<name>]).

Everything else in the file (add-on tables, the user's own lines and comments) is left as it is.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

from orch.errors import Refused

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_HEADER = re.compile(r"^\s*\[\[?\s*([^\]\[]+?)\s*\]\]?\s*(#.*)?$")


def path(root: Path) -> Path:
    return root / ".orch" / "config.toml"


def read(root: Path) -> dict:
    p = path(root)
    if not p.is_file():
        return {}
    try:
        return tomllib.loads(p.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise Refused(f"{p} is not valid TOML ({e}). Fix it, or remove the line you added last.") from None


def agent_name(root: Path) -> str | None:
    """The agent that does the work here ([workspace] agent), or None when nobody chose."""
    v = (read(root).get("workspace") or {}).get("agent")
    return v if isinstance(v, str) and v else None


def agent_entries(root: Path) -> dict[str, dict]:
    """The user's [agents.<name>] entries, only well-formed ones."""
    out = {}
    for name, e in (read(root).get("agents") or {}).items():
        if isinstance(e, dict) and NAME_RE.match(name) and isinstance(e.get("adapter"), str):
            out[name] = {k: e[k] for k in ("adapter", "command", "interactive") if isinstance(e.get(k), str)}
    return out


def _value(v: str) -> str:
    return json.dumps(v, ensure_ascii=False)  # a JSON string is a valid TOML basic string


def set_key(root: Path, table: str, key: str, value: str) -> None:
    """Set `key = "value"` inside [table], creating the table (and file) when needed."""
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True) if p.is_file() else []
    new = f"{key} = {_value(value)}\n"
    start = end = None
    for i, line in enumerate(lines):
        h = _HEADER.match(line)
        if h:
            if start is not None and end is None:
                end = i
            if h.group(1).strip() == table:
                start = i
    if start is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines += (["\n"] if lines else []) + [f"[{table}]\n", new]
    else:
        end = len(lines) if end is None else end
        key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for i in range(start + 1, end):
            if key_re.match(lines[i]):
                lines[i] = new
                break
        else:
            at = end
            while at > start + 1 and not lines[at - 1].strip():
                at -= 1  # keep blank lines that separate the next table
            if at > 0 and not lines[at - 1].endswith("\n"):
                lines[at - 1] += "\n"
            lines.insert(at, new)
    p.write_text("".join(lines), encoding="utf-8", newline="\n")
    read(root)  # never leave a file orch cannot read


def add_agent(root: Path, name: str, command: str, interactive: str | None = None, adapter: str = "generic"):
    if not NAME_RE.match(name):
        raise Refused(f"'{name}' is not a name orch can use. Use lowercase letters, digits and '-'.")
    for k, v in (("command", command), ("interactive", interactive)):
        if v is not None and not (1 <= len(v) <= 500 and "\n" not in v and "\r" not in v):
            raise Refused(f"The {k} must be one line of at most 500 characters.")
    set_key(root, f"agents.{name}", "adapter", adapter)
    set_key(root, f"agents.{name}", "command", command)
    if interactive:
        set_key(root, f"agents.{name}", "interactive", interactive)


# ---- the one notice for a command that comes from a folder's settings


def _seen_path() -> Path:
    from orch import addons

    return addons.home() / "agent-commands-seen.json"


def first_use_notice(command: str) -> str | None:
    """The one line to print the first time this machine runs this command from a folder's settings."""
    key = hashlib.sha256(command.encode("utf-8")).hexdigest()[:32]
    p = _seen_path()
    try:
        seen = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else []
    except (OSError, ValueError):
        seen = []
    if key in seen:
        return None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(seen[-200:] + [key]), encoding="utf-8")
    except OSError:
        pass
    return f"Using agent command from this folder's settings: {command}"
