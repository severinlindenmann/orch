"""The ONE place that opens a workspace file whose name or content an agent could have planted, to read bytes
that are stored or hashed (`orch check record --output`, files_sig). Enforced here and nowhere else:

- the file is opened O_NOFOLLOW|O_NONBLOCK|O_NOCTTY (a link is never followed, a FIFO never blocks);
- the handle is fstat'ed: it must be a regular file with exactly ONE name (a hard link to ~/.ssh/... is
refused)
  and the same device/inode as the path had a moment before (a swap in between is refused);
- reads come from that handle and are bounded (a tail by pread, a hash in chunks up to a limit).
Special files (FIFO, device, socket, directory, and so a submodule folder) are never read: a hash counts only
their type.
`safe_read_tail` adds the name rules for `--output`: only plain log files inside the workspace."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
from pathlib import Path

from orch import winacl
from orch.errors import Refused

_FLAGS = (
    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0)
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
    if not parts:
        raise OSError("no file name")
    if _DIRFD:
        fd = _walk(root, parts[:-1])
        return parts[-1], {"dir_fd": fd}, fd
    full = Path(root).joinpath(*parts)
    if not Path(os.path.realpath(full.parent)).is_relative_to(Path(os.path.realpath(root))):
        raise OSError("outside the workspace")
    return str(full), {}, None


def _open_checked(name: str, kw: dict, check: str | None = None) -> tuple[int, os.stat_result] | None:
    """(fd, fstat) of a regular, single-name file opened without following a link; None for anything else."""
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
            ok = stat.S_ISREG(named.st_mode) and (st.st_dev, st.st_ino) == (real.st_dev, real.st_ino) == (
                named.st_dev,
                named.st_ino,
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
    parts = tuple(p for p in rel.split("/") if p)
    if not parts:
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
    `root` must be a real path. Windows has its own branch (`_read_private_windows`)."""
    parts = tuple(p for p in rel.split("/") if p)
    if winacl._windows():
        return _read_private_windows(Path(root), parts, limit)
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


def _read_private_windows(root: Path, parts: tuple[str, ...], limit: int) -> bytes | None:
    """read_private on Windows, where there is no dir_fd, no O_NOFOLLOW and os.open reads in text mode.
    Every part from `root` down is checked to be no link, junction or other reparse point (winacl). The file
    is opened in BINARY mode (text mode would turn CRLF into LF and stop at Ctrl-Z, so the size check would
    fail for a file written with CRLF). The handle must be a regular file with ONE name and the same volume
    and file index as the path's own lstat (a swap in between, or a link that was followed, is refused). The
    read is bounded by `limit` and must match the size. None for anything else (fail closed)."""
    if not parts or any(p in (".", "..") or "\\" in p or ":" in p for p in parts):
        return None
    full = Path(root).joinpath(*parts)
    try:
        for c in (Path(root).joinpath(*parts[:i]) for i in range(len(parts) + 1)):
            if winacl._attrs(c) & winacl.REPARSE:  # the root itself too
                return None
        named = os.lstat(full)
        if not stat.S_ISREG(named.st_mode):
            return None
        fd = os.open(full, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0))
    except (OSError, Refused):
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > limit:
            return None
        if (st.st_dev, st.st_ino) != (named.st_dev, named.st_ino):
            return None
        out = b""
        while len(out) <= st.st_size:
            data = os.read(fd, min(CHUNK, st.st_size - len(out) + 1))
            if not data:
                break
            out += data
        return out if len(out) == st.st_size else None
    except OSError:
        return None
    finally:
        os.close(fd)
