"""The ONE place that opens a workspace file whose name or content an agent could have planted, to read bytes
that are stored or hashed (`orch check record --output`, files_sig). Enforced here and nowhere else:

- the file is opened O_NOFOLLOW|O_NONBLOCK|O_NOCTTY (a link is never followed, a FIFO never blocks);
- the handle is fstat'ed: it must be a regular file with exactly ONE name (a hard link to ~/.ssh/... is
refused)
  and the same device/inode as the path had a moment before (a swap in between is refused);
- reads come from that handle and are bounded (a tail by pread, a hash in chunks up to a limit).
Special files (FIFO, device, socket, directory, and so a submodule folder) are never read: a hash counts only
their type.
`safe_read_tail` adds the name rules for `--output`: only plain log files inside the workspace.

Windows (no dir_fd, no O_NOFOLLOW) has ONE shared open path for all three readers (`_anchor`,
`_open_windows`): every folder from the root down is checked to be no reparse point, DOS device names and stream names are
refused, the file is opened with CreateFileW (FILE_FLAG_OPEN_REPARSE_POINT) and the handle must be a disk file
with one name, the same file index as the path's lstat, and the final path we meant. Known deviation from
POSIX: a file may be OPENED through a junction that was swapped in after the folder check (there is no dir_fd
to prevent it), but it is never READ: the final-path check refuses the handle before any byte is read."""

from __future__ import annotations

import ctypes
import fnmatch
import hashlib
import ntpath
import os
import stat
from pathlib import Path

from orch import winacl
from orch.errors import Refused

# O_BINARY: on Windows os.open defaults to TEXT mode (CRLF -> LF, Ctrl-Z ends the read),
# which breaks lengths and hashes.
_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_NOCTTY", 0)
    | getattr(os, "O_BINARY", 0)
    | getattr(os, "O_NOINHERIT", 0)
)
CHUNK = 64 * 1024
SECRETISH = (
    "*key*",
    "*secret*",
    "*token*",
    "*.pem",
    "*.p8",
    "*.p12",
    "*.pfx",
    "*.kdbx",
    "*password*",
    "*credential*",
    "*.gpg",
    "*.asc",
    ".netrc",
    ".pgpass",
    ".npmrc",
    ".pypirc",
    ".env*",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
)
_NO = "The output file must be a plain log file inside this workspace."


_DIRFD = os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY")
_DIRFLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


_DOS_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{i}" for i in "123456789\u00b9\u00b2\u00b3"}
    | {f"LPT{i}" for i in "123456789\u00b9\u00b2\u00b3"}
)


def _dos_device(part: str) -> bool:
    """Windows reserved device names, with or without an extension, any case (CON, nul.txt, COM1 ...)."""
    return part.split(".")[0].rstrip(" ").upper() in _DOS_DEVICES


def _plain(parts: tuple[str, ...]) -> bool:
    """A non-empty list of plain names: no empty part, no . or .., no slash or NUL inside a part (backslash
    and colon are Windows separators and streams: refused in the Windows branch of `_anchor`)."""
    return bool(parts) and all(p not in ("", ".", "..") and "/" not in p and "\0" not in p for p in parts)


def split_rel(rel: str) -> tuple[str, ...] | None:
    """The parts of a relative, `/` separated path, or None (empty, absolute, `.`/`..`/empty part, NUL)."""
    if not rel or rel.startswith("/"):
        return None
    parts = tuple(rel.split("/"))
    return parts if _plain(parts) else None


def _reparse(p: Path) -> bool:
    """Windows: is `p` itself a symlink, junction or other reparse point (not followed)? POSIX: never (those
    have O_NOFOLLOW and dir_fd). A path that can not be looked at counts as one: fail closed."""
    try:
        return bool(getattr(os.lstat(p), "st_file_attributes", 0) & winacl.REPARSE)
    except OSError:
        return True


