"""The environment a background service was started with, kept so that a restart starts it the same.

`orch update` may run with another HOME or PATH than the service had (a test home, a shell without the
login): the restarted service would lose the agent login and the run gate. At start we record an ALLOWLIST
of the launch environment (running.json, mode 0600). The record is writable by anything running as this
user, so it is checked again at restart: a variable that fails its check is taken from the caller instead,
and one line says so.

Recorded: HOME, PATH, TMPDIR, LANG, LC_*, ORCH_* (not the actor/run markers), and the folders the agent tools
keep their login in (CLAUDE_CONFIG_DIR, CODEX_HOME, XDG_*). Tokens and API keys are never recorded."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

NAMES = (
    "HOME",
    "PATH",
    "TMPDIR",
    "LANG",
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
)
PREFIXES = ("LC_", "ORCH_")
NEVER = frozenset(  # who is acting / which run: never carried over from one start to another
    {"ORCH_ADDON", "ORCH_BIN", "ORCH_TICKET", "ORCH_RUN", "ORCH_VIA", "ORCH_DASHBOARD_NONCE"}
)
DIRS = frozenset({"CLAUDE_CONFIG_DIR", "CODEX_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "TMPDIR"})
MAX = 4096


def allowed(name: str) -> bool:
    return name not in NEVER and (name in NAMES or name.startswith(PREFIXES))


def capture(env: dict[str, str] | None = None, root: Path | None = None) -> dict[str, str]:
    """The allowlisted part of the launch environment (ORCH_ROOT = the workspace folder)."""
    src = os.environ if env is None else env
    out = {
        k: v for k, v in src.items() if allowed(k) and isinstance(v, str) and len(v) <= MAX and "\0" not in v
    }
    if root is not None:
        out["ORCH_ROOT"] = str(root)
    return out


def clean(rec: object) -> dict[str, str]:
    """A recorded env read back from disk: only allowlisted names with plain string values."""
    if not isinstance(rec, dict):
        return {}
    return {
        k: v
        for k, v in rec.items()
        if isinstance(k, str) and allowed(k) and isinstance(v, str) and len(v) <= MAX and "\0" not in v
    }


def _temp_dirs() -> list[Path]:
    out = {Path(tempfile.gettempdir()).resolve()}
    for p in ("/tmp", "/var/tmp", "/private/tmp", "/private/var/folders"):
        out.add(Path(p).resolve())
    return sorted(out)


def _inside(p: Path, bases) -> bool:
    return any(p == b or b in p.parents for b in bases)


def unsafe_dir(raw: str, workspaces: set[Path], *, allow_temp: bool = False) -> str | None:
    """Why this folder may not be used from a record, or None: absolute, existing, not inside a workspace
    (or any folder with .orch above it) and not inside a temp folder."""
    p = Path(raw)
    if not p.is_absolute():
        return "not an absolute path"
    try:
        r = p.resolve(strict=True)
    except OSError:
        return "does not exist"
    if not r.is_dir():
        return "not a folder"
    if _inside(r, workspaces) or any((a / ".orch").is_dir() for a in [r, *r.parents]):
        return "inside a workspace"
    if not allow_temp and _inside(r, _temp_dirs()):
        return "inside a temp folder"
    return None


def _home_of_user() -> Path | None:
    if os.name == "nt":
        return None
    try:
        import pwd

        return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
    except (ImportError, KeyError, OSError):
        return None


def validate(
    rec: dict[str, str], *, root: Path, workspaces: set[Path], orch_home: Path
) -> tuple[dict[str, str], list[str]]:
    """(the recorded variables that passed, the names that did not). ORCH_ROOT is always the verified root."""
    ok: dict[str, str] = {}
    bad: list[str] = []
    for k, v in clean(rec).items():
        why = None
        if k == "PATH":
            parts = [x for x in v.split(os.pathsep) if x]
            why = (
                "empty"
                if not parts
                else next((w for w in (unsafe_dir(x, workspaces) for x in parts) if w), None)
            )
        elif k == "HOME":
            h = _home_of_user()
            why = None if h is None or Path(v).resolve() == h else "not this user's home"
        elif k == "ORCH_ROOT":
            continue  # replaced below
        elif k == "ORCH_HOME":
            why = None if Path(v).resolve() == orch_home.resolve() else "not this orch folder"
        elif k in DIRS:
            why = unsafe_dir(v, workspaces, allow_temp=(k == "TMPDIR"))
        if why:
            bad.append(k)
        else:
            ok[k] = v
    ok["ORCH_ROOT"] = str(root)
    return ok, bad


def apply(base: dict[str, str], recorded: dict[str, str]) -> dict[str, str]:
    """`base` (the caller's environment) with every allowlisted variable replaced by the recorded set: a
    variable the service did not have is not inherited from the caller."""
    out = {k: v for k, v in base.items() if not allowed(k)}
    out.update({k: v for k, v in base.items() if k in NEVER})
    out.update(recorded)
    return out
