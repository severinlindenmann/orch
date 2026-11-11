"""Windows rights for the guarded orch home (issue #405, contracts/secrets.md "Windows").

POSIX has 0700/0600 and an lstat link check. Windows has neither, so this module does the same job there:

- set_private(path, is_dir): only this user and SYSTEM may reach it, inheritance removed.
- check_private(path): read the rights back and refuse unless the list is exactly this user and/or SYSTEM,
  allow-only, protected (no inheritance), and the path has no link or junction.
- no_reparse(path): no symlink, junction or other reparse point on any part of the path.
- allow_home(path) / check_scope(path): rights are only ever WRITTEN inside a guarded orch home that
  humanproof.guarded_home resolved in this process (its real path, so a junction can not lead out). Never the
  current folder, a workspace, the Public folder, the profile folder or anything above it. Fail closed.

No child process is ever started (a planted icacls.exe or whoami.exe in the current folder or on PATH can
not fake the answer): everything goes through the Win32 API with ctypes (advapi32). Rights are compared by
SID, so it works in every language. FAIL CLOSED: any API error or anything unexpected is a refusal.

On POSIX all three are no-ops: the existing mode and lstat checks stay there. Errors are plain words.
Level 1 (R1): the owner of the folder (this user) can still change rights; a hostile process of the same user
is outside the promise.
"""

from __future__ import annotations

import ntpath
import os
import struct
from pathlib import Path

from orch.errors import Refused

REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
TAG_SYMLINK = 0xA000000C  # IO_REPARSE_TAG_SYMLINK
TAG_MOUNT_POINT = 0xA0000003  # IO_REPARSE_TAG_MOUNT_POINT (a junction)
SYSTEM_SID = "S-1-5-18"
FILE_ALL_ACCESS = 0x1F01FF
ACE_ALLOWED = 0
ACE_INHERIT_FLAGS = 0x03  # OBJECT_INHERIT (1) | CONTAINER_INHERIT (2): allowed on a folder's own entries
ACE_INHERITED = 0x10  # INHERITED_ACE: a copy from the parent


def link_reparse(attrs: int, tag: int) -> bool:
    """A symlink or junction? Other reparse points (OneDrive/cloud placeholders, dedup, WSL...) are ordinary
    files for us. A reparse point whose tag is unknown (0) counts as a link: fail closed."""
    return bool(attrs & REPARSE) and (tag in (TAG_SYMLINK, TAG_MOUNT_POINT) or tag == 0)


def _windows() -> bool:
    return os.name == "nt"


class Unknown(Refused):
    """Windows could not tell (an API error, a long path, a virus scanner holding the file): refuse this call,
    but it is NOT a finding. Callers must not reset or quarantine anything because of it."""


def _cant(why: str) -> Unknown:
    return Unknown(f"Refused: this orch folder is not private to you ({why}).")


def _no(why: str) -> Refused:
    return Refused(f"Refused: this orch folder is not private to you ({why}).")


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
        raise _cant("an account name could not be read")
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
                raise _cant("your account could not be found")
            try:
                n = wintypes.DWORD(0)
                adv.GetTokenInformation(tok, 1, None, 0, ctypes.byref(n))  # TokenUser: ask the size
                buf = ctypes.create_string_buffer(n.value)
                if not adv.GetTokenInformation(tok, 1, buf, n, ctypes.byref(n)):
                    raise _cant("your account could not be found")
                sid_ptr = ctypes.c_void_p.from_buffer(buf).value  # TOKEN_USER starts with the SID pointer
                _sid_cache = _sid_string(ctypes, adv, k32, sid_ptr)
            finally:
                k32.CloseHandle(tok)
        except Refused:
            raise
        except Exception as e:  # noqa: BLE001 - fail closed on any API surprise
            raise _cant("your account could not be found") from e
    return _sid_cache


GENERIC_WRITE_DAC = 0x00040000  # WRITE_DAC
GENERIC_READ_CONTROL = 0x00020000  # READ_CONTROL
FILE_SHARE_ALL = 0x7  # READ | WRITE | DELETE
OPEN_EXISTING = 3
FLAG_BACKUP_SEMANTICS = 0x02000000  # lets CreateFileW open a folder
FLAG_OPEN_REPARSE_POINT = 0x00200000  # open a link itself, never its target


