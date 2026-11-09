"""`.orch/config.toml`: read it, and change the few keys orch owns ([workspace] agent, [agents.<name>]).

Everything else in the file (add-on tables, the user's own lines and comments) is left as it is.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
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


PERMISSION_MODES = ("ask", "auto", "full")
DEFAULT_PERMISSIONS = "auto"
DEFAULT_LIVE_IDLE_MINUTES = 60


def _perm_file() -> Path:
    from orch import addons

    return addons.home() / "permissions.json"


def _perm_key(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:32]


def permissions(root: Path | None) -> str:
    """What agents may do here without asking: ask | auto | full. Kept per machine in the orch home, keyed by
    the workspace's real path, never in the workspace: a committed config.toml (a cloned repo, or an agent
    editing it) cannot raise it. A permissions key in .orch/config.toml is ignored. Default: auto."""
    if root is None:
        return DEFAULT_PERMISSIONS
    try:
        v = json.loads(_perm_file().read_text(encoding="utf-8")).get(_perm_key(root))
    except (OSError, ValueError, AttributeError):
        return DEFAULT_PERMISSIONS
    return v if v in PERMISSION_MODES else DEFAULT_PERMISSIONS


def set_permissions(root: Path, value: str, by: str = "human:owner") -> str:
    """Save the mode for this machine. An agent may lower it, never raise it."""
    if value not in PERMISSION_MODES:
        raise Refused(f"'{value}' is not a mode. Pick one of: {', '.join(PERMISSION_MODES)}.")
    if by.startswith("agent:") and PERMISSION_MODES.index(value) > PERMISSION_MODES.index(permissions(root)):
        raise Refused(
            "Only a person can allow an agent more. Ask them to run: "
            f"orch config set workspace.permissions {value}"
        )
    p = _perm_file()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc = doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        doc = {}
    doc[_perm_key(root)] = value
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)  # private
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(doc, indent=1).encode("utf-8"))
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)
    return value


# ------------------------------------------------------------------ separate copies (per machine)
#
# `workflow.copies`, `workflow.copies_max` and `workflow.copy_setup` are kept like the permission mode: per
# machine in the orch home, keyed by the workspace's real path, never in the workspace. copy_setup is a
# command
# orch RUNS: a committed .orch/config.toml (a cloned repo, or an agent editing it) must not be able to
# choose it.

COPIES_MODES = ("off", "together", "always")
DEFAULT_COPIES = "together"
DEFAULT_COPIES_MAX = 3
MAX_COPIES_MAX = 20
MAX_COPY_SETUP = 500


def _copies_file() -> Path:
    from orch import addons

    return addons.home() / "copies.json"


def _copies_doc() -> dict:
    try:
        doc = json.loads(_copies_file().read_text(encoding="utf-8"))
    except (OSError, ValueError, Refused):  # no usable orch home: the defaults
        return {}
    return doc if isinstance(doc, dict) else {}


def _copies_get(root: Path | None, key: str):
    if root is None:
        return None
    try:
        mine = _copies_doc().get(_perm_key(root))
    except Refused:
        return None
    return mine.get(key) if isinstance(mine, dict) else None


def _copies_set(root: Path, key: str, value) -> None:
    doc = _copies_doc()
    mine = doc.get(_perm_key(root))
    mine = dict(mine) if isinstance(mine, dict) else {}
    if value is None:
        mine.pop(key, None)
    else:
        mine[key] = value
    doc[_perm_key(root)] = mine
    p = _copies_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(doc, indent=1).encode("utf-8"))
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


def copies_mode(root: Path | None) -> str:
    """off | together (default: a copy when another agent already works in the folder) | always."""
    v = _copies_get(root, "copies")
    return v if v in COPIES_MODES else DEFAULT_COPIES


def copies_max(root: Path | None) -> int:
    v = _copies_get(root, "copies_max")
    return (
        v
        if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= MAX_COPIES_MAX
        else DEFAULT_COPIES_MAX
    )


def copy_setup(root: Path | None) -> str | None:
    """The command the person chose to prepare a new copy (e.g. "npm ci"), or None."""
    v = _copies_get(root, "copy_setup")
    return v if isinstance(v, str) and v.strip() and len(v) <= MAX_COPY_SETUP and "\n" not in v else None


def set_copies_mode(root: Path, value: str) -> str:
    if value not in COPIES_MODES:
        raise Refused(f"'{value}' is not a choice. Pick one of: {', '.join(COPIES_MODES)}.")
    _copies_set(root, "copies", value)
    return value


def set_copies_max(root: Path, value: str) -> int:
    if not value.isdigit() or not 1 <= int(value) <= MAX_COPIES_MAX:
        raise Refused(f"Give a whole number of copies, from 1 to {MAX_COPIES_MAX}.")
    _copies_set(root, "copies_max", int(value))
    return int(value)


def set_copy_setup(root: Path, value: str) -> str | None:
    """ "" or "none" clears it. One line, at most MAX_COPY_SETUP characters; it is split into words, never run
    through a shell."""
    v = value.strip()
    if v in ("", "none"):
        _copies_set(root, "copy_setup", None)
        return None
    if "\n" in v or "\r" in v or "\x00" in v or len(v) > MAX_COPY_SETUP:
        raise Refused(f"Give one line of at most {MAX_COPY_SETUP} characters.")
    _copies_set(root, "copy_setup", v)
    return v


def live_idle_minutes(root: Path | None) -> int:
    """[workspace] live_idle_minutes: how long a live session may sit idle (or the ticket stay Done) before
    it is closed. Default 60; a value that is not a whole number above 0 is the default."""
    if root is None:
        return DEFAULT_LIVE_IDLE_MINUTES
    try:
        v = (read(root).get("workspace") or {}).get("live_idle_minutes")
    except Refused:
        return DEFAULT_LIVE_IDLE_MINUTES
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else DEFAULT_LIVE_IDLE_MINUTES


DEFAULT_FOCUS_LIVE_SESSION = True
DEFAULT_FOCUS_SESSION_TYPING = False
DEFAULT_RECORD_KEEP_DAYS = 90
DEFAULT_RECORD_MAX_MB = 2048
DEFAULT_INSIGHTS_SHARE_COUNTS = True
DEFAULT_INSIGHTS_SHARE_NAMES = False


def _reserved(root: Path | None, section: str, key: str, default: bool | int) -> bool | int:
    if root is None:
        return default
    try:
        table = read(root).get(section)
    except Refused:
        return default
    value = table.get(key) if isinstance(table, dict) else None
    if type(value) is not type(default):
        return default
    return value if isinstance(value, bool) or value > 0 else default


def focus_live_session(root: Path | None) -> bool:
    return _reserved(root, "focus", "live_session", DEFAULT_FOCUS_LIVE_SESSION)


def focus_session_typing(root: Path | None) -> bool:
    return _reserved(root, "focus", "session_typing", DEFAULT_FOCUS_SESSION_TYPING)


def record_keep_days(root: Path | None) -> int:
    return _reserved(root, "record", "keep_days", DEFAULT_RECORD_KEEP_DAYS)


def record_max_mb(root: Path | None) -> int:
    return _reserved(root, "record", "max_mb", DEFAULT_RECORD_MAX_MB)


def insights_share_counts(root: Path | None) -> bool:
    return _reserved(root, "insights", "share_counts", DEFAULT_INSIGHTS_SHARE_COUNTS)


def insights_share_names(root: Path | None) -> bool:
    return _reserved(root, "insights", "share_names", DEFAULT_INSIGHTS_SHARE_NAMES)


def agents_may_finish(root: Path | None) -> bool:
    return root is not None and (read(root).get("workflow") or {}).get("agents_may_finish") is True


def set_agents_may_finish(root: Path, value: bool) -> bool:
    set_key(root, "workflow", "agents_may_finish", value)
    return value


def set_live_idle_minutes(root: Path, value: str) -> int:
    if not value.isdigit() or not 1 <= int(value) <= 10080:
        raise Refused("Give a whole number of minutes, from 1 to 10080 (one week).")
    set_key(root, "workspace", "live_idle_minutes", int(value))
    return int(value)


CODE_RE = re.compile(r"^[A-Z0-9]{2,4}$")


def suggest_code(name: str) -> str:
    """Workspace code from a folder name: initials of up to 4 words, one word gives its first 3 characters
    (reference: contracts/validate.py, vectors/ticket-key-v1.json). "Month-end close" -> MEC."""
    import unicodedata

    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", plain)
    code = ("".join(w[0] for w in words[:4]) if len(words) > 1 else (words[0][:3] if words else "")).upper()
    return (code + "WS")[:2] if len(code) < 2 else code


def clean_code(value: str) -> str:
    code = value.strip().upper()
    if not CODE_RE.match(code):
        raise Refused(f"'{value}' can't be a workspace code. Use 2 to 4 letters or digits, e.g. MEC.")
    return code


def workspace_code(root: Path) -> str | None:
    """[workspace] code, or None when it is not set (or not valid)."""
    v = (read(root).get("workspace") or {}).get("code")
    return v if isinstance(v, str) and CODE_RE.match(v) else None


def set_code(root: Path, value: str) -> str:
    code = clean_code(value)
    set_key(root, "workspace", "code", code)
    return code


def agent_entries(root: Path) -> dict[str, dict]:
    """The user's [agents.<name>] entries, only well-formed ones."""
    out = {}
    for name, e in (read(root).get("agents") or {}).items():
        if isinstance(e, dict) and NAME_RE.match(name) and isinstance(e.get("adapter"), str):
            out[name] = {
                k: e[k] for k in ("adapter", "command", "interactive", "prompt") if isinstance(e.get(k), str)
            }
    return out