def _walk(root: Path, parts: tuple[str, ...]) -> int:
    """POSIX: an fd of the folder root/parts, opened one folder at a time with dir_fd and O_NOFOLLOW, starting
    from root (a real path: callers resolve it once). A link anywhere on the way (also one swapped in
    while we look) fails, so what is
    opened is inside root by construction. Raises OSError."""
    cur = os.open(root, _DIRFLAGS)
    try:
        for part in parts:
            nxt = os.open(part, _DIRFLAGS, dir_fd=cur)
            os.close(cur)
            cur = nxt
    except OSError:
        os.close(cur)
        raise
    return cur


def _anchor(root: Path, parts: tuple[str, ...]) -> tuple[str, dict, int | None]:
    """(name, kwargs, dir fd to close) to act on the last part so that nothing outside root can be reached.
    Without dir_fd (Windows) the folder's real path is checked to be inside root instead; callers then
    compare the opened handle with the real path (`_open_checked(check=...)`). Raises OSError."""
    if not _plain(tuple(parts)):  # both branches: empty, ., .., separators inside a part
        raise OSError("not a plain name")
    if _DIRFD:
        fd = _walk(root, parts[:-1])
        return parts[-1], {"dir_fd": fd}, fd
    full = Path(root).joinpath(*parts)
    if any(
        ":" in p or "\\" in p or _dos_device(p) for p in parts
    ):  # no stream name (ADS), no device name (CON, NUL ...)
        raise OSError("not a plain name")
    for i in range(len(parts)):  # root and every folder below it: no link, junction or other reparse point
        if _reparse(Path(root).joinpath(*parts[:i])):
            raise OSError("a link on the way")
    if not Path(os.path.realpath(full.parent)).is_relative_to(Path(os.path.realpath(root))):
        raise OSError("outside the workspace")
    return str(full), {}, None


def _open_checked(name: str, kw: dict, check: str | None = None) -> tuple[int, os.stat_result] | None:
    """(fd, fstat) of a regular, single-name file opened without following a link; None for anything else."""
    if not kw and check is not None and winacl._windows():
        return _open_windows(name, check)
    try:
        fd = os.open(name, _FLAGS, **kw)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        ok = stat.S_ISREG(st.st_mode) and st.st_nlink == 1
        if ok and check is not None:  # no dir_fd: the handle must be the file the real path names
            real = os.stat(os.path.realpath(check))
            named = os.lstat(check)  # the path itself must be that regular file, not a link to one
            ok = (
                stat.S_ISREG(named.st_mode)
                and not _reparse(Path(check))
                and (st.st_dev, st.st_ino) == (real.st_dev, real.st_ino) == (named.st_dev, named.st_ino)
            )
    except OSError:
        os.close(fd)
        return None
    except BaseException:
        os.close(fd)
        raise
    if not ok:
        os.close(fd)
        return None
    return fd, st


# ------------------------------------------------------------------ Windows: the one open path (no dir_fd)
# Every Windows read of saferead ends here (read_private, file_state, safe_read_tail). The folders were
# checked one by one by `_anchor`, but a junction swapped in after that must not redirect the open: the
# handle is asked for its own final path, and it must be exactly the path we meant.


