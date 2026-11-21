"""What a restarted background service gets for its environment (`orch update`).

Nothing the service recorded is replayed: the record sits in a file that any process of this user can write,
so replaying it would let such a process choose what the restarted service runs with. The restart starts the
service with the CALLER's environment plus exactly three overrides that come from the system, not a record:

  HOME      the current user's home from the password database (a sandbox HOME must not decide where the
            agent login is looked for). A test install keeps the caller's HOME: ORCH_HOME_STRICT is on or
            the installer marked it `test`, so its add-ons never reach the real home (ORCH-632).
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


def test_install() -> bool:
    """A test install: ORCH_HOME_STRICT is on (the isolation switch of every test and e2e run) or the
    installer marked this orch `test`. Its services keep the HOME they are started with."""
    if os.environ.get("ORCH_HOME_STRICT", "") not in ("", "0"):
        return True
    try:
        from orch import home as orch_home

        return orch_home.read_install_record() == "test"
    except Exception:  # noqa: BLE001 - no record readable: a normal install
        return False


def overrides(orch_home: Path) -> tuple[dict[str, str], list[str]]:
    """(variables to set over the caller's environment, notes). HOME is left as the caller's in a test
    install, and when the system cannot tell the user's home (and a note says so)."""
    out, notes = {"ORCH_HOME": str(orch_home)}, []
    if test_install():
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


def source(name: str, over: dict[str, str]) -> str:
    """Where the restart took one of HOME/PATH from, in plain words."""
    return "this user's home folder" if name in over else "this terminal"


def differs(recorded: object, used: dict[str, str]) -> list[str]:
    """Which of HOME/PATH the service was started with differ from what the restart uses."""
    rec = clean(recorded)
    return [k for k in INFO_NAMES if k in rec and used.get(k) != rec[k]]