def _open_target(path: Path):
    """ONE handle on the target for the whole write (WRITE_DAC | READ_CONTROL; a link is opened itself, not
    followed). Scope check, rights write and read-back all go through this handle, so nothing can be swapped
    in between them. Tests replace this."""
    ctypes, wintypes, adv, k32 = _api()
    k32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    k32.CreateFileW.restype = ctypes.c_void_p
    h = k32.CreateFileW(
        str(path),
        GENERIC_WRITE_DAC | GENERIC_READ_CONTROL,
        FILE_SHARE_ALL,
        None,
        OPEN_EXISTING,
        FLAG_BACKUP_SEMANTICS | FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if h is None or h in (0, ctypes.c_void_p(-1).value):
        raise _no("Windows would not open it to set its rights")
    return h


def _close_target(h) -> None:
    _api()[3].CloseHandle(h)


def _handle_attrs(h) -> int:
    """File attributes of what the handle really is. Tests replace this."""
    ctypes, wintypes, adv, k32 = _api()

    class _Info(ctypes.Structure):
        _fields_ = [("attrs", wintypes.DWORD), ("rest", ctypes.c_ubyte * 48)]

    info = _Info()
    k32.GetFileInformationByHandle.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    if not k32.GetFileInformationByHandle(h, ctypes.byref(info)):
        raise _cant("a part of its path could not be checked")
    return info.attrs


def _handle_path(h) -> str:
    """The real path the handle points at (GetFinalPathNameByHandleW, no long-path prefix)."""
    ctypes, wintypes, adv, k32 = _api()
    k32.GetFinalPathNameByHandleW.argtypes = [
        ctypes.c_void_p,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    buf = ctypes.create_unicode_buffer(32768)
    n = k32.GetFinalPathNameByHandleW(h, buf, 32768, 0)
    if n == 0 or n >= 32768:
        raise _cant("a part of its path could not be checked")
    got = buf.value
    if got.startswith("\\\\?\\UNC\\"):
        return "\\\\" + got[8:]
    if got.startswith("\\\\?\\"):
        return got[4:]
    return got


def _set_dacl_on_handle(h, is_dir: bool, sid: str) -> None:
    """Replace the DACL through the handle: this user and SYSTEM, full control; protected."""
    ctypes, wintypes, adv, k32 = _api()
    adv.SetSecurityInfo.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.DWORD] + [ctypes.c_void_p] * 4
    adv.SetSecurityInfo.restype = wintypes.DWORD
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
        if adv.SetSecurityInfo(h, 1, 0x4 | 0x80000000, None, None, dacl, None) != 0:
            raise _no("Windows would not set its rights")
    finally:
        k32.LocalFree(sd)


def _write_dacl(path: Path, is_dir: bool, sid: str) -> None:
    """Replace the DACL by: this user and SYSTEM, full control; protected (inheritance removed).
    The target is opened ONCE; a link handle is refused; the scope guard judges the handle's final path; the
    rights are set and read back through that same handle (no check-then-use gap on the name)."""
    check_scope(path)  # the only DACL writer: the scope guard holds here too, whoever calls it (early, cheap)
    h = _open_target(path)
    try:
        if _handle_attrs(h) & REPARSE:
            raise _no("it is a link or junction")
        check_scope(_handle_path(h))  # what was REALLY opened, not the name
        _set_dacl_on_handle(h, is_dir, sid)
        protected, aces = _read_dacl(path, handle=h)
        parse_aces(protected, aces, sid)
    finally:
        _close_target(h)


def _read_dacl(path: Path, handle=None) -> tuple[bool, list[tuple[int, int, int, str]]]:
    """(protected, [(ace type, ace flags, access mask, SID string)]). Raises Refused when it cannot tell.
    With `handle` the rights are read from that open handle (not by name)."""
    ctypes, wintypes, adv, k32 = _api()
    dacl, sd = ctypes.c_void_p(), ctypes.c_void_p()
    if handle is not None:
        adv.GetSecurityInfo.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.DWORD] + [ctypes.c_void_p] * 5
        adv.GetSecurityInfo.restype = wintypes.DWORD
        rc = adv.GetSecurityInfo(handle, 1, 0x4, None, None, ctypes.byref(dacl), None, ctypes.byref(sd))
    else:
        rc = adv.GetNamedSecurityInfoW(
            str(path), 1, 0x4, None, None, ctypes.byref(dacl), None, ctypes.byref(sd)
        )
    if rc != 0:
        raise _cant("Windows would not tell its rights")
    try:
        if not dacl.value:  # a NULL DACL gives everyone access
            raise _no("everyone can reach it")
        ctl, rev = wintypes.WORD(), wintypes.DWORD()
        if not adv.GetSecurityDescriptorControl(sd, ctypes.byref(ctl), ctypes.byref(rev)):
            raise _cant("Windows would not tell its rights")
        protected = bool(ctl.value & 0x1000)  # SE_DACL_PROTECTED

        class _Size(ctypes.Structure):
            _fields_ = [("AceCount", wintypes.DWORD), ("Used", wintypes.DWORD), ("Free", wintypes.DWORD)]

        info = _Size()
        if not adv.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2):  # AclSizeInformation
            raise _cant("Windows would not tell its rights")
        aces = []
        for i in range(info.AceCount):
            p = ctypes.c_void_p()
            if not adv.GetAce(dacl, i, ctypes.byref(p)):
                raise _cant("Windows would not tell its rights")
            typ, flags, _size, mask = struct.unpack("<BBHI", ctypes.string_at(p.value, 8))
            if typ != ACE_ALLOWED:
                aces.append((typ, flags, mask, "?"))  # parse_aces refuses it; no SID layout assumed
                continue
            aces.append((typ, flags, mask, _sid_string(ctypes, adv, k32, p.value + 8)))
        return protected, aces
    finally:
        k32.LocalFree(sd)