def _value(v: str | int | bool) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    # a JSON string is a valid TOML basic string, except that TOML forbids a raw DEL
    return json.dumps(v, ensure_ascii=False).replace("\x7f", "\\u007f")


def _headers(lines: list[str]) -> list[tuple[int, str]]:
    """(line index, table name) of every real table header: not a `[1, 2]` line inside an array, and not
    text inside a multi-line string."""
    out, depth, ml = [], 0, None
    for i, line in enumerate(lines):
        if ml is None and depth == 0:
            h = _HEADER.match(line)
            if h:
                out.append((i, h.group(1).strip()))
                continue
        j, n = 0, len(line)
        while j < n:
            if ml:
                k = line.find(ml, j)
                if k < 0:
                    break
                j, ml = k + 3, None
                continue
            c = line[j]
            if c == "#":
                break
            if line.startswith('"""', j) or line.startswith("'''", j):
                ml, j = line[j : j + 3], j + 3
            elif c in "\"'":
                j += 1
                while j < n and line[j] != c:
                    j += 2 if (c == '"' and line[j] == "\\") else 1
                j += 1
            else:
                depth += (c in "[{") - (c in "]}")
                j += 1
        depth = max(depth, 0)
    return out


def set_key(root: Path, table: str, key: str, value: str | int | bool | None) -> None:
    """Set `key = "value"` inside [table], creating the table (and file) when needed.
    `None` removes the key (and writes nothing when there is none)."""
    p = path(root)
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True) if p.is_file() else []
    if value is None and not any(re.match(rf"^\s*{re.escape(key)}\s*=", x) for x in lines):
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    new = "" if value is None else f"{key} = {_value(value)}\n"
    start = end = None
    for i, name in _headers(lines):
        if start is not None and end is None:
            end = i
        if name == table:
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
                lines[i : i + 1] = [new] if new else []
                break
        else:
            if not new:
                return
            at = end
            while at > start + 1 and not lines[at - 1].strip():
                at -= 1  # keep blank lines that separate the next table
            if at > 0 and not lines[at - 1].endswith("\n"):
                lines[at - 1] += "\n"
            lines.insert(at, new)
    text = "".join(lines)
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise Refused(f"orch could not change {p} safely ({e}). Nothing was written.") from None
    tmp = p.with_name(f"{p.name}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


def add_agent(
    root: Path,
    name: str,
    command: str,
    interactive: str | None = None,
    adapter: str = "generic",
    prompt: str | None = None,
):
    if not NAME_RE.match(name):
        raise Refused(f"'{name}' is not a name orch can use. Use lowercase letters, digits and '-'.")
    for k, v in (("command", command), ("interactive", interactive)):
        if v is not None and not (1 <= len(v) <= 500 and "\n" not in v and "\r" not in v):
            raise Refused(f"The {k} must be one line of at most 500 characters.")
    if isinstance((read(root).get("agents") or {}).get(name), dict):
        raise Refused(f"An agent called '{name}' is already set up here. Pick another name.")
    set_key(root, f"agents.{name}", "adapter", adapter)
    set_key(root, f"agents.{name}", "command", command)
    if interactive:
        set_key(root, f"agents.{name}", "interactive", interactive)
    if prompt:
        if prompt not in ("arg", "stdin"):
            raise Refused("The prompt goes in with 'arg' or 'stdin'.")
        set_key(root, f"agents.{name}", "prompt", prompt)


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
