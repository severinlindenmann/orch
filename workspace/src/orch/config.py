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
import unicodedata
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


def allow_agent(root: Path, name: str, key: str, by: str | None = None) -> str:
    """Approve exactly ONE entry, and only if it is still what was shown (its key matches now). Never
    approves several entries."""
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


def diag_enabled(root: Path | None) -> bool:
    """The always-on debug log (contracts/diag.md): on unless a person switched it off on this computer."""
    v = _copies_get(root, "diag_enabled")
    return v if isinstance(v, bool) else True


def set_diag_enabled(root: Path, on: bool) -> bool:
    _copies_set(root, "diag_enabled", bool(on))
    return bool(on)


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


LIVE_MAX_CHOICES = range(2, 11)  # Settings > Helper > Helpers at once: No limit, or 2 to 10


def live_max(root: Path | None) -> int | None:
    """[workspace] live_max: how many helpers may work at once in this workspace. None (the default, also 0 or
    any value outside 2..10) is no limit; a number makes the next start wait in line until one closes."""
    if root is None:
        return None
    try:
        v = (read(root).get("workspace") or {}).get("live_max")
    except Refused:
        return None
    return v if isinstance(v, int) and not isinstance(v, bool) and v in LIVE_MAX_CHOICES else None


DEFAULT_FOCUS_LIVE_SESSION = True
DEFAULT_FOCUS_SESSION_TYPING = False
DEFAULT_RECORD_KEEP_DAYS = 90
DEFAULT_RECORD_MAX_MB = 2048
DEFAULT_INSIGHTS_SHARE_COUNTS = True
DEFAULT_INSIGHTS_SHARE_NAMES = False


def _reserved(
    root: Path | None, section: str, key: str, default: bool | int, positive: bool = True
) -> bool | int:
    if root is None:
        return default
    try:
        table = read(root).get(section)
    except Refused:
        return default
    value = table.get(key) if isinstance(table, dict) else None
    if type(value) is not type(default):
        return default
    return value if isinstance(value, bool) or not positive or value > 0 else default


# Retention settings (Insights > Settings): a number, not a switch. A file value is snapped DOWN to the
# allowed list and never below the floor (30 days / 512 MB), so an edit of config.toml can never make
# pruning delete nearly the whole record.
RETENTION_DEFAULTS = {"insights.keep_days": 90, "insights.max_mb": 2048}
RETENTION_ALLOWED = {"insights.keep_days": (30, 90, 365), "insights.max_mb": (512, 1024, 2048, 4096)}
RETENTION_FLOOR = {setting: min(allowed) for setting, allowed in RETENTION_ALLOWED.items()}


def retention_snap(setting: str, value: int) -> int:
    """A FILE retention number as it can count: snapped DOWN to the allowed list (keep_days 100 -> 90,
    99999 -> 365) and never below the floor (a whole number <= 0 reads as "as little as possible"). Anything
    but a whole number (true, a float, a string) is the default."""
    if type(value) is not int:
        return RETENTION_DEFAULTS[setting]
    if value <= 0:
        return RETENTION_FLOOR[setting]
    return max((v for v in RETENTION_ALLOWED[setting] if v <= value), default=RETENTION_FLOOR[setting])


RESERVED_DEFAULTS = {
    ("focus", "live_session"): DEFAULT_FOCUS_LIVE_SESSION,
    ("focus", "session_typing"): DEFAULT_FOCUS_SESSION_TYPING,
    ("record", "keep_days"): DEFAULT_RECORD_KEEP_DAYS,
    ("record", "max_mb"): DEFAULT_RECORD_MAX_MB,
    ("insights", "share_counts"): DEFAULT_INSIGHTS_SHARE_COUNTS,
    ("insights", "share_names"): DEFAULT_INSIGHTS_SHARE_NAMES,
}


