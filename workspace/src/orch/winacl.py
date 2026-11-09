"""Windows rights for the guarded orch home (issue #405, contracts/secrets.md "Windows").

POSIX has 0700/0600 and an lstat link check. Windows has neither, so this module does the same job there:

- set_private(path, is_dir): only this user and SYSTEM may reach it, inheritance removed (icacls, argv list,
  no shell). SIDs, not names, so it works in every language.
- check_private(path): read the rights back (icacls /save gives SDDL with SIDs) and refuse unless the list is
  exactly this user and/or SYSTEM, protected (no inheritance), and the path has no link or junction.
  FAIL CLOSED: anything this module cannot parse or run is a refusal.
- no_reparse(path): no symlink, junction or other reparse point on any part of the path.

On POSIX all three are no-ops: the existing mode and lstat checks stay there. Errors are plain words.
Level 1 (R1): the owner of the folder (this user) can still change rights; a hostile process of the same user
is outside the promise.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from orch.errors import Refused

REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
SYSTEM_SID = "S-1-5-18"
_TIMEOUT = 20


def _windows() -> bool:
    return os.name == "nt"


def _no(why: str) -> Refused:
    return Refused(f"Refused: this orch folder is not private to you ({why}). Fix: orch doctor")


def _run_icacls(args: list[str]) -> tuple[int, str]:
    """icacls through an argv list (no shell). (exit code, output text). Tests replace this."""
    try:
        r = subprocess.run(
            ["icacls", *args],
            capture_output=True,
            timeout=_TIMEOUT,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise _no("Windows would not tell its rights") from e
    return r.returncode, (r.stdout or b"").decode("utf-8", errors="replace")


def _read_sddl_file(p: Path) -> str:
    raw = p.read_bytes()
    for enc in ("utf-16", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    raise _no("its rights could not be read")


_sid_cache: str | None = None


def _whoami() -> str:
    try:
        r = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            timeout=_TIMEOUT,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise _no("your account could not be found") from e
    return (r.stdout or b"").decode("utf-8", errors="replace")


def user_sid() -> str:
    global _sid_cache
    if _sid_cache is None:
        m = re.search(r'"(S-1-5-21(?:-\d+){4})"\s*$', _whoami().strip())
        if not m:
            raise _no("your account could not be found")
        _sid_cache = m.group(1)
    return _sid_cache


def _attrs(path: Path) -> int:
    """st_file_attributes of the path itself (not followed). Tests replace this."""
    return getattr(os.lstat(path), "st_file_attributes", 0)


def no_reparse(path: str | os.PathLike) -> None:
    """Refuse a symlink, junction or other reparse point on any part of the path that exists."""
    if not _windows():
        return
    p = Path(path)
    for c in [p, *p.parents]:
        if c == c.parent:  # the drive root
            continue
        try:
            a = _attrs(c)
        except FileNotFoundError:
            continue
        except OSError as e:
            raise _no("a part of its path could not be checked") from e
        if a & REPARSE:
            raise _no("part of its path is a link or junction")


def set_private(path: str | os.PathLike, is_dir: bool) -> None:
    """Only this user and SYSTEM, inheritance removed. Folders pass the rights on to what is made inside."""
    if not _windows():
        return
    p = Path(path)
    no_reparse(p)
    sid = user_sid()
    grant = "(OI)(CI)(F)" if is_dir else "(F)"
    rc, _out = _run_icacls(
        [str(p), "/inheritance:r", "/grant:r", f"*{sid}:{grant}", f"*{SYSTEM_SID}:{grant}"]
    )
    if rc != 0:
        raise _no("Windows would not set its rights")
    check_private(p)


_ACE = re.compile(r"\(([^()]*)\)")


def parse_sddl(sddl: str, sid: str) -> None:
    """Raise Refused unless the DACL is protected and grants only `sid` and SYSTEM. Fail closed."""
    line = next((x.strip() for x in sddl.splitlines() if x.strip().startswith("D:")), None)
    if line is None:
        raise _no("it has no rights list")
    body = line[2:]
    head, paren, rest = body.partition("(")
    if not paren:
        raise _no("its rights list is empty")
    if "P" not in head or re.fullmatch(r"[PAIR]*", head) is None:
        raise _no("it takes rights from its parent folder")
    tail = paren + rest
    if re.fullmatch(r"(?:\([^()]*\))+", tail) is None:
        raise _no("its rights list is not understood")
    aces = _ACE.findall(tail)
    seen_user = False
    for ace in aces:
        f = ace.split(";")
        if len(f) != 6:
            raise _no("its rights list is not understood")
        typ, flags, rights, _obj, _inh, who = f
        if typ != "A" or re.fullmatch(r"(OI|CI)*", flags) is None:
            raise _no("its rights list is not understood")
        if rights not in ("FA", "0x1f01ff"):
            raise _no("another right is set")
        if who in (SYSTEM_SID, "SY"):
            continue
        if who == sid:
            seen_user = True
            continue
        raise _no("another account can reach it")
    if not seen_user:
        raise _no("your account is not on its rights list")


def check_private(path: str | os.PathLike) -> None:
    """Refuse unless `path` (file or folder) is private to this user: see the module text. A missing path
    raises FileNotFoundError, like lstat does on POSIX."""
    if not _windows():
        return
    p = Path(path)
    _attrs(p)  # FileNotFoundError passes through: "not there" is not "wrong rights"
    no_reparse(p)
    sid = user_sid()
    with tempfile.TemporaryDirectory(prefix="orch-acl-") as td:
        out = Path(td) / "acl.txt"
        rc, _o = _run_icacls([str(p), "/save", str(out), "/c"])
        if rc != 0:
            raise _no("Windows would not tell its rights")
        try:
            text = _read_sddl_file(out)
        except OSError as e:
            raise _no("its rights could not be read") from e
    parse_sddl(text, sid)
