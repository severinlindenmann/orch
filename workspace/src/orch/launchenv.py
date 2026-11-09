"""What a restarted background service gets for its environment (`orch update`).

Nothing the service recorded is replayed: the record sits in a file that any process of this user can write,
so replaying it would let such a process choose what the restarted service runs with. The restart starts the
service with the CALLER's environment plus exactly three overrides that come from the system, not a record:

  HOME      the current user's home from the password database (a test or sandbox HOME must not decide
            where the agent login is looked for)
  ORCH_HOME the orch folder in use now
  ORCH_ROOT the verified workspace folder (set by services._call)

The record (HOME and PATH at start) is kept only as information: when it differs from what the restart uses,
one line says so. Names that change what code a process loads are never taken from a record at all."""

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


def capture(env: dict[str, str] | None = None, root: Path | None = None) -> dict[str, str]:  # noqa: ARG001
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


def overrides(orch_home: Path) -> tuple[dict[str, str], list[str]]:
    """(variables to set over the caller's environment, notes). HOME is left as the caller's when the system
    cannot tell the user's home (and a note says so)."""
    out, notes = {"ORCH_HOME": str(orch_home)}, []
    home = user_home()
    if home is not None:
        out["HOME"] = str(home)
    elif os.name != "nt":
        notes.append("could not read this user's home folder; kept this terminal's HOME")
    return out, notes


def apply(base: dict[str, str], over: dict[str, str]) -> dict[str, str]:
    """The caller's environment with the overrides on top (nothing else changes)."""
    return {**base, **{k: v for k, v in over.items() if not denied(k)}}


def differs(recorded: object, used: dict[str, str]) -> list[str]:
    """Which of HOME/PATH the service was started with differ from what the restart uses."""
    rec = clean(recorded)
    return [k for k in INFO_NAMES if k in rec and used.get(k) != rec[k]]