def file_value(root: Path | None, section: str, key: str) -> bool | int:
    """The value as the FILE says it (a wrong type or a bool for a number is the default). A retention number
    is snapped DOWN to its allowed list with a floor (retention_snap); any other number <= 0 is the
    default."""
    setting = _RETENTION_SETTINGS.get((section, key))
    value = _reserved(root, section, key, RESERVED_DEFAULTS[(section, key)], positive=setting is None)
    return value if setting is None else retention_snap(setting, value)


def file_switch(root: Path, section: str, key: str, default: bool) -> bool | None:
    """A switch as the FILE says it: the parsed true / false (no key: `default`), or None when the file cannot
    be read (not valid TOML, mid-write) or the value is not true / false. None counts as off."""
    try:
        table = read(root).get(section, {})
    except (Refused, OSError):
        return None
    value = table.get(key, default) if isinstance(table, dict) else None
    return value if isinstance(value, bool) else None


_RETENTION_SETTINGS = {("record", "keep_days"): "insights.keep_days", ("record", "max_mb"): "insights.max_mb"}


def focus_live_session(root: Path | None) -> bool:
    return _reserved(root, "focus", "live_session", DEFAULT_FOCUS_LIVE_SESSION)


def focus_session_typing(root: Path | None) -> bool:
    return _reserved(root, "focus", "session_typing", DEFAULT_FOCUS_SESSION_TYPING)


SESSION_TYPING_KEY = "focus.session_typing"  # the `orch config` key of the setting below


def set_focus_session_typing(root: Path, value: bool) -> bool:
    """[focus] session_typing (default off): may the person type into the helper's screen."""
    set_key(root, "focus", "session_typing", bool(value))
    return bool(value)


def record_keep_days(root: Path | None) -> int:
    """[record] keep_days as the file says it (snapped to the allowed list, default 90)."""
    return file_value(root, "record", "keep_days")


def record_max_mb(root: Path | None) -> int:
    """[record] max_mb as the file says it (snapped to the allowed list, default 2048)."""
    return file_value(root, "record", "max_mb")


def insights_share_counts(root: Path | None) -> bool:
    """[insights] share_counts (default on). A file that cannot be read, or a value that is not true / false,
    is off."""
    if root is None:
        return False
    return file_switch(root, "insights", "share_counts", DEFAULT_INSIGHTS_SHARE_COUNTS) is True


def insights_share_names(root: Path | None) -> bool:
    """[insights] share_names (default off). A file that cannot be read, or a value that is not true / false,
    is off."""
    if root is None:
        return False
    return file_switch(root, "insights", "share_names", DEFAULT_INSIGHTS_SHARE_NAMES) is True


def conn_grants(root: Path) -> dict:
    """[conn.allow] grants by connection name ("*" or a list of action names). A wrong shape is no grant."""
    try:
        table = (read(root).get("conn") or {}).get("allow")
    except (Refused, OSError, AttributeError):
        return {}
    if not isinstance(table, dict):
        return {}
    return {
        name: val
        for name, val in table.items()
        if val == "*" or (isinstance(val, list) and all(isinstance(a, str) for a in val))
    }


SHARE_BLOCKED_MSG = {
    "not_connected": "Sharing counts is not available: this workspace is not connected to a relay.",
    "off_by_admin": "Sharing counts is not available: your admin turned it off for this workspace.",
}


def share_counts_state(root: Path) -> str:
    """The state of the daily counts upload (counts.md `sharing.counts`, usage-counts.md): `not_connected` (no
    relay connection, `.orch/secrets/relay.json`), `off_by_admin` (the last relay policy said
    `usage_counts: "off"`; kept by relay.refresh in `.orch/secrets/policy.json`), else `on` / `off` (the
    effective `insights.share_counts`). The core and the Insights page read the same state. The policy file
    counts only while there is a connection, and relay.connect clears it (a new connection never inherits the
    last relay's policy)."""
    from orch import net

    sec = net.secrets_dir(root)
    relay = net.read_json(sec / "relay.json", None)
    if not isinstance(relay, dict) or not {"url", "workspace", "token"} <= relay.keys():
        return "not_connected"
    policy = net.read_json(sec / "policy.json", None)
    if isinstance(policy, dict) and policy.get("usage_counts") == "off":
        return "off_by_admin"
    return "on" if insights_share_counts(root) else "off"


