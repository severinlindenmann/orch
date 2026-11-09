"""`.orch/config.toml`: read it, and change the few keys orch owns ([workspace] agent, [agents.<name>]).

Everything else in the file (add-on tables, the user's own lines and comments) is left as it is.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sys
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


# ---- THE trust rule: orch runs a settings-supplied agent command only if THIS person approved exactly that
# command on THIS machine. Approvals live in the orch home (like permissions.json), never in the workspace,
# and do not depend on git, links or where the file came from. Any error = not approved.


def _approvals_path() -> Path:
    from orch import addons

    return addons.home() / "agent-approvals.json"


def _entry_key(root: Path, name: str, e: dict) -> str:
    ws = str(root.resolve())
    doc = [ws, name, e.get("adapter"), e.get("command"), e.get("interactive"), e.get("prompt")]
    return hashlib.sha256(json.dumps(doc).encode("utf-8")).hexdigest()


def _runs_command(e: dict) -> bool:
    return bool(e.get("command") or e.get("interactive"))


def agent_approved(root: Path, name: str, e: dict) -> bool:
    if not _runs_command(e):
        return True
    try:
        data = json.loads(_approvals_path().read_text(encoding="utf-8"))
        return isinstance(data, list) and _entry_key(root, name, e) in data
    except Exception:  # noqa: BLE001 - fail closed on anything
        return False


def approve_agent(root: Path, name: str, e: dict) -> None:
    """A person's yes for exactly this command here (the hash covers workspace, name, adapter, command,
    interactive and prompt: any change asks again)."""
    p = _approvals_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else []
    except (OSError, ValueError):
        data = []
    if not isinstance(data, list):
        data = []
    k = _entry_key(root, name, e)
    if k not in data:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{secrets.token_hex(4)}.tmp")
        try:
            tmp.write_text(json.dumps(data[-500:] + [k]), encoding="utf-8")
            os.replace(tmp, p)
        finally:
            tmp.unlink(missing_ok=True)


def _raw_entries(root: Path) -> dict[str, dict]:
    out = {}
    try:
        agents = read(root).get("agents") or {}
    except Refused:
        return {}
    for name, e in agents.items():
        if isinstance(e, dict) and NAME_RE.fullmatch(name) and isinstance(e.get("adapter"), str):
            out[name] = {
                k: e[k] for k in ("adapter", "command", "interactive", "prompt") if isinstance(e.get(k), str)
            }
    return out


SHOW_MAX = 500  # an entry with a longer field cannot be shown in full, so it cannot be approved


def _safe_text(v: str) -> bool:
    """Plain printable text only: no control (C0/C1, ESC), format (bidi, zero-width), line/paragraph
    separator, private-use or unassigned character, and no space but the plain one.
    What is shown is exactly what is hashed."""
    import unicodedata

    return len(v) <= SHOW_MAX and all(
        c == " " or (unicodedata.category(c) not in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp", "Zs"))
        for c in v
    )


def pending_agents(root: Path) -> list[dict]:
    """Entries of this workspace's settings that name a command nobody approved here. Every field the approval
    covers is returned in full, plus `key` (the hash the approval is bound to) and `showable`."""
    out = []
    for n, e in _raw_entries(root).items():
        if agent_approved(root, n, e):
            continue
        fields = {k: e.get(k) for k in ("adapter", "command", "interactive", "prompt")}
        out.append(
            {
                "name": n,
                **fields,
                "key": _entry_key(root, n, e),
                "showable": all(_safe_text(v) for v in fields.values() if isinstance(v, str))
                and _safe_text(n),
            }
        )
    return out


def allow_agent(root: Path, name: str, key: str) -> str:
    """Approve exactly ONE entry, and only if it is still what was shown (its key matches now). A person only
    (the caller checks). Never approves several entries."""
    e = _raw_entries(root).get(name) if isinstance(name, str) else None
    if e is None:
        raise Refused("That agent is not in this workspace's settings (any more). Please look again.")
    if not isinstance(key, str) or _entry_key(root, name, e) != key:
        raise Refused("That command changed since you looked. Please look again.")
    if not (_safe_text(name) and all(_safe_text(v) for v in e.values() if isinstance(v, str))):
        raise Refused(
            "That command cannot be shown safely (too long or odd characters), so it cannot be allowed."
        )
    approve_agent(root, name, e)
    return name


def untrusted_note(root: Path) -> str | None:
    """Plain line for a command this machine has not approved; None when nothing waits."""
    p = pending_agents(root)
    if not p:
        return None
    if not p[0]["showable"]:
        return "This workspace asks to run a command orch can't show safely. It is not run."
    c = p[0]["command"] or p[0]["interactive"] or ""
    return f"This workspace asks to run `{c[:200]}`. Allow it on this machine first: orch private"


def _builtin_names() -> set[str]:
    from orch import adapters

    return set(adapters.builtin_names())


def agent_name(root: Path) -> str | None:
    """The agent that does the work here ([workspace] agent), or None when nobody chose. A name that is not
    built in counts only when its command is approved here."""
    v = (read(root).get("workspace") or {}).get("agent")
    if not (isinstance(v, str) and v):
        return None
    if v not in _builtin_names() and v not in agent_entries(root):
        return None
    return v


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
    """The [agents.<name>] entries that may be used: well-formed, approved here when they run a command."""
    return {n: e for n, e in _raw_entries(root).items() if agent_approved(root, n, e)}


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
    approve: bool = True,
):
    if not NAME_RE.fullmatch(name):
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
    if (
        approve
    ):  # a person typed it here: approve ONLY what they typed, and only if the file says exactly that
        typed = {"adapter": adapter, "command": command}
        if interactive:
            typed["interactive"] = interactive
        if prompt:
            typed["prompt"] = prompt
        if _raw_entries(root).get(name) == typed:
            approve_agent(root, name, typed)
        else:
            print(
                f"orch: '{name}' also has other settings here, so it is not allowed yet: orch private",
                file=sys.stderr,
            )


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