def _owner_sid(path: Path) -> str:
    """The SID that owns the file or folder. Raises Refused when it cannot tell."""
    ctypes, wintypes, adv, k32 = _api()
    owner, sd = ctypes.c_void_p(), ctypes.c_void_p()
    rc = adv.GetNamedSecurityInfoW(  # OWNER_SECURITY_INFORMATION = 1
        str(path), 1, 0x1, ctypes.byref(owner), None, None, None, ctypes.byref(sd)
    )
    if rc != 0 or not owner.value:
        raise _cant("Windows would not tell who owns it")
    try:
        return _sid_string(ctypes, adv, k32, owner.value)
    finally:
        k32.LocalFree(sd)


def _attrs(path: Path) -> int:
    """st_file_attributes of the path itself (a link is not followed). Tests replace this."""
    st = os.lstat(path)
    if not hasattr(st, "st_file_attributes"):
        raise _cant("a part of its path could not be checked")
    return st.st_file_attributes


def _tag(path: Path) -> int:
    """st_reparse_tag of the path itself (not followed); 0 when unknown. Tests replace this."""
    return getattr(os.lstat(path), "st_reparse_tag", 0)


def _is_link(path: Path) -> bool:
    return link_reparse(_attrs(path), _tag(path)) if _attrs(path) & REPARSE else False


# ---------------------------------------------------------------------- the account's profile folder (B1)

_profile_cache: str | None = None


def _profile_raw() -> str | None:
    """GetUserProfileDirectoryW of this process's token (userenv), never %USERPROFILE%. Tests replace this."""
    ctypes, wintypes, adv, k32 = _api()
    ue = ctypes.WinDLL("userenv", use_last_error=True)
    ue.GetUserProfileDirectoryW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    tok = ctypes.c_void_p()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x8, ctypes.byref(tok)):
        return None
    try:
        n = wintypes.DWORD(0)
        ue.GetUserProfileDirectoryW(tok, None, ctypes.byref(n))  # asks for the size
        if n.value == 0 or n.value > 32768:
            return None
        buf = ctypes.create_unicode_buffer(n.value)
        if not ue.GetUserProfileDirectoryW(tok, buf, ctypes.byref(n)):
            return None
        return buf.value
    finally:
        k32.CloseHandle(tok)


def profile_dir() -> str:
    """This account's profile folder from the process token, never from the environment (an agent can set
    USERPROFILE, HOMEDRIVE and HOMEPATH). Fail closed."""
    global _profile_cache
    if _profile_cache is None:
        try:
            got = _profile_raw()
        except Exception as e:  # noqa: BLE001 - fail closed
            raise _cant("your profile folder could not be found") from e
        if not got or not ntpath.isabs(got):
            raise _cant("your profile folder could not be found")
        _profile_cache = got
    return _profile_cache


def _floor() -> str | None:
    """Where the link walk starts: the profile folder (what is above it is not ours to guard, and a profile
    moved by junction must keep working). None = walk everything. Tests replace this."""
    try:
        return profile_dir()
    except Refused:
        return None


# ------------------------------------------------------------------------------------------- the checks


def no_reparse(path: str | os.PathLike) -> None:
    """Refuse a symlink or junction on the path, from the profile folder downward (the folder itself and what
    is above it are not checked: an agent can not replace those, and a profile moved by junction works).
    A path outside the profile folder is walked up to the drive root. Other reparse points are allowed."""
    if not _windows():
        return
    p = Path(path)
    floor = _floor()
    fl = ntpath.normcase(ntpath.normpath(floor)) if floor else None
    for c in [p, *p.parents]:
        if c == c.parent:  # the drive root
            continue
        if fl is not None:
            cn = ntpath.normcase(ntpath.normpath(str(c)))
            if cn == fl:
                break  # the profile folder and everything above it
        try:
            if _is_link(c):
                raise _no("part of its path is a link or junction")
        except FileNotFoundError:
            continue
        except Refused:
            raise
        except OSError as e:
            raise _cant("a part of its path could not be checked") from e


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