def share_counts_blocked(root: Path) -> str | None:
    """`not_connected` / `off_by_admin` when share_counts cannot be turned on here, else None."""
    state = share_counts_state(root)
    return state if state in SHARE_BLOCKED_MSG else None


INSIGHTS_KEYS = {  # setting -> ([table], key) in config.toml
    "insights.share_counts": ("insights", "share_counts"),
    "insights.share_names": ("insights", "share_names"),
    "insights.keep_days": ("record", "keep_days"),
    "insights.max_mb": ("record", "max_mb"),
}


def set_insights(root: Path, setting: str, value: bool | int, by: str | None = None) -> bool | int:
    """An Insights setting, written to config.toml. Lowering retention deletes nothing now: the next pruning
    applies it."""
    table, key = INSIGHTS_KEYS[setting]
    set_key(root, table, key, value)
    return value


class InsightsRefused(Refused):
    """A refusal of change_insights with its contract code (`{"error", "code"}`)."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code
        self.extra = {"code": code}


def insights_value(root: Path, setting: str) -> bool | int:
    """The EFFECTIVE value of an Insights setting (share_* with the person's record, retention the lower of
    file and record)."""
    return {
        "insights.share_counts": insights_share_counts,
        "insights.share_names": insights_share_names,
        "insights.keep_days": record_keep_days,
        "insights.max_mb": record_max_mb,
    }[setting](root)


def insights_text(value: bool | int) -> str:
    """How a value is written in a command: on/off, or the number."""
    return ("on" if value else "off") if isinstance(value, bool) else str(value)


def insights_target(setting: str, value: bool | int) -> str:
    """`key=value`: still named by the Insights page (removed with the page's own clean-up)."""
    return f"{setting}={insights_text(value)}"


def _same_text(setting: str, text: str, current: bool | int) -> bool:
    t = str(text).strip().lower()
    if isinstance(current, bool):
        t = {"true": "on", "false": "off"}.get(t, t)
    elif t.isascii() and t.isdigit():
        t = str(int(t))
    return t == insights_text(current)


def change_insights(
    root: Path,
    setting: str,
    value: bool | int,
    *,
    by: str | None = None,
    if_current: str | None = None,
) -> dict:
    """Change an Insights setting: refuse a stale `if_current` (code `changed`), classify widen / same, write
    the file. `insights.share_counts` = on is refused (`not_available`, nothing written) while the share state
    is off_by_admin or not_connected; off is always allowed."""
    current = insights_value(root, setting)
    widened = value > current
    if if_current is not None and not _same_text(setting, if_current, current):
        raise InsightsRefused(f"This changed in the meantime: now {insights_text(current)}", "changed")
    if setting == "insights.share_counts" and value is True:
        blocked = share_counts_blocked(root)  # off_by_admin / not_connected: `on` is not available here
        if blocked is not None:
            raise InsightsRefused(SHARE_BLOCKED_MSG[blocked], "not_available")
    if value == current:
        return {setting: current, "changed": False, "widened": False}
    set_insights(root, setting, value, by)
    return {setting: insights_value(root, setting), "changed": True, "widened": widened}


def agents_may_finish(root: Path | None) -> bool:
    """[workflow] agents_may_finish (default off): may an agent mark a ticket Done."""
    if root is None:
        return False
    return file_switch(root, "workflow", "agents_may_finish", False) is True


def set_agents_may_finish(root: Path, value: bool, by: str | None = None) -> bool:
    set_key(root, "workflow", "agents_may_finish", value)
    return value


def reviewer_on(root: Path | None) -> bool:
    """[workflow] reviewer (default off): the Reviewer accepts small work for the owner."""
    if root is None:
        return False
    return file_switch(root, "workflow", "reviewer", False) is True


def set_reviewer(root: Path, value: bool, by: str | None = None) -> bool:
    set_key(root, "workflow", "reviewer", value)
    return value


def release_merge_on(root: Path | None) -> bool:
    """[workflow] release_merge (default off): a release Merge card (`orch ask ... --merge --release`) merges
    by itself once every check of its pull request is green (`orch review tend-releases`). Owner's choice."""
    if root is None:
        return False
    return file_switch(root, "workflow", "release_merge", False) is True


def set_release_merge(root: Path, value: bool, by: str | None = None) -> bool:
    set_key(root, "workflow", "release_merge", value)
    return value


def set_live_idle_minutes(root: Path, value: str) -> int:
    if not value.isdigit() or not 1 <= int(value) <= 10080:
        raise Refused("Give a whole number of minutes, from 1 to 10080 (one week).")
    set_key(root, "workspace", "live_idle_minutes", int(value))
    return int(value)


def set_live_max(root: Path, value: str) -> int | None:
    """`none` (also off, 0) = no limit; 2 to 10 = that many helpers at once."""
    v = value.strip().lower()
    if v in ("none", "off", "0", "no limit", "unlimited"):
        set_key(root, "workspace", "live_max", None)  # no limit is the default: no line in the file
        return None
    if not v.isdigit() or int(v) not in LIVE_MAX_CHOICES:
        raise Refused("Give none (no limit) or a number from 2 to 10.")
    set_key(root, "workspace", "live_max", int(v))
    return int(v)


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


MAX_WS_NAME = 60
MAX_WS_DESCRIPTION = 280


def _ws_text(value: str, what: str, limit: int) -> str:
    v = " ".join(unicodedata.normalize("NFC", value).split())  # one line, single spaces
    if any(unicodedata.category(c)[0] == "C" for c in v):
        raise Refused(f"The {what} cannot contain control characters.")
    if len(v) > limit:
        raise Refused(f"The {what} can be at most {limit} characters.")
    return v


def workspace_name(root: Path | None) -> str | None:
    """[workspace] name: the name shown for this workspace; None when not set (the folder name is shown)."""
    if root is None:
        return None
    try:
        v = (read(root).get("workspace") or {}).get("name")
    except Refused:
        return None
    return v if isinstance(v, str) and 1 <= len(v) <= MAX_WS_NAME and v == v.strip() else None


def workspace_description(root: Path | None) -> str | None:
    """[workspace] description: one short line about this workspace, or None."""
    if root is None:
        return None
    try:
        v = (read(root).get("workspace") or {}).get("description")
    except Refused:
        return None
    return v if isinstance(v, str) and 1 <= len(v) <= MAX_WS_DESCRIPTION else None


def set_workspace_name(root: Path, value: str) -> str | None:
    """ "" clears it (the folder name is shown again)."""
    v = _ws_text(value, "name", MAX_WS_NAME)
    set_key(root, "workspace", "name", v or None)
    return v or None


def set_workspace_description(root: Path, value: str) -> str | None:
    v = _ws_text(value, "description", MAX_WS_DESCRIPTION)
    set_key(root, "workspace", "description", v or None)
    return v or None


WS_TAG_RE = re.compile(r"[a-z0-9-]{1,24}")
MAX_WS_TAGS = 4  # the dashboard's limit (the relay takes up to 8)


def _parse_tags(value: str) -> list[str]:
    out: list[str] = []
    for t in value.replace(" ", ",").split(","):
        t = t.strip().lower()
        if t and t not in out:
            out.append(t)
    if any(not WS_TAG_RE.fullmatch(t) for t in out):
        raise Refused("Tags are short words: lowercase letters, digits and hyphens, at most 24 characters.")
    if len(out) > MAX_WS_TAGS:
        raise Refused(f"Use at most {MAX_WS_TAGS} tags.")
    return out


def workspace_tags(root: Path | None) -> list[str]:
    """[workspace] tags = "a,b": a few short words about this workspace; [] when not set or hand-edited."""
    if root is None:
        return []
    try:
        v = (read(root).get("workspace") or {}).get("tags")
    except Refused:
        return []
    if not isinstance(v, str):
        return []
    try:
        return _parse_tags(v)
    except Refused:
        return []


def set_workspace_tags(root: Path, value: str) -> list[str]:
    """ "a,b" (commas or spaces); "" clears them."""
    tags = _parse_tags(value)
    set_key(root, "workspace", "tags", ",".join(tags) or None)
    return tags


# ---- who set the workspace profile (name, description, tags)
# Kept per machine in the orch home, keyed by the workspace's real path, like the look's `look_set_by`: an
# agent that edits config.toml cannot fake "agent" to unlock a person's choice.

PROFILE_FIELDS = ("name", "description", "tags")


def _profile_by_file() -> Path:
    from orch import addons

    return addons.home() / "profile-set-by.json"


def profile_set_by(root: Path) -> dict[str, str]:
    """{field: "agent"|"human"} for the fields someone set with orch; a field left out = nobody recorded."""
    from orch import net

    doc = net.read_json(_profile_by_file(), {})
    v = doc.get(_perm_key(root)) if isinstance(doc, dict) else None
    if not isinstance(v, dict):
        return {}
    return {k: w for k, w in v.items() if k in PROFILE_FIELDS and w in ("agent", "human")}


def _save_profile_by(root: Path, field: str, who: str) -> None:
    from orch import net

    doc = net.read_json(_profile_by_file(), {})
    doc = doc if isinstance(doc, dict) else {}
    mine = doc.get(_perm_key(root))
    mine = mine if isinstance(mine, dict) else {}
    mine[field] = who
    doc[_perm_key(root)] = mine
    net.write_json(_profile_by_file(), doc, private=False)


def set_profile_field(root: Path, field: str, value: str, by: str):
    """Set the workspace name, description or tags. `by` is the actor ("agent:<tool>" | "human:<name>").
    An agent may set a field while nobody has chosen it, and change its own choice later; once a person set it
    (or it was set before orch kept track), an agent is refused. Returns the saved value."""
    if field not in PROFILE_FIELDS:
        raise Refused("Pick the name, the description or the tags.")
    setters = {"name": set_workspace_name, "description": set_workspace_description}
    setter = setters.get(field, set_workspace_tags)
    getter = {"name": workspace_name, "description": workspace_description}.get(field, workspace_tags)
    if by.startswith("agent:"):
        was = profile_set_by(root).get(field)
        if was == "human" or (getter(root) and was != "agent"):
            raise Refused(f"The person chose the workspace {field}. Leave it; they change it in Settings.")
        if field == "tags":
            _parse_tags(value)  # refused before anything is written
        else:
            _ws_text(value, field, MAX_WS_NAME if field == "name" else MAX_WS_DESCRIPTION)
        try:  # first: if this fails, nothing is written
            _save_profile_by(root, field, "agent")
        except OSError as x:  # e.g. an agent whose sandbox only lets it write in the workspace
            raise Refused(
                f"orch could not save the workspace {field} here (this tool may only write in the folder). "
                "It is optional: skip it and carry on with the task."
            ) from x
        return setter(root, value)
    v = setter(root, value)
    try:
        _save_profile_by(root, field, "human")
    except OSError:
        pass  # the value is saved; with nothing recorded an agent still treats a set field as the person's
    return v


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
    approve: bool = False,
    by: str | None = None,
):
    """Save an agent entry. A person only: an agent (`by` = agent:...) is refused before it writes."""
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


def select_agent(root: Path, name: str, by: str | None = None) -> None:
    """Make `name` the workspace's default agent. A person only (an agent is refused)."""
    set_key(root, "workspace", "agent", name)


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
