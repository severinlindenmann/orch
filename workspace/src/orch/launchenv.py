"""What a restarted background service gets for its environment (`orch update`).

Nothing the service recorded is replayed: the record sits in a file that any process of this user can write,
so replaying it would let such a process choose what the restarted service runs with. The restart starts the
service with the CALLER's environment plus exactly three overrides that come from the system, not a record:

  HOME      the current user's home from the password database (a test or sandbox HOME must not decide
            where the agent login is looked for); except in a test install (ORCH_HOME_STRICT), where the
            caller's test HOME stays, so a restarted test dashboard never sees or writes the real home's files
  ORCH_HOME the orch folder in use now
  ORCH_ROOT the verified workspace folder (set by services._call)

The record holds only HOME and PATH as they were at start, and only as information: when it differs from what
the restart uses, one line says so. Anything else in that file is ignored, and names that change what code a
process loads (LD_*, PYTHON*, ...) are refused outright."""

from __future__ import annotations

import os
import re
from pathlib import Path

INFO_NAMES = ("HOME", "PATH")  # all that is recorded, for the "started with a different HOME/PATH" line
DENY = re.compile(r"^(LD_|DYLD_|PYTHON|NODE_|GIT_|PERL5|RUBY)|^(BASH_ENV|ENV)$")
MAX = 4096


def denied(name: str) -> bool:
    """Variables that change what code a process loads: never set from a record."""
    return bool(DENY.match(name))


def capture(env: dict[str, str] | None = None) -> dict[str, str]:
    """The informational record of a start: HOME and PATH as the service got them."""
    src = os.environ if env is None else env
    return {
        k: v
        for k, v in src.items()
        if k in INFO_NAMES and isinstance(v, str) and len(v) <= MAX and "\0" not in v
    }


def clean(rec: object) -> dict[str, str]:
    """A recorded env read back from disk: only HOME and PATH as plain strings."""
    if not isinstance(rec, dict):
        return {}
    return {
        k: v
        for k, v in rec.items()
        if k in INFO_NAMES and isinstance(v, str) and len(v) <= MAX and "\0" not in v and not denied(k)
    }


def user_home() -> Path | None:
    """The current uid's home from the password database; None when it cannot be told (Windows, no entry)."""
    if os.name == "nt":
        return None
    try:
        import pwd

        home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except (ImportError, KeyError, OSError):
        return None
    return home if home.is_absolute() and home.is_dir() else None


def strict() -> bool:
    """A test install: ORCH_HOME_STRICT (anything but empty or 0), the same test as orch.addons.home()."""
    return os.environ.get("ORCH_HOME_STRICT", "") not in ("", "0")


def overrides(orch_home: Path) -> tuple[dict[str, str], list[str]]:
    """(variables to set over the caller's environment, notes). HOME is left as the caller's in a test install
    (ORCH_HOME_STRICT) and when the system cannot tell the user's home (then a note says so)."""
    out, notes = {"ORCH_HOME": str(orch_home)}, []
    if strict():
        return out, notes
    home = user_home()
    if home is not None:
        out["HOME"] = str(home)
    elif os.name != "nt":
        notes.append("could not read this user's home folder; kept this terminal's HOME")
    return out, notes


def apply(base: dict[str, str], over: dict[str, str]) -> dict[str, str]:
    """The caller's environment with the overrides on top (nothing else changes)."""
    return {**base, **over}


def home_said(over: dict[str, str], used: dict[str, str]) -> str:
    """Which HOME a restart used, for the line a person reads: the path and where it came from."""
    where = "this user's home folder" if "HOME" in over else "this terminal's"
    return f"HOME {used.get('HOME', '(not set)')} ({where})"


TMUX_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")  # where a person's tmux sits on a Mac (Homebrew) or Linux


def with_tmux(env: dict[str, str], dirs: tuple[str, ...] | None = None) -> dict[str, str]:
    """The environment of a background service, with the folder of an installed tmux at the END of PATH when
    PATH does not lead to one. A service started with a short PATH (at login, by an update that ran in the
    background) found no tmux although it is installed: every helper it started then worked in the background,
    with no screen to watch, and the page never said why (report r-1127-1221-t_7eoocm, ORCH-2367). The folder
    goes last, so it never changes which program any other name means. Nothing changes on Windows (no tmux),
    or when PATH already leads to tmux."""
    if os.name == "nt":
        return env
    parts = [p for p in (env.get("PATH") or "").split(os.pathsep) if p]

    def has(folder: str) -> bool:
        cand = os.path.join(folder, "tmux")
        return os.path.isfile(cand) and os.access(cand, os.X_OK)

    if any(has(p) for p in parts):
        return env
    for d in TMUX_DIRS if dirs is None else dirs:
        if d not in parts and has(d):
            return {**env, "PATH": os.pathsep.join([*parts, d])}
    return env


def differs(recorded: object, used: dict[str, str]) -> list[str]:
    """Which of HOME/PATH the service was started with differ from what the restart uses."""
    rec = clean(recorded)
    return [k for k in INFO_NAMES if k in rec and used.get(k) != rec[k]]