def _win_open_raw(path: str):
    """Windows only. CreateFileW (read, share all, FILE_FLAG_OPEN_REPARSE_POINT: a link is opened itself,
    never followed; no backup semantics: a folder can not be opened) -> (fd, file attributes, number of
    links, final path of the handle) or None. The fd is a binary os-level file that owns the handle. Tests
    replace this."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    V, D = ctypes.c_void_p, wintypes.DWORD
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, D, D, V, D, D, V]
    k32.CreateFileW.restype = V
    k32.CloseHandle.argtypes = [V]
    k32.GetFinalPathNameByHandleW.argtypes = [V, wintypes.LPWSTR, D, D]
    k32.GetFinalPathNameByHandleW.restype = D

    class Info(ctypes.Structure):
        _fields_ = [
            ("attrs", D),
            ("ctime", wintypes.FILETIME),
            ("atime", wintypes.FILETIME),
            ("mtime", wintypes.FILETIME),
            ("volume", D),
            ("size_high", D),
            ("size_low", D),
            ("links", D),
            ("index_high", D),
            ("index_low", D),
        ]

    k32.GetFileType.argtypes = [V]
    k32.GetFileType.restype = D
    k32.GetFileInformationByHandle.argtypes = [V, ctypes.POINTER(Info)]
    # GENERIC_READ, share read|write|delete, OPEN_EXISTING, OPEN_REPARSE_POINT | ATTRIBUTE_NORMAL
    h = k32.CreateFileW(path, 0x80000000, 7, None, 3, 0x00200000 | 0x80, None)
    if h is None or h == ctypes.c_void_p(-1).value:
        return None
    try:
        info = Info()
        buf = ctypes.create_unicode_buffer(32768)
        # VOLUME_NAME_DOS | FILE_NAME_NORMALIZED = 0
        if (
            k32.GetFileType(h) != 1  # FILE_TYPE_DISK: not a pipe, console or other device
            or not k32.GetFileInformationByHandle(h, ctypes.byref(info))
            or not k32.GetFinalPathNameByHandleW(h, buf, 32768, 0)
        ):
            k32.CloseHandle(h)
            return None
        fd = msvcrt.open_osfhandle(h, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except BaseException:
        k32.CloseHandle(h)
        raise
    return fd, info.attrs, info.links, buf.value


def _same_path(a: str, b: str) -> bool:
    """Windows path equality: case-insensitive, slash = backslash, and the long-path prefixes dropped."""

    def norm(p: str) -> str:
        if p.startswith("\\\\?\\UNC\\"):
            p = "\\\\" + p[8:]
        elif p.startswith("\\\\?\\"):
            p = p[4:]
        return ntpath.normcase(ntpath.normpath(p))

    return norm(a) == norm(b)


def _open_windows(path: str, expected: str) -> tuple[int, os.stat_result] | None:
    """(fd, fstat) of the regular, single-name file at `path` (a plain, already checked path); None when the
    handle is a folder or a link, has more than one name, or its final path is not `expected` (a junction was
    swapped in after the folders were checked). Any error: None."""
    try:
        got = _win_open_raw(path)
    except (OSError, ImportError, AttributeError, ValueError, TypeError, ctypes.ArgumentError):
        return None
    if got is None:
        return None
    fd, attrs, links, final = got
    try:
        st = os.fstat(fd)
        named = os.lstat(path)  # the path itself must name this very file (same volume and file index)
        ok = (
            (st.st_dev, st.st_ino) == (named.st_dev, named.st_ino)
            and not attrs
            & (0x10 | winacl.REPARSE)  # a folder, or a symlink/junction/other reparse point itself
            and links == 1
            and _same_path(final, expected)
            and stat.S_ISREG(st.st_mode)
        )
    except OSError:
        os.close(fd)
        return None
    except BaseException:
        os.close(fd)
        raise
    if not ok:
        os.close(fd)
        return None
    return fd, st


def _name_ok(parts: tuple[str, ...]) -> bool:
    for part in parts:
        low = part.lower()
        if (
            part in (".git", ".orch")
            or part.startswith(".")
            or any(fnmatch.fnmatch(low, g) for g in SECRETISH)
        ):
            return False
    return bool(parts)


def safe_read_tail(root: Path, path: str, limit: int) -> bytes:
    """The last `limit` bytes of a plain log file inside `root`. Refused (Refused) for anything else:
    outside the
    workspace, a path part that is `.git`, `.orch` or starts with a dot (.env, .ssh, .aws), a name like *key*,
    *secret*, *token*, *.pem, a link or hard link, a FIFO/device/directory. Never blocks, never reads more."""
    p = Path(path)
    p = p if p.is_absolute() else Path.cwd() / p
    base = Path(root).resolve()
    try:
        real = p.resolve(strict=True)
        inside = real.relative_to(base).parts
    except (OSError, ValueError):
        raise Refused(_NO) from None
    given = Path(os.path.abspath(p))  # the name as typed counts too, not only where a link leads
    for b in (base, Path(root).absolute()):
        try:
            asked = given.relative_to(b).parts
            break
        except ValueError:
            asked = inside
    if not (_name_ok(inside) and _name_ok(asked)):
        raise Refused(_NO)
    try:
        name, kw, dfd = _anchor(base, inside)
    except OSError:
        raise Refused(_NO) from None
    try:
        opened = _open_checked(name, kw, str(base.joinpath(*inside)))
    finally:
        if dfd is not None:
            os.close(dfd)
    if opened is None:
        raise Refused(_NO)
    fd, st = opened
    try:
        want = min(limit, st.st_size)
        if hasattr(os, "pread"):
            return os.pread(fd, want, st.st_size - want) if want else b""
        os.lseek(fd, st.st_size - want, os.SEEK_SET)
        return os.read(fd, want)
    finally:
        os.close(fd)


def file_state(root: Path, rel: str, hash_limit: int, budget: list[int]) -> str:
    """A short string for the file root/rel (rel as git lists it, `/` separated), for files_sig.
    Regular single-name file: sha256 of up to `hash_limit` bytes (streamed) + size (+ mtime and ctime when it
    is bigger than the limit). Link: its target text. Anything else (also a folder, so a submodule): its type
    only. Nothing outside root is ever touched (see `_walk`). `budget[0]` is the bytes that may still be
    read; spent, it becomes -1 (the caller then gives up)."""
    parts = split_rel(rel)
    if parts is None:
        return "?"
    try:
        name, kw, dfd = _anchor(root, parts)
    except OSError:
        return "?"
    try:
        return _state_at(name, kw, str(Path(root).joinpath(*parts)), hash_limit, budget)
    finally:
        if dfd is not None:
            os.close(dfd)


def _state_at(name: str, kw: dict, full: str, hash_limit: int, budget: list[int]) -> str:
    try:
        st = os.lstat(name, **kw)
    except OSError:
        return "?"
    mode = st.st_mode
    exe = "x" if mode & 0o111 else "-"
    if stat.S_ISLNK(mode):
        try:
            return "L:" + os.readlink(name, **kw)
        except OSError:
            return "L?"
    if not stat.S_ISREG(mode):
        return "S:" + oct(stat.S_IFMT(mode))
    if st.st_nlink != 1:
        return f"H:{exe}:{st.st_size}:{st.st_mtime_ns}:{st.st_ctime_ns}"
    if st.st_size > hash_limit:
        return f"B:{exe}:{st.st_size}:{st.st_mtime_ns}:{st.st_ctime_ns}"
    if budget[0] < st.st_size:
        budget[0] = -1
        return "?"
    opened = _open_checked(name, kw, None if kw else full)
    if opened is None:
        return "?"
    fd, st = opened
    h = hashlib.sha256()
    left = min(hash_limit, st.st_size)
    try:
        while left > 0:
            data = os.read(fd, min(CHUNK, left))
            if not data:
                break
            h.update(data)
            left -= len(data)
    except OSError:
        return "?"
    finally:
        os.close(fd)
    budget[0] -= st.st_size
    return f"F:{exe}:{h.hexdigest()}"


def read_private(root: Path, rel: str, limit: int) -> bytes | None:
    """All bytes of the guarded file root/rel (rel `/` separated, fixed names: no name rules), at most
    `limit`. None for a missing file, a link, a hard-linked or special file (FIFO, device, folder), a file
    swapped while we look, a file bigger than `limit` or any read error: the caller takes its fail-closed
    path. Opened like everything here (`_walk`, `_open_checked`): nothing outside root, never blocks.
    `root` must be a real path."""
    parts = split_rel(rel)
    if parts is None:
        return None
    try:
        name, kw, dfd = _anchor(Path(root), parts)
    except OSError:
        return None
    try:
        opened = _open_checked(name, kw, None if kw else str(Path(root).joinpath(*parts)))
    finally:
        if dfd is not None:
            os.close(dfd)
    if opened is None:
        return None
    fd, st = opened
    try:
        if st.st_size > limit:
            return None
        out = b""
        while len(out) <= st.st_size:
            data = os.read(fd, min(CHUNK, st.st_size - len(out) + 1))
            if not data:
                break
            out += data
        return out if len(out) == st.st_size else None  # it grew or shrank under us: not trusted
    except OSError:
        return None
    finally:
        os.close(fd)
