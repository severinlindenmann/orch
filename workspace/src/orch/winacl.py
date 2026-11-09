"""Windows rights for the guarded orch home (issue #405, contracts/secrets.md "Windows").

POSIX has 0700/0600 and an lstat link check. Windows has neither, so this module does the same job there:

- set_private(path, is_dir): only this user and SYSTEM may reach it, inheritance removed.
- check_private(path): read the rights back and refuse unless the list is exactly this user and/or SYSTEM,
  allow-only, protected (no inheritance), and the path has no link or junction.
- no_reparse(path): no symlink, junction or other reparse point on any part of the path.

No child process is ever started (a planted icacls.exe or whoami.exe in the current folder or on PATH can
not fake the answer): everything goes through the Win32 API with ctypes (advapi32). Rights are compared by
SID, so it works in every language. FAIL CLOSED: any API error or anything unexpected is a refusal.

On POSIX all three are no-ops: the existing mode and lstat checks stay there. Errors are plain words.
Level 1 (R1): the owner of the folder (this user) can still change rights; a hostile process of the same user
is outside the promise.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

from orch.errors import Refused

REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
SYSTEM_SID = "S-1-5-18"
FILE_ALL_ACCESS = 0x1F01FF
ACE_ALLOWED = 0
ACE_INHERIT_FLAGS = 0x03  # OBJECT_INHERIT (1) | CONTAINER_INHERIT (2): allowed on a folder's own entries
ACE_INHERITED = 0x10  # INHERITED_ACE: a copy from the parent


def _windows() -> bool:
    return os.name == "nt"


def _no(why: str) -> Refused:
    return Refused(f"Refused: this orch folder is not private to you ({why}). Fix: orch doctor")


# ------------------------------------------------------------------------------ Win32 (ctypes), Windows only


def _api():
    import ctypes
    from ctypes import wintypes

    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    V, W, D = ctypes.c_void_p, ctypes.c_wchar_p, wintypes.DWORD
    k32.GetCurrentProcess.restype = V
    k32.LocalFree.argtypes = [V]
    k32.LocalFree.restype = V
    k32.CloseHandle.argtypes = [V]
    adv.OpenProcessToken.argtypes = [V, D, ctypes.POINTER(V)]
    adv.GetTokenInformation.argtypes = [V, ctypes.c_int, V, D, ctypes.POINTER(D)]
    adv.ConvertSidToStringSidW.argtypes = [V, ctypes.POINTER(ctypes.c_void_p)]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        W,
        D,
        ctypes.POINTER(V),
        V,
    ]
    adv.GetSecurityDescriptorDacl.argtypes = [
        V,
        ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(V),
        ctypes.POINTER(wintypes.BOOL),
    ]
    adv.SetNamedSecurityInfoW.argtypes = [W, ctypes.c_int, D, V, V, V, V]
    adv.SetNamedSecurityInfoW.restype = D
    adv.GetNamedSecurityInfoW.argtypes = [
        W,
        ctypes.c_int,
        D,
        V,
        V,
        ctypes.POINTER(V),
        V,
        ctypes.POINTER(V),
    ]
    adv.GetNamedSecurityInfoW.restype = D
    adv.GetSecurityDescriptorControl.argtypes = [V, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(D)]
    adv.GetAclInformation.argtypes = [V, V, D, ctypes.c_int]
    adv.GetAce.argtypes = [V, D, ctypes.POINTER(V)]
    return ctypes, wintypes, adv, k32


def _sid_string(ctypes, adv, k32, sid_ptr) -> str:
    out = ctypes.c_void_p()
    if not adv.ConvertSidToStringSidW(sid_ptr, ctypes.byref(out)):
        raise _no("an account name could not be read")
    try:
        return ctypes.wstring_at(out.value)
    finally:
        k32.LocalFree(out)


_sid_cache: str | None = None


def user_sid() -> str:
    """The SID of the account this process runs as (from its token; not from a program, a name or env)."""
    global _sid_cache
    if _sid_cache is None:
        try:
            ctypes, wintypes, adv, k32 = _api()
            tok = ctypes.c_void_p()
            if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x8, ctypes.byref(tok)):  # TOKEN_QUERY
                raise _no("your account could not be found")
            try:
                n = wintypes.DWORD(0)
                adv.GetTokenInformation(tok, 1, None, 0, ctypes.byref(n))  # TokenUser: ask the size
                buf = ctypes.create_string_buffer(n.value)
                if not adv.GetTokenInformation(tok, 1, buf, n, ctypes.byref(n)):
                    raise _no("your account could not be found")
                sid_ptr = ctypes.c_void_p.from_buffer(buf).value  # TOKEN_USER starts with the SID pointer
                _sid_cache = _sid_string(ctypes, adv, k32, sid_ptr)
            finally:
                k32.CloseHandle(tok)
        except Refused:
            raise
        except Exception as e:  # noqa: BLE001 - fail closed on any API surprise
            raise _no("your account could not be found") from e
    return _sid_cache


def _write_dacl(path: Path, is_dir: bool, sid: str) -> None:
    """Replace the DACL by: this user and SYSTEM, full control; protected (inheritance removed)."""
    ctypes, wintypes, adv, k32 = _api()
    inh = "OICI" if is_dir else ""
    sddl = f"D:P(A;{inh};FA;;;{SYSTEM_SID})(A;{inh};FA;;;{sid})"
    sd = ctypes.c_void_p()
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(sd), None):
        raise _no("Windows would not set its rights")
    try:
        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        dacl = ctypes.c_void_p()
        if not adv.GetSecurityDescriptorDacl(
            sd, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)
        ) or not (present.value and dacl.value):
            raise _no("Windows would not set its rights")
        # DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION; SE_FILE_OBJECT = 1
        rc = adv.SetNamedSecurityInfoW(str(path), 1, 0x4 | 0x80000000, None, None, dacl, None)
        if rc != 0:
            raise _no("Windows would not set its rights")
    finally:
        k32.LocalFree(sd)


def _read_dacl(path: Path) -> tuple[bool, list[tuple[int, int, int, str]]]:
    """(protected, [(ace type, ace flags, access mask, SID string)]). Raises Refused when it cannot tell."""
    ctypes, wintypes, adv, k32 = _api()
    dacl, sd = ctypes.c_void_p(), ctypes.c_void_p()
    rc = adv.GetNamedSecurityInfoW(str(path), 1, 0x4, None, None, ctypes.byref(dacl), None, ctypes.byref(sd))
    if rc != 0:
        raise _no("Windows would not tell its rights")
    try:
        if not dacl.value:  # a NULL DACL gives everyone access
            raise _no("everyone can reach it")
        ctl, rev = wintypes.WORD(), wintypes.DWORD()
        if not adv.GetSecurityDescriptorControl(sd, ctypes.byref(ctl), ctypes.byref(rev)):
            raise _no("Windows would not tell its rights")
        protected = bool(ctl.value & 0x1000)  # SE_DACL_PROTECTED

        class _Size(ctypes.Structure):
            _fields_ = [("AceCount", wintypes.DWORD), ("Used", wintypes.DWORD), ("Free", wintypes.DWORD)]

        info = _Size()
        if not adv.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2):  # AclSizeInformation
            raise _no("Windows would not tell its rights")
        aces = []
        for i in range(info.AceCount):
            p = ctypes.c_void_p()
            if not adv.GetAce(dacl, i, ctypes.byref(p)):
                raise _no("Windows would not tell its rights")
            typ, flags, _size, mask = struct.unpack("<BBHI", ctypes.string_at(p.value, 8))
            if typ != ACE_ALLOWED:
                aces.append((typ, flags, mask, "?"))  # parse_aces refuses it; no SID layout assumed
                continue
            aces.append((typ, flags, mask, _sid_string(ctypes, adv, k32, p.value + 8)))
        return protected, aces
    finally:
        k32.LocalFree(sd)


def _attrs(path: Path) -> int:
    """st_file_attributes of the path itself (a link is not followed). Tests replace this."""
    st = os.lstat(path)
    if not hasattr(st, "st_file_attributes"):
        raise _no("a part of its path could not be checked")
    return st.st_file_attributes


# ------------------------------------------------------------------------------------------- the checks


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
        except Refused:
            raise
        except OSError as e:
            raise _no("a part of its path could not be checked") from e
        if a & REPARSE:
            raise _no("part of its path is a link or junction")


def parse_aces(protected: bool, aces: list[tuple[int, int, int, str]], sid: str) -> None:
    """Raise Refused unless the DACL is protected and allows only `sid` and SYSTEM (both with full control,
    at least `sid` present). Anything else, or anything odd, is a refusal."""
    if not protected:
        raise _no("it takes rights from its parent folder")
    seen_user = False
    for typ, flags, mask, who in aces:
        if typ != ACE_ALLOWED:
            raise _no("its rights list is not understood")
        if flags & ACE_INHERITED:
            raise _no("it takes rights from its parent folder")
        if flags & ~ACE_INHERIT_FLAGS:
            raise _no("its rights list is not understood")
        if who not in (SYSTEM_SID, sid):
            raise _no("another account can reach it")
        if mask & FILE_ALL_ACCESS != FILE_ALL_ACCESS:
            raise _no("a right is missing")
        if who == sid:
            seen_user = True
    if not seen_user:
        raise _no("your account is not on its rights list")


def set_private(path: str | os.PathLike, is_dir: bool) -> None:
    """Only this user and SYSTEM, inheritance removed; then read back and verified."""
    if not _windows():
        return
    p = Path(path)
    no_reparse(p)
    try:
        _write_dacl(p, is_dir, user_sid())
    except Refused:
        raise
    except Exception as e:  # noqa: BLE001 - fail closed
        raise _no("Windows would not set its rights") from e
    check_private(p)


def check_private(path: str | os.PathLike) -> None:
    """Refuse unless `path` (file or folder) is private to this user: see the module text. A missing path
    raises FileNotFoundError, like lstat does on POSIX."""
    if not _windows():
        return
    p = Path(path)
    _attrs(p)  # FileNotFoundError passes through: "not there" is not "wrong rights"
    no_reparse(p)
    sid = user_sid()
    try:
        protected, aces = _read_dacl(p)
    except Refused:
        raise
    except Exception as e:  # noqa: BLE001 - fail closed
        raise _no("Windows would not tell its rights") from e
    parse_aces(protected, aces, sid)