# ------------------------------------------------------------------------- where rights may be written

_homes: set[str] = set()  # real paths (normcase) of the guarded homes this process resolved


def _real(path: str | os.PathLike) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def _inside(child: str, parent: str) -> bool:
    """child is parent or below it (both real, normcased)."""
    if child == parent:
        return True
    if os.path.splitdrive(child)[0] != os.path.splitdrive(parent)[0]:
        return False
    rel = os.path.relpath(child, parent)
    return rel != os.pardir and not rel.startswith(os.pardir + os.sep) and not os.path.isabs(rel)


def _guard_profile() -> str:
    """The profile folder (from the token) for the scope guard. Unknown = refused. Tests replace this."""
    return profile_dir()


def _forbidden(rp: str, *, is_home: bool = False) -> str | None:
    """Why `rp` (real, normcased) may never get its rights changed by orch, or None. A guarded HOME (already
    validated by humanproof: the account's own orch folder, or the test home) may contain the current folder:
    ORCH_HOME=~/.orch-test with a workspace under it and the shell standing in that workspace is normal."""
    if rp == os.path.dirname(rp):
        return "it is a drive root"
    try:
        prof = _real(_guard_profile())
    except Refused:
        return "your profile folder could not be found"
    if _inside(prof, rp):
        return "it is your profile folder or above it"
    public = _real(os.path.join(os.path.dirname(prof), "Public"))
    if _inside(rp, public):
        return "it is in the shared Public folder"
    if not _inside(rp, prof):
        return "it is outside your profile folder"
    try:
        cwd = _real(os.getcwd())
    except OSError:
        return "the current folder could not be found"
    if not is_home and _inside(cwd, rp):
        return "it is the current folder or above it"
    return None


def allow_home(path: str | os.PathLike) -> None:
    """Record a guarded home (humanproof.guarded_home calls this). Windows only; a home in a forbidden place
    (Public, the profile folder itself, a drive root) is refused."""
    if not _windows():
        return
    rp = _real(path)
    why = _forbidden(rp, is_home=True)
    if why:
        raise _no(f"orch would change rights outside its own folder: {why}")
    _homes.add(rp)


def check_scope(path: str | os.PathLike) -> None:
    """Refuse unless `path` (real path: links and junctions resolved) is inside a guarded home recorded by
    allow_home, and is not a forbidden place. Called before EVERY rights write. No home recorded = refused."""
    if not _windows():
        return
    rp = _real(path)
    why = _forbidden(rp, is_home=rp in _homes)
    if why is None and not any(_inside(rp, h) for h in _homes):
        why = "it is not inside orch's own folder"
    if why:
        raise _no(f"orch will not change the rights of {path}: {why}")


def set_private(path: str | os.PathLike, is_dir: bool) -> None:
    """Only this user and SYSTEM, inheritance removed; then read back and verified. Only inside a guarded home
    (check_scope runs before any write)."""
    if not _windows():
        return
    p = Path(path)
    check_scope(p)
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
        raise _cant("Windows would not tell its rights") from e
    parse_aces(protected, aces, sid)


def ensure_private(path: str | os.PathLike) -> None:
    """check_private, but a FOLDER that is OWNED by this user and too open (made before this check
    existed, or by an older version) is tightened to user+SYSTEM and verified, so nobody is locked out. That
    only narrows access. Refused: another owner, a link or junction, or when tightening or verifying fails."""
    if not _windows():
        return
    p = Path(path)
    try:
        check_private(p)
        return
    except FileNotFoundError:
        raise
    except Refused:
        pass
    no_reparse(p)  # a link or junction is never tightened
    try:
        owner = _owner_sid(p)
    except Refused:
        raise
    except Exception as e:  # noqa: BLE001 - fail closed
        raise _cant("Windows would not tell who owns it") from e
    if owner != user_sid():
        raise _no("it belongs to another account")
    set_private(p, True)


def file_check(path: str | os.PathLike) -> str | None:
    """The hook for humanproof.FILE_CHECKS: a secret or integrity file is never tightened and trusted.
    "acl" = a real finding (loose, a link in its place): the caller resets the protection. "unknown" = Windows
    could not tell (API error): the caller refuses this call only, with no reset. None = private. A missing
    file raises FileNotFoundError, like lstat."""
    if not _windows():
        return None
    try:
        check_private(path)
    except FileNotFoundError:
        raise
    except Unknown:
        return "unknown"
    except Refused:
        return "acl"
    except Exception:  # noqa: BLE001 - not a finding, just not known
        return "unknown"
    return None
