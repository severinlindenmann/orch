"""Private, hidden activity records and explicit retention.

All path I/O is confined to the core below. Windows re-lstat narrows but cannot
close the path replacement race; POSIX walks use pinned directory descriptors.
"""

import errno
import hashlib
import json
import os
import re
import stat
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

from jsonschema import Draft202012Validator, FormatChecker

from orch import hider as hiding
from orch import humanproof, record_auth
from orch.collect_execjson import _hash, detail_name
from orch.errors import Refused
from orch.hider import Hider, NoHiderError
from orch.phone_view import redact
from orch.record_files import MAX_INPUT, file_ok

_OFF = "Recording is off until key hiding is ready."
_OFF_KEY = "Recording is off until orch's protection is ready."
# The one place for the plain words about records made before orch checked them (Focus and the phone show it).
UNCHECKED_TEXT = "These records were made before orch checked them."
# The one place for the marker of a run by a helper whose deny rules orch cannot set (codex, generic).
UNPROTECTED_TEXT = "Records from this helper can't be fully checked."
_INVALID = "This record entry is not valid."
_RUN = r"r_[a-z0-9_]{6,32}"
_FILE = r"[0-9a-f]{32}"
_PART = r"[A-Za-z0-9_.-]{1,80}"
_MAX_FILES = 8
TAMPER_REASONS = (
    "link",
    "reparse",
    "hardlink",
    "foreign_owner",
    "not_regular",
    "not_dir",
    "swapped",
    "content",
    "removed",
    "unverified",
    "old_key",
)
_MESSAGES = {
    "tampered": (
        "Some records of this run were changed outside orch. "
        "To be safe, orch does not show them. Nothing was deleted."
    ),
    "content": (
        "Some records of this run were changed outside orch. "
        "To be safe, orch does not show them. Nothing was deleted."
    ),
    "removed": "Some records of this run were removed outside orch.",
    "unverified": "orch cannot check these records, so it does not show them.",
    "old_key": (
        "These records were made before orch's protection was reset. "
        "orch cannot check them any more, so it does not show them."
    ),
    "unchecked": UNCHECKED_TEXT,
    "swapped_detail": "Details changed outside orch.",
    "io": "The records of this run cannot be read right now. Try again later.",
    "missing": "There are no records for this run.",
    "pending": "Some records of this run are waiting to be written.",
    "torn": "The last entry of this job was cut off.",
}


class RecordRefused(Refused):
    code = "refused"

    def __init__(self, message=_INVALID, *, reason=None):
        super().__init__(message)
        self.reason = reason
        self.alert = None


class RecordInvalid(RecordRefused):
    code = "invalid"


class RecordOff(RecordRefused):
    code = "refused"


class RecordFull(RecordRefused):
    code = "cap"


class RecordBusy(RecordRefused):
    code = "busy"


class RecordUnavailable(RecordRefused):
    code = "not_available"

    def __init__(self, reason="io"):
        super().__init__(_MESSAGES[reason], reason=reason)


class RecordTampered(RecordRefused):
    code = "tampered"

    def __init__(self, reason, message=None):
        super().__init__(message or _MESSAGES.get(reason, _MESSAGES["tampered"]), reason=reason)


T = TypeVar("T")
Status = Literal["ok", "unavailable", "tampered"]


@dataclass(frozen=True)
class ReadResult(Generic[T]):
    status: Status
    value: T | None = None
    reason: str | None = None
    message: str | None = None
    changed: int = 0  # lines of the run that are not genuine (planted, edited, replayed, no auth)
    removed: int = 0  # genuine lines that are gone
    unchecked: int = 0  # lines made before orch checked them (never counted as orch-checked)
    legacy: bool = False  # the whole run is such (no sealed line, no chain head)
    pending: int = 0
    alert: dict | None = None

    def unwrap(self) -> T:
        if self.status != "ok":
            error = (
                RecordTampered(self.reason, self.message)
                if self.status == "tampered"
                else RecordUnavailable(self.reason)
            )
            error.alert = self.alert
            raise error
        return self.value

    @classmethod
    def from_error(cls, error, workspace, target, run=None, seen_by="reader"):
        alert = None
        if isinstance(error, RecordTampered):
            alert = _alert(workspace, target=target, run=run, reason=error.reason, seen_by=seen_by)
            error.alert = alert
        return cls(
            "tampered" if isinstance(error, RecordTampered) else "unavailable",
            reason=error.reason,
            message=str(error),
            alert=alert,
        )


RunRead = ReadResult[list[dict]]


def record_dir(workspace: Path) -> Path:
    return Path(workspace) / ".orch" / "record"


def registered_writer(workspace: Path) -> "RecordWriter":
    try:
        return RecordWriter(workspace, hider=hiding.current_hider())
    except NoHiderError:
        raise RecordOff(_OFF) from None


def _name(value: Any, pattern: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise RecordInvalid(_INVALID)
    return value


# I/O core. Only this section uses filesystem operations, including fd operations.
# os.replace uses rename's dir_fd implementation but is absent from supports_dir_fd
# on some Python builds; os.rename is the corresponding capability probe.
def _io_setup():
    try:
        import fcntl
    except ImportError:
        fcntl = None
    try:
        import msvcrt
    except ImportError:
        msvcrt = None
    return (
        os.name == "posix"
        and {os.open, os.mkdir, os.unlink, os.rmdir, os.rename, os.stat} <= os.supports_dir_fd
        and os.scandir in os.supports_fd,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
        getattr(os, "O_NOFOLLOW", 0),
        fcntl,
        msvcrt,
    )


_FD, _DIR, _NOFOLLOW, _FCNTL, _MSVCRT = _io_setup()
_REPARSE = 0x400
_SURROGATE = 0x20000000
_LOCK_WAIT = 30.0


def _io_error(error):
    if error.errno in (errno.ELOOP, errno.EMLINK):
        return RecordTampered("link")
    if error.errno == errno.ENOTDIR:
        return RecordTampered("not_dir")
    if error.errno in (errno.ENXIO, errno.EISDIR, errno.EWOULDBLOCK):
        return RecordTampered("not_regular")
    return RecordUnavailable("missing" if error.errno == errno.ENOENT else "io")


@contextmanager
def _io(target=None):
    try:
        yield
    except (RecordTampered, RecordUnavailable) as error:
        if target is not None and not hasattr(error, "target"):
            error.target = target
        raise
    except OSError as error:
        converted = _io_error(error)
        if target is not None:
            converted.target = target
        raise converted from None


def _parts(rel):
    if not isinstance(rel, tuple):
        raise RecordInvalid()
    for part in rel:
        _name(part, _PART)
        if part in (".", ".."):
            raise RecordInvalid()


def _check_info(info, *, want_dir=False, owner=True):
    if want_dir:
        if not stat.S_ISDIR(info.st_mode):
            raise RecordTampered("not_dir")
    else:
        if not stat.S_ISREG(info.st_mode):
            raise RecordTampered("not_regular")
        if info.st_nlink == 0:
            raise RecordUnavailable("missing")
        if info.st_nlink != 1:
            raise RecordTampered("hardlink")
    if owner and os.name == "posix" and info.st_uid != os.geteuid():
        raise RecordTampered("foreign_owner")


def _check_fd(fd, *, want_dir=False):
    with _io():
        _check_info(os.fstat(fd), want_dir=want_dir)


def _reparse(info):
    tag = getattr(info, "st_reparse_tag", None)
    return bool(getattr(info, "st_file_attributes", 0) & _REPARSE) and (tag is None or bool(tag & _SURROGATE))


def _path_info(path, *, want_dir=False):
    info = os.lstat(path)
    if _reparse(info):
        raise RecordTampered("reparse")
    if stat.S_ISLNK(info.st_mode):
        raise RecordTampered("link")
    _check_info(info, want_dir=want_dir)
    return info


@dataclass
class _Dir:
    fd: int | None
    path: Path
    walked: list


@contextmanager
def _walk(ws, rel_dir, *, create=False):
    _parts(rel_dir)
    fd = None
    with _io():
        try:
            if _FD:
                fd = os.open(ws, _DIR)
            path, walked = Path(ws), []
            for part in (".orch", "record", *rel_dir):
                made = False
                if create:
                    try:
                        os.mkdir(part if _FD else path / part, 0o700, **({"dir_fd": fd} if _FD else {}))
                        made = True
                    except FileExistsError:
                        pass
                path = path / part
                if _FD:
                    # lstat only classifies a failed O_DIRECTORY open; never authorizes it.
                    try:
                        child = os.open(part, _DIR | _NOFOLLOW, dir_fd=fd)
                    except NotADirectoryError:
                        if stat.S_ISLNK(os.stat(part, dir_fd=fd, follow_symlinks=False).st_mode):
                            raise RecordTampered("link") from None
                        raise
                    os.close(fd)
                    fd = child
                    _check_fd(fd, want_dir=True)
                    if made and hasattr(os, "fchmod"):
                        os.fchmod(fd, 0o700)
                else:
                    info = _path_info(path, want_dir=True)
                    walked.append((path, info))
            yield _Dir(fd, path, walked)
        finally:
            if fd is not None:
                os.close(fd)


def _verify_walk(directory):
    for path, before in directory.walked:
        after = os.lstat(path)
        if (
            _reparse(after)
            or stat.S_ISLNK(after.st_mode)
            or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
        ):
            raise RecordTampered("swapped")


def _open(ws, rel, mode, *, create_dirs=False, _directory=None):
    _parts(rel)
    flags = {
        "lock": os.O_RDWR,
        "read": os.O_RDONLY,
        "append": os.O_WRONLY | os.O_APPEND | os.O_CREAT,
        "create_excl": os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        "read_append": os.O_RDWR | os.O_APPEND | os.O_CREAT,
    }[mode]
    flags |= _NOFOLLOW | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
    target = (
        "lock"
        if rel[-1].endswith(".lock")
        else "meta"
        if rel == ("meta.json",)
        else {
            "runs": "run",
            "detail": "detail",
            "alerts": "alerts",
        }.get(rel[0], "folder")
    )
    walk = nullcontext(_directory) if _directory is not None else _walk(ws, rel[:-1], create=create_dirs)
    with _io(target), walk as directory:
        fd = None
        try:
            if not _FD:
                try:
                    _path_info(directory.path / rel[-1])
                except FileNotFoundError:
                    pass
            try:
                fd = os.open(
                    rel[-1] if _FD else directory.path / rel[-1],
                    flags,
                    0o600,
                    **({"dir_fd": directory.fd} if _FD else {}),
                )
            except FileExistsError:
                if mode == "create_excl":
                    return None
                raise
            _check_fd(fd)
            if not _FD:
                after = os.lstat(directory.path / rel[-1])
                before = os.fstat(fd)
                if _reparse(after) or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
                    raise RecordTampered("swapped")
                _verify_walk(directory)
            if mode != "read" and hasattr(os, "fchmod"):
                os.fchmod(fd, 0o600)
            result, fd = fd, None
            return result
        finally:
            if fd is not None:
                if mode == "create_excl" and rel[-1].endswith(".lock"):
                    _release_lock(ws, rel, fd, _directory=directory)
                else:
                    os.close(fd)


def _close(fd):
    with _io():
        os.close(fd)


def _read_bytes(fd):
    with _io():
        os.lseek(fd, 0, os.SEEK_SET)
        chunks = []
        while chunk := os.read(fd, 65536):
            chunks.append(chunk)
        return b"".join(chunks)


def _write(fd, payload):
    with _io():
        if os.write(fd, payload) != len(payload):
            raise RecordUnavailable("io")


def _entries(ws, rel_dir):
    with _walk(ws, rel_dir) as directory:
        with os.scandir(directory.fd if _FD else directory.path) as entries:
            return [entry.name for entry in entries]


def _unlink(ws, rel, *, expected=None):
    _parts(rel)
    try:
        with _walk(ws, rel[:-1]) as directory:
            name = rel[-1] if _FD else directory.path / rel[-1]
            kw = {"dir_fd": directory.fd} if _FD else {}
            if expected is not None:
                current = os.stat(name, follow_symlinks=False, **kw)
                before = os.fstat(expected)
                if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
                    return False
            os.unlink(name, **kw)
            return True
    except RecordUnavailable as error:
        if error.reason != "missing":
            raise
        return False


def _write_new(ws, rel, payload, *, expected=None):
    temporary = (*rel[:-1], "tmp_" + uuid.uuid4().hex)
    with _walk(ws, rel[:-1], create=True) as directory:
        # Keep the same parent descriptor through creation and publication.
        name = temporary[-1] if _FD else directory.path / temporary[-1]
        kw = {"dir_fd": directory.fd} if _FD else {}
        fd = _open(ws, temporary, "create_excl", _directory=directory)
        if fd is None:
            raise RecordUnavailable("io")
        try:
            _check_fd(fd)
            _write(fd, payload)
            with _io():
                os.fsync(fd)
            _verify_walk(directory)
            if expected is not None:
                # the file we read through `expected` must still be the one at this name (no swap in between)
                with _io():
                    current = os.stat(
                        rel[-1] if _FD else directory.path / rel[-1], follow_symlinks=False, **kw
                    )
                    before = os.fstat(expected)
                if (current.st_dev, current.st_ino, current.st_nlink) != (
                    before.st_dev,
                    before.st_ino,
                    before.st_nlink,
                ):
                    raise RecordTampered("swapped")
            try:
                existing = _open(ws, rel, "read", _directory=directory)
            except RecordUnavailable as error:
                if error.reason != "missing":
                    raise
            else:
                _close(existing)
            # temp file + rename: a reader sees the old file or the new one, never a half-written one; a
            # failed rename leaves the old file as it was (a RecordUnavailable: the caller marks detail_lost)
            with _io():
                os.replace(
                    name,
                    rel[-1] if _FD else directory.path / rel[-1],
                    **({"src_dir_fd": directory.fd, "dst_dir_fd": directory.fd} if _FD else {}),
                )
            if _FD:
                with _io():
                    os.fsync(directory.fd)
        finally:
            os.close(fd)
            try:
                os.unlink(name, **kw)
            except FileNotFoundError:
                pass
    return True


_MAX_DEPTH = 8  # no folder tree of orch's own is deeper; a planted deeper one is refused, never walked


def _size(ws, rel):
    if len(rel) > _MAX_DEPTH:
        raise RecordTampered("not_dir")
    try:
        try:
            fd = _open(ws, rel, "read")
        except RecordTampered as error:
            if error.reason != "not_regular":
                raise
            try:
                names = _entries(ws, rel)
            except RecordTampered as folder_error:
                if folder_error.reason == "not_dir":
                    raise error from None
                raise
            return sum(_size(ws, (*rel, name)) for name in names)
        try:
            with _io():
                return os.fstat(fd).st_size
        finally:
            _close(fd)
    except RecordUnavailable as error:
        if error.reason != "missing":
            raise
        return 0


def _rmtree(ws, rel):
    # Preflight the entire tree before deleting anything; directory links refuse. Never used on pending/
    # (spool entries are flat files: see RecordWriter._reject).
    _size(ws, rel)
    try:
        names = _entries(ws, rel)
    except RecordUnavailable as error:
        if error.reason != "missing":
            raise
        return
    except RecordTampered as error:
        if error.reason != "not_dir":
            raise
        _unlink(ws, rel)
        return
    for name in names:
        _rmtree(ws, (*rel, name))
    with _walk(ws, rel[:-1]) as directory:
        os.rmdir(rel[-1] if _FD else directory.path / rel[-1], **({"dir_fd": directory.fd} if _FD else {}))


def _mtime_iso(ws, rel):
    """When the file was last written (UTC, whole seconds), or None when there is no such file."""
    try:
        fd = _open(ws, rel, "read")
    except RecordUnavailable as error:
        if error.reason != "missing":
            raise
        return None
    try:
        with _io():
            stamp = os.fstat(fd).st_mtime
    finally:
        _close(fd)
    return datetime.fromtimestamp(stamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rename_aside(ws, rel, run):
    """Move one entry (of any kind, a link is not followed) out of pending/<run>/ into quarantine/<run>/ (a
    folder only orch writes and nothing reads), atomically, under a name orch makes. No recursion, nothing is
    deleted, and the entry can no longer be mistaken for a spool entry."""
    _parts(rel)
    aside = "q_" + uuid.uuid4().hex
    with _walk(ws, ("quarantine", run), create=True) as target, _walk(ws, rel[:-1]) as source:
        kw = {"src_dir_fd": source.fd, "dst_dir_fd": target.fd} if _FD else {}
        src = rel[-1] if _FD else source.path / rel[-1]
        dst = aside if _FD else target.path / aside
        with _io():
            os.rename(src, dst, **kw)


def _rmdir_empty(ws, rel):
    """Remove the folder only if it is empty, in ONE step: rmdir itself fails on a folder that is not empty,
    so a file another writer created in between is never removed with it (no check-then-delete). True when
    it went; False when it is not empty or already gone."""
    _parts(rel)
    try:
        with _walk(ws, rel[:-1]) as directory:
            try:
                os.rmdir(
                    rel[-1] if _FD else directory.path / rel[-1], **({"dir_fd": directory.fd} if _FD else {})
                )
            except OSError as error:
                if error.errno in (errno.ENOTEMPTY, errno.EEXIST, errno.ENOENT):
                    return False
                raise
            return True
    except RecordUnavailable as error:
        if error.reason != "missing":
            raise
        return False


def _try_lock(fd):
    with _io():
        try:
            if _FCNTL is not None:
                _FCNTL.flock(fd, _FCNTL.LOCK_EX | _FCNTL.LOCK_NB)
            elif _MSVCRT is not None:
                os.lseek(fd, 0, os.SEEK_SET)
                _MSVCRT.locking(fd, _MSVCRT.LK_NBLCK, 1)
            return True
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return False
            if error.errno in (errno.EOPNOTSUPP, errno.ENOTSUP, errno.ENOLCK):
                return None  # This lock uses mtime and identity instead.
            raise


def _lock_check(ws, rel, fd, *, fallback=False):
    with _io("lock"), _walk(ws, rel[:-1]) as directory:
        current = os.stat(
            rel[-1] if _FD else directory.path / rel[-1],
            follow_symlinks=False,
            **({"dir_fd": directory.fd} if _FD else {}),
        )
        before = os.fstat(fd)
        if (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise RecordTampered("swapped")
        if fallback or (_FCNTL is None and _MSVCRT is None):
            os.utime(fd)


def _release_lock(ws, rel, fd, *, _directory=None):
    try:
        before = os.fstat(fd)
        if os.name == "nt":
            # Windows handles lack FILE_SHARE_DELETE: capture identity, then close.
            _close(fd)
            fd = None
        walk = nullcontext(_directory) if _directory is not None else _walk(ws, rel[:-1])
        with _io("lock"), walk as directory:
            name = rel[-1] if _FD else directory.path / rel[-1]
            kw = {"dir_fd": directory.fd} if _FD else {}
            try:
                current = os.stat(name, follow_symlinks=False, **kw)
                if (current.st_dev, current.st_ino) == (before.st_dev, before.st_ino):
                    os.unlink(name, **kw)
            except FileNotFoundError:
                pass
    finally:
        if fd is not None:
            _close(fd)


@contextmanager
def _lock(ws, run, wait=None):
    rel = ("runs", f"{run}.lock")
    deadline = time.monotonic() + (_LOCK_WAIT if wait is None else wait)
    while True:
        fd = _open(ws, rel, "create_excl", create_dirs=True)
        if fd is not None:
            try:
                locked = _try_lock(fd)
                if locked is not False:
                    try:
                        _lock_check(ws, rel, fd, fallback=locked is None)
                    except RecordTampered as error:
                        if error.reason != "swapped":
                            raise
                    else:
                        yield lambda fd=fd, locked=locked: _lock_check(ws, rel, fd, fallback=locked is None)
                        return
            finally:
                _release_lock(ws, rel, fd)
        else:
            try:
                old = _open(ws, rel, "lock")
            except RecordUnavailable as error:
                if error.reason == "missing":
                    continue
                raise
            try:
                with _io():
                    stale = time.time() - os.fstat(old).st_mtime > 30
                # A live kernel lock wins over age. Keep it until unlink completes.
                if stale and _try_lock(old) is not False:
                    closing, old = old, None
                    _release_lock(ws, rel, closing)
            finally:
                if old is not None:
                    _close(old)
        if time.monotonic() >= deadline:
            raise RecordBusy("The record is busy.")
        time.sleep(0.005)


# Record logic: only calls the I/O core above.
def _json(obj):
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _hidden_line(hider, obj) -> bytes:
    """The compact JSON of `obj`, refused when a form of a hidden value is in the serialized text or in any
    decoded string or key (a reader json-decodes, so escaped bytes alone prove nothing)."""
    line = _json(obj)
    if hider.hide_text(line) != line or hider.leaks(obj):
        raise RecordInvalid("This record cannot be hidden safely.")
    return line.encode("utf-8")


def problem_message(reason):
    """The plain words for a read problem (one place for every screen)."""
    return _MESSAGES[reason]


def alert_content(workspace, run):
    """Leave one integrity alert for a run file whose content disagrees with what the writer guarantees."""
    return _alert(workspace, target="run", run=run, reason="content", seen_by="writer")


def _validate(event, *, detail=False):
    if not (_DETAIL_VALIDATOR if detail else _VALIDATOR).is_valid(event):
        raise RecordInvalid()


def _generic(obj):
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, list):
        return [_generic(x) for x in obj]
    if isinstance(obj, dict):
        return {redact(k): _generic(v) for k, v in obj.items()}
    return obj


def _key(event):
    via = event["via"]
    return (
        event["run"],
        event["id"],
        event["kind"],
        event["outcome"] is not None,
        "hl" if via in ("hook", "log") else via,
    )


def _provisional(event):
    """A hook's finished line that does not know how the call ended (`ok: null`; the hook entry writes every
    finished step this way unless it claims a failure, hook_outcome)."""
    return event["via"] == "hook" and event["outcome"] is not None and event["outcome"]["ok"] is None


def _agree(old, event):
    """The hook line `old` of a call says what the log line `event` of that call says: what was used, the
    text, the files, and (when both are finished and the hook's is not provisional) `ok` and `error`; a hook's
    fixed failure code (HOOK_ERRORS) is never the log's text, so against it only `ok` counts."""
    if any(old.get(k) != event.get(k) for k in ("used", "text")) or (old.get("files") or []) != (
        event.get("files") or []
    ):
        return False
    if old["outcome"] is None or event["outcome"] is None or _provisional(old):
        return True
    keys = ("ok",) if old["outcome"]["error"] in HOOK_ERRORS else ("ok", "error")
    return all(old["outcome"][k] == event["outcome"][k] for k in keys)


def _replaces(old, event):
    """`event` (a log line) replaces `old` (the hook line of the same key) in the reader's view."""
    return event["via"] == "log" and old["via"] == "hook" and _key(old) == _key(event) and _agree(old, event)


def _same_call(old, event):
    """Lines of one call (run, id, kind), started or finished."""
    return all(old[k] == event[k] for k in ("run", "id", "kind"))


def _decision(previous, event):
    """Keep `event`? Hook lines come from inside the agent's trust boundary, so for one key (started or
    finished alike) the log line wins: it replaces the hook line, and a hook line after any log line of that
    call (started or finished) is dropped. When a log line disagrees with any hook line of its call (a hook
    end against the log's started line too), both are kept and the log line carries `conflict: true` (the
    log line is the one to believe). Repeats of one origin keep the first."""
    matching = [old for old in previous if _key(old) == _key(event)]
    if any(old["via"] == event["via"] for old in matching):
        return False
    call = [old for old in previous if old["via"] in ("hook", "log") and _same_call(old, event)]
    if event["via"] == "hook" and any(old["via"] == "log" for old in call):
        return False  # the log already has this call
    if event["via"] == "log" and any(old["via"] == "hook" and not _agree(old, event) for old in call):
        event["conflict"] = True
    return True


def _shown(events):
    """The lines a reader keeps, in file order."""
    kept = []
    for event in events:
        if _decision(kept, event):
            kept = [old for old in kept if not _replaces(old, event)] + [event]
    return kept


def _dedupe(events, run):
    # copies: `_decision` marks `conflict` on the event it is given, and verified events are cached
    return sorted(_shown([dict(e) for e in events if e["run"] == run]), key=lambda e: e["seq"])


def _legacy_parse(raw, run):
    """The lines of a run made before orch sealed lines, as the old reader took them (schema check, the run,
    seq == the physical line number): (events, skipped). They are never trusted: the caller marks them."""
    events, skipped = [], 0
    for lineno, line in enumerate(raw.splitlines(), 1):
        try:
            event = json.loads(line)
            _validate(event)
            if event["run"] != run or event["seq"] != lineno or isinstance(event["seq"], bool):
                raise RecordInvalid()
            events.append(event)
        except (ValueError, TypeError, UnicodeError, RecursionError, RecordInvalid):
            skipped += 1
    return events, skipped


# Per process: the walk over the verified prefix of a run file, so a re-read (tail --follow, the collector,
# query paging) verifies only what was appended. Keyed by workspace and run; valid only while the first
# `offset` bytes still hash the same and the key id is the same.
_VERIFIED: dict = {}
_VERIFIED_MAX = 64


def _chain(workspace, run, raw, rec, head, head_present):
    """(Verified, mode, legacy prefix bytes) of a run file's bytes: the one place that decides which lines
    count (record_auth.verify_run's walk, resumed from the cache). `head` is the checked chain head or None;
    `head_present`: a head file exists (even a damaged one), so the run is never a legacy run. When the head
    records a legacy prefix that the file still starts with exactly, those bytes are returned (not walked) and
    the chain numbering begins after them."""
    ws_id, kid, rk = rec
    mode, sealed, _ = record_auth.legacy_split(raw, head_present)
    if mode == "legacy":
        return record_auth.Verified(), mode, b""
    if head is not None and head.get("pruned"):
        head = None
    pre, lines = record_auth.legacy_prefix(sealed, head)
    sealed = sealed[len(pre) :]
    cut = sealed.rfind(b"\n") + 1
    whole, torn = sealed[:cut], sealed[cut:]
    key = (str(workspace), run)
    digest = hashlib.sha256(whole).digest()
    hit = _VERIFIED.get(key)
    state, done = None, 0
    if hit is not None and hit[0] == (kid, lines) and len(whole) >= hit[1]:
        if hashlib.sha256(whole[: hit[1]]).digest() == hit[2]:
            state, done = hit[3].copy(), hit[1]
    if state is None:
        state = record_auth.start_state(lines)
    record_auth.scan(state, whole[done:], run, ws_id, rk, kid)
    if len(_VERIFIED) >= _VERIFIED_MAX:
        _VERIFIED.clear()
    _VERIFIED[key] = ((kid, lines), len(whole), digest, state.copy())
    if torn:  # a cut-off last line (a crash): never cached, counted as changed
        record_auth.scan(state, torn, run, ws_id, rk, kid)
    return record_auth.finish(state, kid, head), mode, pre


@dataclass
class _View:
    events: list
    changed: int = 0
    removed: int = 0
    reason: str | None = None
    legacy: bool = False
    unchecked: int = 0
    last_seq: int = 0
    last_mac: str | None = None
    before: tuple = ()  # lines made before protection, recorded in the head
    rejected: int = 0  # spool entries refused for this run (head.rejected, or the counter of a headless run)


def _legacy_parse_prefix(pre, run):
    """The legacy prefix the head recorded, as lines to show (not checked, before protection)."""
    if not pre:
        return [], 0
    events, skipped = _legacy_parse(pre, run)
    return [dict(e, before_protection=True) for e in events], skipped


def _verified(workspace, run, raw) -> _View:
    """The one read path of a run file (A1): what counts, what was changed outside orch, what is gone.
    Raises RecordTampered("unverified") whenever the run may have a chain that cannot be checked: sealed
    lines or a head and no key, or ANY unknown state of the guarded home (a damaged local id, a key folder
    that cannot be read): never a legacy read then. Only a run with no sealed line and a head file that is
    truly absent, in a guarded home that resolves cleanly, is a legacy run (UNCHECKED_TEXT): shown, never
    counted as checked."""
    state = humanproof.record_head_state(workspace, run)
    if state == "unknown":
        raise RecordTampered("unverified")
    rec = humanproof.record_key(workspace)
    # a run whose unsigned lines may be shown as "not checked": it existed when protection began (the cutover
    # list), or no list was made yet. Any other run that has no sealed line and no head holds planted lines.
    cutover = humanproof.record_cutover_read(workspace)
    legacy_ok = cutover is None or (cutover is not False and run in cutover)
    present = state == "present" or not legacy_ok
    if rec is None:
        mode, _sealed, _prefix = record_auth.legacy_split(raw, present)
        if mode != "legacy":
            raise RecordTampered("unverified")  # sealed lines or a head, and no key: fail closed
        return _legacy_view(raw, run)
    # (a run with no key returns above; below the counters can be read)
    head, _ = humanproof.record_head_read(workspace, run) if state == "present" else (None, True)
    verified, mode, pre = _chain(workspace, run, raw, rec, head, present)
    if mode == "legacy":
        view = _legacy_view(raw, run)
        view.rejected = humanproof.record_rejects_read(workspace, run)
        view.changed += view.rejected
        return view
    old, _skipped = _legacy_parse_prefix(pre, run)
    gone = 0
    if (head or {}).get("legacy_lines") and not pre:
        first = next((x for x in raw.split(b"\n") if x), b"")
        if (
            record_auth.split(first) is not None
        ):  # the file now starts with a sealed line: the old ones are gone
            gone = head["legacy_lines"]
    # two counters, never folded or deleted (so nothing can be lost or counted twice): the head's, and the
    # guarded one a run keeps from before its first head
    rejected = int((head or {}).get("rejected") or 0) + humanproof.record_rejects_read(workspace, run)
    if not verified.events and not old and (verified.changed or verified.removed):
        raise RecordTampered(verified.reason)
    return _View(
        verified.events,
        verified.changed + rejected,  # a refused spool entry is a change outside orch, though it is gone
        verified.removed + gone,
        verified.reason
        or ("content" if rejected else None)
        or ("removed" if gone else None)
        or ("unchecked" if old else None),
        unchecked=len(old),
        last_seq=verified.last_seq,
        last_mac=verified.last_mac,
        before=tuple(old),
        rejected=rejected,
    )


def _legacy_view(raw, run):
    events, skipped = _legacy_parse(raw, run)
    return _View(
        [dict(e, before_protection=True) for e in events],  # every line of a legacy run is tagged: one rule
        changed=0,  # unreadable lines of a legacy run are part of "not checked", not a change
        reason="unchecked" if events or skipped else None,
        legacy=True,
        unchecked=len(events) + skipped,
    )


_SPOOL_MAX_BYTES = 3 * 1024**2  # one line (8 KB), its detail (1 MB) and the escaping of both
_SPOOL_NAME = re.compile(r"\d{20}_[0-9a-f]{32}\.json")
_ALERTED = set()


def _alert(ws, *, target, run, reason, seen_by):
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    alert = dict(
        v=1,
        schema="orch.record-alert/1",
        at=now,
        target=target,
        run=run,
        reason=reason,
        seen_by=seen_by,
        message=_MESSAGES["tampered"],
    )
    key = (str(ws), now[:10], target, run, reason)
    if key not in _ALERTED:
        _ALERTED.add(key)
        try:
            fd = _open(ws, ("alerts", now[:10] + ".jsonl"), "append", create_dirs=True)
            try:
                _write(fd, (_json(alert) + "\n").encode())
            finally:
                _close(fd)
        except (RecordTampered, RecordUnavailable):
            pass  # the returned alert still reaches the caller; never recurse
    return alert


LOST_REASONS = (
    "hider_off",
    "invalid",
    "too_large",
    "other_run",
    "job_activity",
    "collector_error",  # the wrapper's collector failed on a turn (the run goes on; `error` names the type)
    "hooks_off",  # the agent's folder settings switch the tool's hooks off (agent-writable)
    "hooks_missing",  # a turn's log shows tool calls but no hook line of them reached the record
)  # after the caller is proven to be in the run
UNPROVEN_REASONS = ("not_active", "other_run", "not_provable")  # before it is: never under a run id
_LOST_RUN_LINES = 50  # per run and day; the next one is a "trimmed" marker, then nothing
_LOST_FILE_BYTES = 1024**2  # per file; over it only a global "trimmed" marker is written


def _note(ws, name, run, reason, now, run_lines, error=None):
    now = datetime.now(UTC) if now is None else now
    stamp = now.isoformat().replace("+00:00", "Z")
    try:
        fd = _open(ws, ("alerts", f"{name}-{stamp[:10]}.jsonl"), "read_append", create_dirs=True)
        try:
            raw = _read_bytes(fd)
            rows = []
            for line in raw.splitlines():
                try:
                    rows.append(json.loads(line))
                except (ValueError, TypeError):
                    continue
            rows = [r for r in rows if isinstance(r, dict)]
            if len(raw) > _LOST_FILE_BYTES:
                if not any(r.get("run") is None and r.get("reason") == "trimmed" for r in rows):
                    write = dict(run=None, reason="trimmed")
                else:
                    return
            else:
                mine = [r for r in rows if r.get("run") == run]
                for old in mine[-200:]:
                    try:
                        if old["reason"] == reason and (
                            timedelta(0) <= now - datetime.fromisoformat(old["at"]) < timedelta(minutes=1)
                        ):
                            return
                    except (ValueError, KeyError, TypeError):
                        continue
                if run_lines and len(mine) >= run_lines:
                    if any(r.get("reason") == "trimmed" for r in mine):
                        return
                    write = dict(run=run, reason="trimmed")  # loud, never a silent stop (invariant I3)
                else:
                    write = dict(run=run, reason=reason, **({"error": error} if error else {}))
            note = dict(v=1, schema="orch.record-lost/1", at=stamp, **write)
            _write(fd, (_json(note) + "\n").encode())
        finally:
            _close(fd)
    except (RecordTampered, RecordUnavailable):
        pass  # a trace that cannot be stored is not worth failing the hook


def note_lost(ws, run, reason, *, now=None, error=None):
    """A hook entry of a PROVEN caller (live claim, inside its process tree) that could not be written leaves
    one short trace (orch.record-lost/1, no content): alerts/hook-lost-<day>.jsonl, at most one per run and
    reason per minute, at most 50 lines per run, then one "trimmed" line. `error`: an exception's type name
    (collector_error), kept only when it is a plain identifier; never its message. Never raises."""
    if reason in LOST_REASONS and isinstance(run, str) and re.fullmatch(_RUN, run):
        if not (isinstance(error, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", error)):
            error = None
        _note(ws, "hook-lost", run, reason, now, _LOST_RUN_LINES, error)


def note_unattributed(ws, reason, *, now=None):
    """A hook entry whose caller could not be proven to be in the run: nothing under any run id (the claimed
    run is the caller's word), only the reason, in alerts/hook-lost-unattributed-<day>.jsonl, 1 per minute."""
    if reason in UNPROVEN_REASONS:
        _note(ws, "hook-lost-unattributed", None, reason, now, 0)


_JOB = r"j_[a-z0-9]{6,32}"
JOB_BYTES = 5 * 1024**2  # stored stream of one job (job-events.md caps)
JOB_RUN_BYTES = 50 * 1024**2  # all job streams of one run
JOB_REPLACE_BYTES = 64 * 1024  # a same-second progress line is replaced (file rewritten) only below this size


def _job_events(raw, run, job, valid):
    """The lines of one job stream. Strict: a line that is not a valid event of this job and run, in order,
    means the file was changed outside orch (tampered), never quietly skipped or trusted."""
    if raw and not raw.endswith(b"\n"):
        raise RecordUnavailable("torn")
    events = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
            ok = (event["run"], event["job"], event["seq"]) == (run, job, len(events) + 1) and valid(event)
        except (ValueError, RecursionError, KeyError, TypeError):
            ok = False
        if not ok:
            raise RecordTampered("content")
        events.append(event)
    return events


def read_job(workspace, run, job, *, valid, seen_by="reader") -> ReadResult[list[dict]]:
    """One job stream (jobs/<run>/<job>.jsonl), explicit status as read_run. `valid(event)` is the caller's
    schema check of a stored line."""
    _name(run, _RUN)
    _name(job, _JOB)
    try:
        fd = _open(workspace, ("jobs", run, job + ".jsonl"), "read")
        try:
            return ReadResult("ok", _job_events(_read_bytes(fd), run, job, valid))
        finally:
            _close(fd)
    except (RecordTampered, RecordUnavailable) as error:
        return _report(workspace, error, "folder", run, seen_by)


def list_jobs(workspace, run=None, *, seen_by="reader") -> ReadResult[list[tuple[str, str]]]:
    """(run, job) pairs that have a stream, for one run or for all runs."""
    try:
        runs = (
            [_name(run, _RUN)]
            if run
            else [n for n in _entries(workspace, ("jobs",)) if re.fullmatch(_RUN, n)]
        )
        found = []
        for name in sorted(runs):
            try:
                names = _entries(workspace, ("jobs", name))
            except RecordUnavailable as error:
                if error.reason == "missing":
                    continue
                raise
            found += [(name, n[:-6]) for n in sorted(names) if re.fullmatch(_JOB + r"\.jsonl", n)]
        return ReadResult("ok", found)
    except RecordUnavailable as error:
        if error.reason == "missing":
            return ReadResult("ok", [])
        return _report(workspace, error, "folder", run, seen_by)
    except RecordTampered as error:
        return _report(workspace, error, "folder", run, seen_by)


def append_job(workspace, run, job, decide, *, valid, hider, max_jobs=None):
    """Append one line to a job stream under the run's lock (one writer per job). `decide(events, size)` runs
    inside the lock on the strictly read stream and returns (line_dict | None, replace_last, result); the line
    is stored only after the caller's own checks passed (every string already hidden). A cut-off last line (a
    crash) is dropped under the lock. Caps are checked here, under the lock: the stream, the run's streams,
    and (at the first line) the number of jobs of the run. `hider` is required: the line passes the same
    fail-closed backstop as a run line (RecordInvalid when a form of a hidden value is still in it). Returns
    result."""
    _name(run, _RUN)
    _name(job, _JOB)
    try:
        hiding._check(hider)
    except (ValueError, TypeError):
        raise RecordOff(_OFF) from None
    rel = ("jobs", run, job + ".jsonl")
    try:
        with _lock(workspace, run) as check_lock:
            check_lock()
            fd = _open(workspace, rel, "read_append", create_dirs=True)
            stored, raw = False, None
            try:
                check_lock()
                raw = _read_bytes(fd)
                if raw and not raw.endswith(b"\n"):
                    raw = raw[: raw.rfind(b"\n") + 1]
                    _write_new(workspace, rel, raw, expected=fd)
                    old, fd = fd, _open(workspace, rel, "read_append")
                    _close(old)
                    if _read_bytes(fd) != raw:  # the repaired file must be exactly what we wrote
                        raise RecordTampered("swapped")
                events = _job_events(raw, run, job, valid)
                if (
                    not events
                    and max_jobs is not None
                    and len(
                        [n for n in _entries(workspace, ("jobs", run)) if re.fullmatch(_JOB + r"\.jsonl", n)]
                    )
                    > max_jobs
                ):
                    raise RecordFull("This run has reached its limit of jobs.")
                event, replace_last, result = decide(events, len(raw))
                if event is None:
                    return result
                try:
                    data = _hidden_line(hider, event) + b"\n"
                except (ValueError, TypeError, RecursionError, UnicodeError):
                    raise RecordInvalid() from None
                if len(data) > 16384:
                    raise RecordInvalid("The job entry is too large.")
                if len(raw) + len(data) > JOB_BYTES or (
                    # the final `end` is always accepted (200 jobs x 16 KB at most)
                    event["type"] != "end" and _size(workspace, ("jobs", run)) + len(data) > JOB_RUN_BYTES
                ):
                    raise RecordFull("This job has reached its limit of entries.")
                check_lock()
                if replace_last and len(raw) <= JOB_REPLACE_BYTES:
                    rows = raw.splitlines(keepends=True)[:-1]
                    _write_new(workspace, rel, b"".join(rows) + data, expected=fd)
                else:
                    _write(fd, data)
                stored = True
                return result
            finally:
                if not stored and raw == b"":  # a refused first line leaves no empty file behind
                    _unlink(workspace, rel, expected=fd)
                _close(fd)
    except RecordBusy:
        raise
    except (RecordTampered, RecordUnavailable) as error:
        _report(workspace, error, "folder", run, "writer")
        raise


def _report(ws, error, target, run, seen_by):
    return ReadResult.from_error(error, ws, getattr(error, "target", target), run, seen_by)


def _pending_count(workspace, run):
    try:
        with _io("folder"):
            return len([n for n in _entries(workspace, ("pending", run)) if _SPOOL_NAME.fullmatch(n)])
    except RecordUnavailable as error:
        if error.reason == "missing":
            return 0
        raise


def _pending_preflight(workspace, run):
    """Retention's look at pending/<run>/ before it deletes anything: a flat listing only, never a size or a
    walk of what is inside (a planted tree must not be able to stop it or exhaust it)."""
    return _pending_count(workspace, run)


def run_lines(workspace, run, *, lock_wait=None, drain=None, only=None) -> list[dict]:
    """The run's VERIFIED lines AS WRITTEN (no dedupe, no reader view), read under the run lock: for a
    writer-side caller that must see every line (a collector numbering its id-less lines `<run>:<n>` past
    every seq and every such id already used). Lines that are not genuine are not in it (A1); a changed or
    removed line leaves one integrity alert. `drain`: a writer's drain (RecordWriter.drain); the spooled
    lines of the run (pending/<run>/) are committed first, under the same lock, so their ids are seen too. No
    run file yet: []. A legacy run (made before orch checked it): [], its lines are not verified. `only` is
    kept for callers; every verified line is returned. Raises RecordBusy, RecordTampered (its alert is
    left) or RecordUnavailable."""
    _name(run, _RUN)
    try:
        with _lock(workspace, run, lock_wait) as check_lock:
            check_lock()
            if drain is not None:
                drain(run, check_lock=check_lock)
                check_lock()
            try:
                fd = _open(workspace, ("runs", run + ".jsonl"), "read")
            except RecordUnavailable as error:
                if error.reason == "missing":
                    return []
                raise
            try:
                _check_fd(fd)
                view = _verified(workspace, run, _read_bytes(fd))
            finally:
                _close(fd)
            if (view.changed or view.removed) and not view.legacy:
                alert_content(workspace, run)
            return [] if view.legacy else [dict(e) for e in view.events]
    except (RecordTampered, RecordUnavailable) as error:
        _report(workspace, error, "run", run, "writer")
        raise


def _removed_run(workspace, run):
    """(0, None) or (n, head) when the run file is gone but its chain head says it had n lines (not pruned).
    An unknown state of the guarded home raises RecordTampered("unverified"): a missing file is not "gone
    for good" when its head cannot be looked up."""
    state = humanproof.record_head_state(workspace, run)
    if state == "unknown":
        raise RecordTampered("unverified")
    if state == "absent":
        return 0, None
    head, _ = humanproof.record_head_read(workspace, run)
    if head is None or head.get("pruned") or not head["seq"]:
        return 0, None
    return head["seq"], head


def read_run(workspace, run, *, seen_by="reader") -> RunRead:
    _name(run, _RUN)
    pending = 0
    try:
        pending = _pending_count(workspace, run)
        fd = _open(workspace, ("runs", run + ".jsonl"), "read")
        try:
            view = _verified(workspace, run, _read_bytes(fd))
        finally:
            _close(fd)
        pending = max(pending, _pending_count(workspace, run))
        reason = view.reason or ("pending" if pending else None)
        return ReadResult(
            "ok",
            [*view.before, *_dedupe(view.events, run)],
            changed=view.changed,
            removed=view.removed,
            unchecked=view.unchecked,
            legacy=view.legacy,
            pending=pending,
            reason=reason,
            message=_MESSAGES[reason] if reason else None,
        )
    except (RecordTampered, RecordUnavailable) as error:
        if isinstance(error, RecordUnavailable) and error.reason == "missing":
            try:
                gone, _head = _removed_run(workspace, run)
            except RecordTampered as unknown:  # the guarded home cannot be looked at: fail closed
                return _report(workspace, unknown, "run", run, seen_by)
            if gone:  # the file is gone but orch wrote lines to it (not pruned): removed outside orch
                return _report(workspace, RecordTampered("removed"), "run", run, seen_by)
            rejected = humanproof.record_rejects_read(workspace, run)
            if rejected:  # a planted spool entry was refused for a run that has no file and no head
                return ReadResult(
                    "ok",
                    [],
                    changed=rejected,
                    reason="content",
                    message=_MESSAGES["content"],
                    pending=pending,
                )
            if pending:
                return ReadResult("ok", [], reason="pending", message=_MESSAGES["pending"], pending=pending)
        return _report(workspace, error, "run", run, seen_by)


def _read_json(ws, rel):
    return _json_of(_read_file(ws, rel))


def _read_file(ws, rel):
    fd = _open(ws, rel, "read")
    try:
        return _read_bytes(fd)
    finally:
        _close(fd)


def _json_of(raw):
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise RecordTampered("swapped") from None


def read_detail(workspace, run, file_id, *, line_id, ticket=None):
    """The detail file `file_id` of `run`, as presented by the VERIFIED line `line_id` that points at it. The
    hash that file must have is taken from that line here (inside its MAC), never from the caller; a run
    made before orch checked it (legacy) has none and is read as before. A sealed line with a detail pointer
    but no `detail_hash`, a file with other bytes, or no verified line of the run naming this file is
    refused as swapped ("Details changed outside orch."). The name must also be the one made from the
    payload's own (run, kind, id, ticket), and `ticket` the ticket of the line that points at the file."""
    _name(run, _RUN)
    _name(file_id, _FILE)
    try:
        view = read_run(workspace, run, seen_by="reader")
        if view.status != "ok":
            return view
        point = f"detail/{run}/{file_id}.json"
        lines = [e for e in view.value if e.get("id") == line_id and e.get("detail") == point]
        if not lines:
            raise RecordTampered("swapped", _MESSAGES["swapped_detail"])
        unchecked = not is_sealed(lines[-1])
        want = None
        if not unchecked:
            want = lines[-1].get("detail_hash")
            if not isinstance(want, str):
                raise RecordTampered("swapped", _MESSAGES["swapped_detail"])
        raw = _read_file(workspace, ("detail", run, file_id + ".json"))
        if want is not None and record_auth.detail_hash(raw) != want:
            raise RecordTampered("swapped", _MESSAGES["swapped_detail"])
        value = _json_of(raw)
        if (
            not _DETAIL_VALIDATOR.is_valid(value)
            or value["run"] != run
            or detail_name(run, value["kind"], value["id"], value["ticket"]) != file_id
            or (ticket is not None and value["ticket"] != ticket)
        ):
            raise RecordTampered("swapped")
        if unchecked:  # made before orch checked it: shown, never as verified
            return ReadResult("ok", value, reason="unchecked", message=UNCHECKED_TEXT, unchecked=1)
        return ReadResult("ok", value)
    except (RecordTampered, RecordUnavailable) as error:
        return _report(workspace, error, "detail", run, "reader")


def read_meta(workspace):
    try:
        value = _read_json(workspace, ("meta.json",))
        if not _META_VALIDATOR.is_valid(value):
            raise RecordTampered("swapped")
        return ReadResult("ok", value)
    except (RecordTampered, RecordUnavailable) as error:
        return _report(workspace, error, "meta", None, "reader")


def list_runs(workspace):
    """Every run orch knows: the run files AND the runs that have a chain head (not pruned) but no file, so a
    deleted run file (or runs/ folder) cannot hide a run: reading such a run says `removed`."""
    files, problem = [], None
    try:
        names = _entries(workspace, ("runs",))
        files = [n[:-6] for n in names if re.fullmatch(_RUN + r"\.jsonl", n)]
    except (RecordTampered, RecordUnavailable) as error:
        problem = _report(workspace, error, "folder", None, "reader")
    gone = []
    for name in humanproof.record_head_names(workspace):
        if name not in files:
            head, _ = humanproof.record_head_read(workspace, name)
            if head is not None and head["seq"] and not head.get("pruned"):
                gone.append(name)
    if problem is not None and not (problem.status == "unavailable" and problem.reason == "missing"):
        return problem
    if not files and not gone and not humanproof.record_reject_names(workspace) and problem is not None:
        return problem
    for name in humanproof.record_reject_names(workspace):
        if name not in files and name not in gone:
            gone.append(name)
    return ReadResult("ok", sorted([*files, *gone]))


@dataclass(frozen=True)
class _Detail:
    created: bool = False
    reason: str | None = None
    alert: dict | None = None
    hash: str | None = None  # detail_hash of the bytes on disk (inside the line's MAC)


def _store_detail(ws, event, payload, previous):
    """Store the detail file of `event` and return the hash of the bytes that are on disk. An existing file
    at the name is kept only when a VERIFIED previous line of the run carries its hash (activity.md, Detail
    files): anything else is an orphan or planted and is replaced atomically."""
    rel = tuple(event["detail"].split("/"))
    exists = False
    try:
        try:
            current = _read_file(ws, rel)
            exists = True
        except RecordUnavailable as error:
            if error.reason != "missing":
                raise
        if exists:
            digest = record_auth.detail_hash(current)
            same = [
                old
                for old in previous
                if old.get("detail") == event["detail"]
                and old.get("detail_hash") == digest
                # the detail name derives from these four
                and all(old.get(k) == event[k] for k in ("run", "kind", "id", "ticket"))
            ]
            finished = any(
                old.get("outcome") is not None and not (old.get("via") == "hook" and event["via"] == "log")
                for old in same
            )  # a log line writes its own detail over a hook line's (the log wins, Precedence and dedupe)
            if finished or (same and event["outcome"] is None):
                return _Detail(hash=digest)
        _write_new(ws, rel, payload)
        return _Detail(created=not exists, hash=record_auth.detail_hash(payload))
    except (RecordTampered, RecordUnavailable) as error:
        result = _report(ws, error, "detail", event["run"], "writer")
        return _Detail(reason=error.reason, alert=result.alert)


class RecordWriter:
    def __init__(self, workspace: Path, *, hider: Hider):
        try:
            hiding._check(hider)
        except (ValueError, TypeError):
            raise RecordOff(_OFF) from None
        self.workspace, self.hider = Path(workspace), hider

    def _serialized(self, obj):
        return _hidden_line(self.hider, obj)

    def _prepare_detail(self, event, detail, hidden=0):
        if detail is None or not event.get("ticket"):
            return None  # an event with no ticket gets no detail file (not detail_lost: activity.md, I4)
        try:
            before = _json(detail).count("[hidden: ")
            payload = self.hider.hide_json(detail)
            wrapped = dict(
                v=1,
                id=event["id"],
                run=event["run"],
                kind=event["kind"],
                ticket=event["ticket"],
                input=payload["input"],
                output=payload["output"],
                truncated=False,
                hidden=hidden + max(0, _json(payload).count("[hidden: ") - before),
            )
            data = self._serialized(wrapped)
            if len(data) > 1024**2:
                event["detail_lost"] = True
                return None
            _validate(wrapped, detail=True)
            return data
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            event["detail_lost"] = True
            return None

    def append(self, event, *, detail=None, lock_wait=None):
        """lock_wait: seconds to wait for the run lock before the write is spooled (default 30)."""
        try:
            return self._append(event, detail, lock_wait)
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            raise RecordInvalid() from None

    def _append(self, event, detail, lock_wait=None):
        if not isinstance(event, dict):
            raise RecordInvalid()
        run = _name(event.get("run"), _RUN)
        if humanproof.record_key(self.workspace) is None:
            raise RecordOff(_OFF_KEY)  # no key, no recording: fail closed, nothing written (not even a spool)
        event = dict(event, seq=1, v=1)
        default_id = event.get("id") is None
        eid = event.get("id") if not default_id else f"{run}:1"
        if not isinstance(eid, str):
            raise RecordInvalid()
        eid = self.hider.hide_text(eid)
        if not default_id:
            if event.get("via") == "hook" and re.fullmatch(r"(?:h_)?" + _RUN + r":.*", eid):
                eid = "x_" + hashlib.sha256(b"orch.id.hook/1\0" + eid.encode()).hexdigest()[:32]
            elif (
                not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", eid)
                or re.fullmatch(r"x_[0-9a-f]{32}", eid)
                or re.fullmatch(r"h_" + _RUN + r":.*", eid)  # the hook's own default namespace: never sent
            ):
                eid = _hash(eid)
        event["id"] = eid
        if not isinstance(event.get("text"), str) or re.search(r"[\x00-\x1f\x7f]", event["text"]):
            raise RecordInvalid()
        if event.get("detail") is not None:
            _name(event["detail"], rf"detail/{_RUN}/{_FILE}\.json")
        if detail is not None and event.get("kind") in ("key.use", "session.input"):
            raise RecordInvalid()
        event.pop("detail_lost", None)
        event.pop("conflict", None)
        event["detail"] = None
        # files (activity.md, Files): only on a step; a bad entry is dropped, never the line.
        files = event.pop("files", None)
        if event.get("kind") != "step" or type(files) is not list:
            files = None
        else:
            files = files[:MAX_INPUT]  # only the first 64 are looked at; the first 8 good ones are kept
        before = _json(event).count("[hidden: ")
        event = self.hider.hide_json(event)
        hidden = max(0, _json(event).count("[hidden: ") - before)
        if files is not None:
            # One shape check (record_files.file_ok, NFC included); a path that changes under the hider or the
            # plain-text cleaner is dropped, never stored hidden.
            good = [f for f in files if file_ok(f) and self.hider.hide_text(f) == f and redact(f) == f]
            event["files"] = _files_in_budget(good[:_MAX_FILES])
        event["text"] = self.hider.hide_cut(" ".join(redact(event["text"]).split()), 500)
        if isinstance(event.get("outcome"), dict) and isinstance(event["outcome"].get("error"), str):
            event["outcome"]["error"] = self.hider.hide_cut(
                " ".join(redact(event["outcome"]["error"]).split()), 300
            )
        if "data" in event:
            event["data"] = _generic(event["data"])
            if len(_json(event["data"]).encode()) > 7000:
                event["data"] = {"cut": True}
        _validate(event)
        payload = self._prepare_detail(event, detail, hidden)
        # Both possible line forms have passed the hider before taking the lock. The audit line is never
        # dropped for its optional parts (I4): a line that is too large loses `files`, then `data` (cut).
        for trim in (None, "files", "data"):
            if trim == "files":
                event.pop("files", None)
            elif trim == "data" and "data" in event:
                event["data"] = {"cut": True}
            prepared = dict(event, seq=10**20, conflict=True)
            if payload is not None:
                prepared["detail"] = (
                    f"detail/{run}/{detail_name(run, event['kind'], event['id'], event['ticket'])}.json"
                )
                prepared["detail_hash"] = "0" * 32
            try:
                self._line(prepared)
                self._line(dict(prepared, detail=None, detail_lost=True))
                break
            except RecordInvalid:
                if trim == "data":
                    raise
        self._serialized(dict(schema="orch.record/1", since=event["at"], keep_days=90, max_mb=2048))
        try:
            with _lock(self.workspace, run, lock_wait) as check_lock:
                check_lock()
                self._drain(run, check_lock=check_lock)
                check_lock()
                return self._commit(event, payload, default_id, check_lock=check_lock)
        except RecordBusy:
            return self._spool(event, payload, default_id)
        except (RecordTampered, RecordUnavailable) as error:
            _report(self.workspace, error, "run", run, "writer")
            raise

    def _line(self, event):
        line = self._serialized(event) + b"\n"
        # the sealed line is the body with `}` replaced by the 125-byte auth suffix (record_auth.SUFFIX_LEN)
        if len(line) + record_auth.SUFFIX_LEN - 1 > 8192:
            raise RecordInvalid("The record entry is too large.")
        return line

    def _commit(self, event, payload, default_id, *, check_lock=lambda: None, drained=None):
        """The only place a run line is sealed (activity.md, Authenticated record). Under the run lock: the
        next seq and link come from the last VERIFIED line of the current key (the chain head only when the
        file was cut short), the line is sealed and written, then the head."""
        run = event["run"]
        rec = humanproof.record_key(self.workspace)
        if rec is None:
            raise RecordOff(_OFF_KEY)
        ws_id, kid, rk = rec
        # once, BEFORE this run's file is made: which runs existed (unsigned) when protection began
        humanproof.record_cutover_ensure(self.workspace)
        fd = _open(self.workspace, ("runs", run + ".jsonl"), "read_append", create_dirs=True)
        try:
            check_lock()
            _check_fd(fd)
            raw = _read_bytes(fd)
            torn = bool(raw and not raw.endswith(b"\n"))
            cutover = humanproof.record_cutover_read(self.workspace)
            legacy_ok = cutover is None or (cutover is not False and run in cutover)
            head, head_state = humanproof.record_head_read(self.workspace, run)
            if head_state is False:  # damaged, of another run or failing its MAC: treated as missing
                alert_content(self.workspace, run)
            # a head file that exists (a pruned run's tombstone too) means the run is never a legacy run
            present = not (head is None and head_state is True) or not legacy_ok
            if head is not None and head.get("pruned"):
                head = None
            view, mode, _pre = _chain(self.workspace, run, raw, rec, head, present)
            previous = view.events  # verified lines only: an unverified line never suppresses a real one
            legacy = None
            last_seq = view.last_seq
            if mode == "legacy" and raw.strip():
                # the run was made before orch sealed lines: its lines are recorded once, in the head (count
                # and hash of the exact bytes), so they stay readable as "not checked" and nothing else can
                # pass as one. The chain then numbers on after them.
                whole = raw + (b"\n" if torn else b"")
                n = len([x for x in whole.split(b"\n") if x])
                legacy = (n, hashlib.sha256(whole[: record_auth.prefix_cut(whole, n)]).hexdigest())
                last_seq = n
            if head is not None and head["seq"] > last_seq:
                seq, link = head["seq"] + 1, head.get("mac") or record_auth.genesis(rk, ws_id, run)
            else:
                seq, link = last_seq + 1, view.last_mac or record_auth.genesis(rk, ws_id, run)
            event = dict(event, seq=seq)
            if default_id:
                # a hook's default id has its own namespace: <run>:<seq> belongs to the collectors, so a hook
                # line can never take the id of a collector line that is still to come (dedupe would drop it)
                event["id"] = f"{'h_' if event.get('via') == 'hook' else ''}{run}:{event['seq']}"
                if payload is not None:
                    wrapped = json.loads(payload)
                    wrapped["id"] = event["id"]
                    payload = _json(wrapped).encode()
            previous = [dict(e) for e in previous]
            if not _decision(previous, event):
                return None
            if payload is not None:
                event["detail"] = (
                    f"detail/{run}/{detail_name(run, event['kind'], event['id'], event['ticket'])}.json"
                )
            check_lock()
            meta = _open(self.workspace, ("meta.json",), "create_excl")
            if meta is not None:
                try:
                    _write(
                        meta,
                        _json(
                            dict(schema="orch.record/1", since=event["at"], keep_days=90, max_mb=2048)
                        ).encode(),
                    )
                finally:
                    _close(meta)
            else:
                # An existing meta file is never opened for write, but must be trusted.
                check = _open(self.workspace, ("meta.json",), "read")
                _close(check)
            stored = _Detail()
            if payload is not None:
                check_lock()
                stored = _store_detail(self.workspace, event, payload, previous)
                if stored.reason:
                    event.update(detail=None, detail_lost=True)
                else:
                    event["detail_hash"] = stored.hash
            if not _BODY_VALIDATOR.is_valid(event):
                raise RecordInvalid()
            body = _hidden_line(self.hider, event)
            sealed = record_auth.seal(rk, kid, ws_id, run, seq, link, body)
            if len(sealed) > 8192:
                raise RecordInvalid("The record entry is too large.")
            mac = record_auth.split(sealed)[3]
            try:
                check_lock()
                _write(fd, (b"\n" if torn else b"") + sealed)
            except (RecordUnavailable, RecordTampered):
                if stored.created:
                    try:
                        _unlink(self.workspace, tuple(event["detail"].split("/")))
                    except (RecordTampered, RecordUnavailable) as cleanup:
                        if isinstance(cleanup, RecordTampered):
                            _report(self.workspace, cleanup, "detail", run, "writer")
                raise
            self._move_head(run, head, seq, mac, drained=drained, legacy=legacy)
            replaced = [old for old in previous if _replaces(old, event)]
            # a log line without a detail of its own (lost, or none) replaced hook lines: the hook's detail
            # file (the same name) goes when no line the reader keeps points to it, so the agent's payload
            # never stays behind without a line. The line is already written: a failure is only reported.
            name = detail_name(run, event["kind"], event["id"], event["ticket"])  # None: no ticket, no detail
            file = f"{name}.json"
            if (
                name is not None
                and event["detail"] is None
                and any(old.get("detail") == f"detail/{run}/{file}" for old in replaced)
                and not any(
                    old.get("detail") == f"detail/{run}/{file}"
                    and all(old.get(k) == event[k] for k in ("run", "kind", "id", "ticket"))
                    for old in _shown([*previous, event])
                )
            ):
                try:
                    _unlink(self.workspace, ("detail", run, file))
                except (RecordTampered, RecordUnavailable) as cleanup:
                    if isinstance(cleanup, RecordTampered):
                        _report(self.workspace, cleanup, "detail", run, "writer")
            # for the collector (not stored): the hook line of this call was there and said the same
            return dict(event, replaced_hook=True) if replaced else event
        finally:
            _close(fd)

    def _move_head(self, run, head, seq, mac, *, drained=None, rejected=0, legacy=None):
        """Write the chain head after the line (a failure is reported, never raised: the line is stored and
        verifies without it; the next commit moves the head)."""
        body = dict(head or {})
        body.update(run=run, seq=seq, mac=mac)
        body.setdefault("jobs", {})
        body.setdefault("rejected", 0)
        body.setdefault("drained", [])
        body.setdefault("drained_floor", "0" * 20)
        body.setdefault("pruned", None)
        body["rejected"] += rejected
        if legacy is not None and head is None:
            body["legacy_lines"], body["legacy_hash"] = legacy
        if drained:
            names = [*body["drained"], drained]
            horizon = f"{time.time_ns() - 24 * 3600 * 10**9:020d}"
            keep = [n for n in names if n[:20] >= horizon][-512:]
            dropped = [n for n in names if n not in keep]
            if dropped:
                body["drained_floor"] = max(body["drained_floor"], f"{int(max(dropped)[:20]) + 1:020d}")
            body["drained"] = keep
        if not humanproof.record_head_try_write(self.workspace, run, body):
            alert_content(self.workspace, run)

    def _spool(self, event, payload, default_id):
        """A line the lock was too busy for: MACed now (the entry and its file name), sealed into the chain
        only when drained under the lock (it has no seq or link yet)."""
        rec = humanproof.record_key(self.workspace)
        if rec is None:
            raise RecordOff(_OFF_KEY)
        name = f"{time.time_ns():020d}_{uuid.uuid4().hex}.json"
        rel = ("pending", event["run"], name)
        entry = dict(event=event, payload=payload.decode() if payload else None, default_id=default_id)
        entry["sm"] = record_auth.spool_mac(rec[2], rec[0], event["run"], name, dict(entry))
        try:
            fd = _open(self.workspace, rel, "create_excl", create_dirs=True)
            if fd is None:
                raise RecordUnavailable("io")
            try:
                _write(fd, _json(entry).encode())
            finally:
                _close(fd)
        except (RecordTampered, RecordUnavailable) as error:
            _report(self.workspace, error, "folder", event["run"], "writer")
            raise  # the real cause (tampered / unavailable) stays visible to the caller
        result = dict(event, pending=True, seq=None)
        if default_id:
            result.pop("id", None)
        return result

    def drain(self, run, *, check_lock):
        """Commit the run's spooled lines (pending/<run>/) in order. Only for a caller that holds the run
        lock (record.run_lines(drain=...)); `check_lock` is that lock's check."""
        self._drain(run, check_lock=check_lock)

    def _reject(self, run, rel, check_lock):
        """A spool entry orch did not prepare (planted, renamed, replayed, not valid): one alert, deleted by
        its exact path, counted in the head (`rejected`). Never committed, never left in place."""
        alert_content(self.workspace, run)
        # Spool entries are flat regular files. Anything else is never walked and never deleted recursively:
        # a non-directory (a link, fifo, odd file) is removed by its exact name (a link is not followed); a
        # directory is renamed aside once (atomic), where nothing reads it.
        try:
            with _io():
                _unlink(self.workspace, rel)
        except (RecordTampered, RecordUnavailable, RecursionError):
            try:
                _rename_aside(self.workspace, rel, run)
            except (RecordTampered, RecordUnavailable, RecursionError) as error:
                if isinstance(error, RecursionError):
                    return
                _report(self.workspace, error, "folder", run, "writer")
                return
        head, _ = humanproof.record_head_read(self.workspace, run)
        if head is not None:
            self._move_head(run, head, head["seq"], head.get("mac"), rejected=1)
            return
        # No head. A run that is already sealed (a crash before its first head write) gets one now, so the
        # count is kept. A legacy run or a run with no file keeps no count (a head would make it non-legacy):
        # the alert above is its only trace.
        tail = self._sealed_tail(run)
        if tail is not None:
            self._move_head(run, None, tail[0], tail[1], rejected=1)
        else:
            humanproof.record_rejects_bump(self.workspace, run)  # a small guarded counter, no head

    def _sealed_tail(self, run):
        """(seq, mac) of the last verified line of a run that has sealed lines, else None."""
        rec = humanproof.record_key(self.workspace)
        if rec is None:
            return None
        try:
            fd = _open(self.workspace, ("runs", run + ".jsonl"), "read")
        except RecordUnavailable:
            return None
        try:
            raw = _read_bytes(fd)
        finally:
            _close(fd)
        verified, mode, _pre = _chain(self.workspace, run, raw, rec, None, False)
        if mode == "legacy" or not verified.last_mac:
            return None
        return verified.last_seq, verified.last_mac

    def _drain(self, run, *, check_lock=lambda: None):
        try:
            names = _entries(self.workspace, ("pending", run))
        except RecordUnavailable as error:
            if error.reason == "missing":
                return
            raise
        rec = humanproof.record_key(self.workspace)
        if rec is None:
            raise RecordOff(_OFF_KEY)
        for name in sorted(names):
            check_lock()
            rel = ("pending", run, name)
            if not _SPOOL_NAME.fullmatch(name):  # orch never names an entry so: left, alerted, not counted
                _alert(self.workspace, target="folder", run=run, reason="swapped", seen_by="writer")
                continue
            try:
                if _size(self.workspace, rel) > _SPOOL_MAX_BYTES:
                    self._reject(run, rel, check_lock)  # orch never spools more than a line and its detail
                    continue
                pending = _read_json(self.workspace, rel)
            except (RecordTampered, RecordUnavailable) as error:
                _report(self.workspace, error, "folder", run, "writer")
                if isinstance(error, RecordTampered):
                    self._reject(
                        run, rel, check_lock
                    )  # a link, a special file, a folder or not JSON: planted
                continue
            head, _ = humanproof.record_head_read(self.workspace, run)
            drained = (head or {}).get("drained", [])
            floor = (head or {}).get("drained_floor", "0" * 20)
            entry = {k: v for k, v in pending.items() if k != "sm"} if isinstance(pending, dict) else None
            if entry is None or not record_auth.drain_ok(
                rec[2], rec[0], run, name, entry, pending.get("sm"), drained, floor
            ):
                self._reject(run, rel, check_lock)
                continue
            try:
                event = pending["event"]
                _validate(event)
                if event["run"] != run:
                    raise RecordInvalid()
                if not isinstance(pending["default_id"], bool):
                    raise RecordInvalid()
                payload = pending["payload"]
                if payload is not None:
                    wrapped = json.loads(payload)
                    _validate(wrapped, detail=True)
                    if any(wrapped[key] != event[key] for key in ("run", "kind", "id")):
                        raise RecordInvalid()
                    payload = payload.encode()
                    if len(payload) > 1024**2:
                        raise RecordInvalid()
                self._serialized(pending)
                self._line(event)
            except (KeyError, TypeError, ValueError, RecursionError, RecordInvalid):
                self._reject(run, rel, check_lock)
                continue
            try:
                self._commit(event, payload, pending["default_id"], check_lock=check_lock, drained=name)
            except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, RecordInvalid):
                # one bad entry is skipped with a trace, never raised: every later write and every
                # run_lines(drain=...) of the run would fail with it. A lock or run-file problem still raises.
                self._reject(run, rel, check_lock)
                continue
            try:
                with _io():
                    _unlink(self.workspace, rel)
            except (RecordTampered, RecordUnavailable) as error:
                # committed already; left behind it is deduped next time (or alerted), never raised
                _report(self.workspace, error, "folder", run, "writer")


def _files_in_budget(files: list[str]) -> list[str]:
    """Each entry at most 512 serialized bytes, all together at most 2048: trailing entries are dropped."""
    sizes = [len(_json(f).encode()) + 1 for f in files]
    keep = 0
    while keep < len(files) and sizes[keep] <= 512 and sum(sizes[: keep + 1]) <= 2048:
        keep += 1
    return files[:keep]


# The out-of-process hook entry's kinds: only kinds whose line can be provisional (the log's line of the call
# replaces it). A `denial` must say ok: false and `usage` carries numbers no log line checks, so both are the
# log's (and the core's) alone: from the agent's side of the trust boundary they would assert an outcome.
HOOK_KINDS = ("step", "helper.start", "helper.end")
# The only `error` a hook end may carry: a fixed code, never the tool's own text (that goes to the detail).
HOOK_ERRORS = ("tool_failed", "interrupted")


def hook_entry_filter(line: dict) -> dict | None:
    """What the hook entry takes: a hook kind only, `via` forced to hook, an outcome as hook_outcome says."""
    if not isinstance(line, dict) or line.get("kind") not in HOOK_KINDS:
        raise RecordRefused("This kind of record is not allowed here.")
    outcome = line.get("outcome")
    return dict(line, via="hook", **({"outcome": hook_outcome(outcome)} if isinstance(outcome, dict) else {}))


def hook_outcome(outcome: dict) -> dict:
    """The outcome the hook entry stores for a finished line, whatever the caller sent (activity.md,
    Precedence and dedupe): a claimed failure (`ok: false`) is kept with a fixed code (HOOK_ERRORS; any other
    error is `tool_failed`), since it only narrows trust; anything else is provisional (`ok: null`), so a hook
    line never says a call ended well. `ms` is always null (the agent's clock)."""
    if "ok" in outcome and outcome["ok"] is False:
        error = outcome["error"] if "error" in outcome else None
        return {"ok": False, "error": error if error in HOOK_ERRORS else "tool_failed", "ms": None}
    return {"ok": None, "error": None, "ms": None}


def plan_retention(runs: list[dict], now: str, keep_days: int = 90, max_mb: int = 2048) -> dict:
    plan: dict[str, list[str]] = dict(fold_first=[], delete_detail=[], delete_run=[])
    cutoff = datetime.fromisoformat(now) - timedelta(days=keep_days)
    ended = sorted((r for r in runs if r["ended"]), key=lambda r: datetime.fromisoformat(r["ended"]))
    # a run orch cannot check (legacy, unverified: `counted` false) is pruned only by age, and its size never
    # counts toward max_mb: planted big files must not push genuine runs out
    total = sum(r["detail_mb"] + r["file_mb"] for r in runs if r.get("counted", True))
    for run in ended:
        if datetime.fromisoformat(run["ended"]) < cutoff:
            plan["delete_detail"].append(run["run"])
            plan["delete_run"].append(run["run"])
            if run.get("counted", True):
                total -= run["detail_mb"] + run["file_mb"]
    for field, size in (("delete_detail", "detail_mb"), ("delete_run", "file_mb")):
        for run in ended:
            if total <= max_mb:
                break
            if run.get("counted", True) and run["run"] not in plan[field] and run[size] > 0:
                plan[field].append(run["run"])
                total -= run[size]
    plan["fold_first"] = plan["delete_run"].copy()
    return plan


def _detail_parts(workspace, run, seen_by):
    """(what is in detail/<run> that is safe to delete, its size in bytes). One entry that is not safe (a
    link, FIFO or hardlink, a name orch never writes, one that cannot be read: anything with file access can
    plant one) is reported and left out: it stays, never a veto of the run's other detail. The run's folder
    itself not being safe (a link, not a folder) raises; no folder has nothing."""
    try:
        names = _entries(workspace, ("detail", run))
    except RecordUnavailable as error:
        if error.reason != "missing":
            raise
        return [], 0
    found, total = [], 0
    for name in sorted(names):
        try:
            if not re.fullmatch(_PART, name):
                raise RecordInvalid()
            total += _size(workspace, ("detail", run, name))
        except RecordInvalid:
            _report(workspace, RecordTampered("swapped"), "folder", run, seen_by)
            continue
        except RecordTampered as error:
            _report(workspace, error, "folder", run, seen_by)
            continue
        except RecordUnavailable as error:
            if error.reason != "missing":  # cannot be read (e.g. a planted mode-000 file or folder): it stays
                _report(workspace, error, "folder", run, seen_by)
            continue
        found.append(("detail", run, name))
    return found, total


def delete_detail(workspace, runs, *, seen_by="cli"):
    """Retention: delete the detail of these runs. Every run's folder is checked first (nothing is deleted
    when one is a link or not a folder); in each, what is safe goes and what is not (a planted link, FIFO or
    hardlink) stays, reported (_detail_parts): a planted file never keeps the run's real detail past
    retention. The run's folder goes when rmdir finds it empty."""
    rels = [("detail", _name(run, _RUN)) for run in runs]
    try:
        for rel in rels:
            _detail_parts(workspace, rel[-1], seen_by)
        for rel in rels:
            for part in _detail_parts(workspace, rel[-1], seen_by)[0]:
                _rmtree(workspace, part)
            _rmdir_empty(workspace, rel)
    except (RecordTampered, RecordUnavailable) as error:
        _report(workspace, error, "folder", rel[-1], seen_by)
        raise


def _detail_file(run, file_id):
    return ("detail", _name(run, _RUN), _name(file_id, _FILE) + ".json")


@dataclass(frozen=True)
class DetailFiles:
    """What find_detail_files found, or what delete_detail_files deleted. `files`: (run, detail id) pairs
    (found: there and safe; deleted: gone). `unreadable`: runs whose detail FOLDER is not safe (a link, not a
    folder, cannot be read): every pair of them skipped. `kept`: pairs whose single FILE is not safe (a link,
    FIFO or hardlink at its name) or cannot be read: only that pair skipped, the safe files of its run are
    not. Not a tuple, so
    a caller that still unpacks an older answer fails loudly."""

    files: tuple = ()
    unreadable: tuple = ()
    kept: tuple = ()


def find_detail_files(workspace, items, *, seen_by="cli") -> ReadResult[DetailFiles]:
    """Of `items` ((run, detail id) pairs), the ones whose detail file is there, through the hardened walk:
    ReadResult of DetailFiles. Anything with file access can plant a line and a file there, so what is not
    safe is reported and skipped at its own level, never a veto of the others: a run whose detail folder is
    not safe skips that run (`unreadable`); a single file that is not safe or cannot be read skips only that
    pair (`kept`). Only the detail folder itself not being safe refuses."""
    found, unreadable, kept, runs = [], [], [], []
    try:
        try:
            _entries(workspace, ("detail",))
        except RecordUnavailable as error:
            if error.reason != "missing":
                raise
            return ReadResult("ok", DetailFiles())  # no detail at all: nothing to find
        for run, file_id in items:
            if run in unreadable:
                continue
            if run not in runs:
                try:
                    _entries(workspace, ("detail", run))  # the run's folder: a link or not a folder
                except RecordUnavailable as error:
                    if error.reason != "missing":
                        unreadable.append(run)
                        continue
                except RecordTampered as error:
                    _report(workspace, error, "folder", run, seen_by)
                    unreadable.append(run)
                    continue
                runs.append(run)
            try:
                fd = _open(workspace, _detail_file(run, file_id), "read")
            except RecordUnavailable as error:
                if error.reason != "missing":  # cannot be read (e.g. mode 000): only that pair is skipped
                    _report(workspace, error, "folder", run, seen_by)
                    kept.append((run, file_id))
                continue
            except RecordTampered as error:
                _report(workspace, error, "folder", run, seen_by)
                kept.append((run, file_id))
                continue
            _close(fd)
            found.append((run, file_id))
        return ReadResult("ok", DetailFiles(tuple(found), tuple(unreadable), tuple(kept)))
    except (RecordTampered, RecordUnavailable) as error:
        return _report(workspace, error, "folder", None, seen_by)


def ticket_detail_files(workspace, ticket, *, skip=(), seen_by="cli"):
    """ReadResult of ((run, detail id) pairs, runs whose detail folder cannot be read): every file in
    detail/<run>/ whose STORED payload belongs to `ticket` and whose name is the I4 name of its own stored
    (run, kind, id, ticket). So this ticket's own files are found also when no line points at them (orphans: a
    crash between the detail write and its line). A file of another ticket, a name orch never writes, or a
    file that is not valid is left alone, silently (it is not read as this ticket's: no alert). Runs in `skip`
    (their run file cannot be read) are not looked at; a run's detail folder that is not safe is skipped and
    returned as unreadable (no veto). The detail folder itself not being safe refuses."""
    found, unreadable = [], []
    try:
        try:
            runs = _entries(workspace, ("detail",))
        except RecordUnavailable as error:
            if error.reason != "missing":
                raise
            return ReadResult("ok", ([], []))
        for run in sorted(runs):
            if not re.fullmatch(_RUN, run) or run in skip:
                continue
            try:
                names = _entries(workspace, ("detail", run))
            except RecordUnavailable as error:
                if error.reason != "missing":
                    unreadable.append(run)
                continue
            except RecordTampered as error:
                _report(workspace, error, "folder", run, seen_by)
                unreadable.append(run)
                continue
            for name in sorted(names):
                if not re.fullmatch(_FILE + r"\.json", name):
                    continue  # a name orch never writes for a detail file (a writer's tmp_ file too)
                file_id = name[: -len(".json")]
                try:
                    value = _read_json(workspace, ("detail", run, name))
                except (RecordTampered, RecordUnavailable):
                    continue
                if (
                    _DETAIL_VALIDATOR.is_valid(value)
                    and value["run"] == run
                    and value["ticket"] == ticket
                    and detail_name(run, value["kind"], value["id"], ticket) == file_id
                ):
                    found.append((run, file_id))
        return ReadResult("ok", (found, unreadable))
    except (RecordTampered, RecordUnavailable) as error:
        return _report(workspace, error, "folder", None, seen_by)


def delete_detail_files(workspace, items, *, seen_by="cli") -> DetailFiles:
    """Delete exactly these detail files ((run, detail id) pairs), run by run UNDER THE RUN'S LOCK (the writer
    stores detail under it). Returns DetailFiles: `files` the pairs deleted by this call. A file can be
    swapped after find_detail_files, so the same levels apply here, never a veto of the others: a run whose
    detail folder (or lock) is not safe now is reported and skipped (`unreadable`); a single file that is not
    safe now (a link, FIFO, hardlink, one that cannot be read or unlinked) is reported and stays (`kept`), its
    safe siblings go. A run's detail folder goes only when rmdir finds it empty, so detail of other tickets in
    the same run (also one written in between) and a kept file stay. A file or run folder that is missing
    (retention pruned it since it was found) is already gone: not counted, never a failure. Raises only for
    the detail folder itself, a busy lock or an I/O error on a run's folder or lock."""
    found, unreadable, kept = [], [], []
    run = None
    try:
        _entries(workspace, ("detail",))  # the detail folder itself not safe: refuse with nothing deleted
        for run in dict.fromkeys(ref[0] for ref in items):
            try:
                with _lock(workspace, run) as check_lock:
                    check_lock()
                    _entries(workspace, ("detail", run))  # the run's folder: a link or not a folder skips it
                    for ref in items:
                        if ref[0] != run:
                            continue
                        check_lock()
                        try:
                            _size(workspace, _detail_file(*ref))  # missing: 0, already gone
                        except RecordTampered as error:
                            _report(workspace, error, "folder", run, seen_by)
                            kept.append(ref)
                            continue
                        except RecordUnavailable as error:
                            if error.reason != "missing":  # cannot be read now (e.g. mode 000): only it stays
                                _report(workspace, error, "folder", run, seen_by)
                                kept.append(ref)
                            continue
                        check_lock()
                        try:
                            gone = _unlink(workspace, _detail_file(*ref))  # missing: False, already gone
                        except RecordUnavailable as error:
                            _report(workspace, error, "folder", run, seen_by)
                            kept.append(ref)
                            continue
                        if gone:
                            found.append(ref)
                    check_lock()
                    _rmdir_empty(workspace, ("detail", run))
            except RecordUnavailable as error:
                if error.reason != "missing":
                    raise
            except RecordTampered as error:
                _report(workspace, error, "folder", run, seen_by)
                unreadable.append(run)
    except RecordUnavailable as error:
        if error.reason != "missing":  # missing: no detail at all (retention pruned it), nothing to delete
            _report(workspace, error, "folder", run, seen_by)
            raise
    except RecordTampered as error:
        _report(workspace, error, "folder", run, seen_by)
        raise
    return DetailFiles(tuple(found), tuple(unreadable), tuple(kept))


def record_sizes(workspace):
    """ReadResult of {"record": bytes, "detail": bytes} through the hardened walk (no record yet: zeros). A
    name orch never writes inside the record counts as changed outside orch."""
    try:
        try:
            names = _entries(workspace, ())
        except RecordUnavailable as error:
            if error.reason != "missing":
                raise
            names = []
        total = sum(_size(workspace, (name,)) for name in names)
        return ReadResult("ok", dict(record=total, detail=_size(workspace, ("detail",))))
    except RecordInvalid:
        return _report(workspace, RecordTampered("swapped"), "folder", None, "reader")
    except (RecordTampered, RecordUnavailable) as error:
        return _report(workspace, error, "folder", None, "reader")


def note_change(workspace, *, change, by, ticket, deleted):
    """One audit line for a person's change to the record (`orch.record-change/1`, e.g.
    record.delete_detail) in the unattributed daily file alerts/<day>.jsonl. Raises when it cannot be stored
    (the caller then changes nothing)."""
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    line = dict(
        v=1, schema="orch.record-change/1", at=now, change=change, by=by, ticket=ticket, deleted=deleted
    )
    if not _CHANGE_VALIDATOR.is_valid(line):
        raise RecordInvalid()
    fd = _open(workspace, ("alerts", now[:10] + ".jsonl"), "append", create_dirs=True)
    try:
        _write(fd, (_json(line) + "\n").encode())
    finally:
        _close(fd)
    return line


def _ended(events):
    states = [e for e in events if e["kind"] == "run.state"]
    last = states[-1] if states else None
    return last["at"] if last and last.get("data", {}).get("state") in ("done", "failed", "stopped") else None


def _ended_run(run, events, now):
    """When a run ended. The unattributed run of a day (`r_outside_<yyyymmdd>`, for uses outside any run) ends
    at the next 00:00Z, taken from its id and never from lines in the file (anything that can write the file
    could plant a run.state); it counts as ended only once that moment has passed."""
    m = re.fullmatch(r"r_outside_(\d{8})", run)
    if not m:
        return _ended(events)
    try:
        d = m[1]
        end = datetime.fromisoformat(f"{d[:4]}-{d[4:6]}-{d[6:]}T00:00:00+00:00") + timedelta(days=1)
        over = end <= datetime.fromisoformat(now)
    except (ValueError, TypeError):
        return None
    return f"{end:%Y-%m-%dT%H:%M:%SZ}" if over else None


def is_sealed(line) -> bool:
    """The ONE definition of "orch verified this line": it is a line of a run read through the verified view,
    not a line of a legacy run and not one made before protection. What retention, caps, counts and run state
    may believe (a hook line is sealed too: it is verified to be the hook entry's, see is_checked)."""
    return not line.get("before_protection")


def is_checked(line) -> bool:
    """The ONE definition of the computed `checked` marker (never stored): True only for a sealed, verified
    line that is not a hook line (a verified `via: hook` line is still the agent's word). Every screen,
    count and detail that shows or reads a trust marker uses this and nothing else."""
    return is_sealed(line) and line.get("via") != "hook"


def _own(events):
    """The lines orch checked (not those made before protection): the only ones retention may believe."""
    return [e for e in events if is_sealed(e)]


def _tombstone(workspace, run, now):
    """The run's chain head says it was pruned on purpose (a run file that is gone otherwise is `removed`)."""
    head, _ = humanproof.record_head_read(workspace, run)
    if head is None and humanproof.record_head_state(workspace, run) != "present":
        return
    humanproof.record_head_try_write(workspace, run, dict(head or {"seq": 0}, pruned=now))


def _retention_end(workspace, run, read, now):
    """(when the run ended, whether its size counts toward max_mb), or None when retention must leave it.
    A checked run ends with its checked core run.state. A run orch cannot check (a legacy run, or one whose
    records are unverified or from before a protection reset) ends when its file was last written: it is
    pruned once that is older than keep_days, and its size never counts toward max_mb."""
    if read.status == "ok" and not read.legacy:
        return _ended_run(run, _own(read.value), now), True
    if (read.status == "ok" and read.legacy) or (
        read.status == "tampered" and read.reason in ("unverified", "old_key")
    ):
        return _mtime_iso(workspace, ("runs", run + ".jsonl")), False
    return None


def apply_retention(workspace, now, keep_days, max_mb, fold: Callable[[str, list[dict]], Any]):
    """Apply retention; fold must be idempotent per run because skipped runs may retry."""
    result = dict(
        fold_first=[], delete_detail=[], delete_run=[], status="ok", reason=None, message=None, alert=None
    )

    def failed(read):
        if result["status"] == "ok":
            result.update(status=read.status, reason=read.reason, message=read.message, alert=read.alert)

    listed = list_runs(workspace)
    if listed.status != "ok":
        failed(listed)
        return result
    runs = []
    for run in listed.value:
        read = read_run(workspace, run, seen_by="retention")
        try:
            end = _retention_end(workspace, run, read, now)
        except (RecordTampered, RecordUnavailable) as error:
            failed(_report(workspace, error, "folder", run, "retention"))
            continue
        if end is None:
            failed(read)
            continue
        try:
            runs.append(
                dict(
                    run=run,
                    ended=end[0],
                    counted=end[1],
                    detail_mb=_detail_parts(workspace, run, "retention")[1] / 1024**2,
                    file_mb=(_size(workspace, ("runs", run + ".jsonl")) + _size(workspace, ("jobs", run)))
                    / 1024**2,
                )
            )
        except (RecordTampered, RecordUnavailable) as error:
            failed(_report(workspace, error, "folder", run, "retention"))
    plan = plan_retention(runs, now, keep_days, max_mb)
    snapshots = {r["run"]: r["ended"] for r in runs}
    for run in dict.fromkeys(plan["fold_first"] + plan["delete_detail"]):
        try:
            with _lock(workspace, run) as check_lock:
                read = read_run(workspace, run, seen_by="retention")
                end = _retention_end(workspace, run, read, now)
                if end is None:
                    failed(read)
                    continue
                if read.pending:
                    failed(ReadResult("unavailable", reason="pending", message=_MESSAGES["pending"]))
                    continue
                ended_now = end[0]
                if not ended_now or ended_now != snapshots[run]:
                    continue
                # Check every deletion target before invoking the irreversible fold. In detail/<run> only the
                # run's folder can refuse; a planted file in it is skipped (delete_detail), never a veto.
                check_lock()
                _detail_parts(workspace, run, "retention")
                check_lock()
                _pending_preflight(workspace, run)
                for rel in (("jobs", run), ("runs", run + ".jsonl")):
                    check_lock()
                    _size(workspace, rel)
                check_lock()
                if _pending_count(workspace, run):
                    failed(ReadResult("unavailable", reason="pending", message=_MESSAGES["pending"]))
                    continue
                fold(run, _own(read.value or []))
                check_lock()
                if _pending_count(workspace, run):
                    failed(ReadResult("unavailable", reason="pending", message=_MESSAGES["pending"]))
                    continue
                if run in plan["delete_detail"]:
                    check_lock()
                    delete_detail(workspace, [run], seen_by="retention")
                    result["delete_detail"].append(run)
                if run in plan["delete_run"]:
                    check_lock()
                    _rmtree(workspace, ("jobs", run))
                    _tombstone(workspace, run, now)  # first: a run file that is gone without it is `removed`
                    check_lock()
                    _unlink(workspace, ("runs", run + ".jsonl"))
                    result["delete_run"].append(run)
                    result["fold_first"].append(run)
        except RecordBusy:
            continue
        except (RecordTampered, RecordUnavailable) as error:
            failed(_report(workspace, error, "folder", run, "retention"))
    return result


# Bundled contract: installed packages do not have the repository's contracts directory.
_SCHEMA = {
    "$schema": ("https://json-schema.org/draft/2020-12/schema"),
    "$id": ("https://orch.severin.io/contracts/activity.schema.json"),
    "title": ("orch activity event v1 (orch.activity/1, one line of .orch/record/runs/<run>.jsonl)"),
    "description": (
        "One thing an agent run did, the same "
        "for every agent tool. See activity.md. "
        "Written only by the core record writer, "
        "which hides exact key values first "
        "(fail closed). Readers skip unknown "
        "kinds and keep unknown fields. text and "
        "every string are plain text (shown with "
        "textContent)."
    ),
    "$ref": "#/$defs/event",
    "$defs": {
        "event": {
            "type": "object",
            "required": [
                "v",
                "id",
                "seq",
                "run",
                "session",
                "agent",
                "parent",
                "at",
                "ticket",
                "harness",
                "via",
                "kind",
                "text",
                "used",
                "outcome",
                "detail",
                "coverage",
            ],
            "properties": {
                "v": {"const": 1},
                "id": {
                    "$ref": "#/$defs/event_id",
                    "description": (
                        "The agent tool's own tool-call id when "
                        "the source has one, else '<run>:<seq>' "
                        "(activity.md, Ids)."
                    ),
                },
                "seq": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Position in this run file, +1 per written line, set by the single writer."
                    ),
                },
                "run": {"$ref": "#/$defs/run"},
                "session": {
                    "oneOf": [
                        {"type": "null"},
                        {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[A-Za-z0-9_.:-]+$"},
                    ],
                    "description": "The agent tool's session id, or null.",
                },
                "agent": {"$ref": "#/$defs/agent"},
                "parent": {
                    "oneOf": [{"type": "null"}, {"$ref": "#/$defs/agent"}],
                    "description": ("Who started this agent: null for main, else main or another helper."),
                },
                "at": {"$ref": "#/$defs/time"},
                "ticket": {"type": "string", "pattern": "^t_[a-z0-9]{6,16}$"},
                "harness": {
                    "type": "string",
                    "pattern": "^[a-z][a-z0-9-]{0,31}$",
                    "description": (
                        "Adapter name of the run "
                        "(agent-adapter.schema.json key or "
                        "[agents.<name>] entry); 'generic' for a "
                        "user entry; 'none' for a job run "
                        "without an agent."
                    ),
                },
                "via": {
                    "enum": ["hook", "log", "broker", "job", "core"],
                    "description": (
                        "Who wrote it: hook = the tool's own "
                        "hook (instant), log = a collector "
                        "reading the tool's log or stream, "
                        "broker = orch secret, job = orch job / "
                        "$ORCH_EVENTS, core = orch itself "
                        "(ticket changes, run state, take-over)."
                    ),
                },
                "kind": {"$ref": "#/$defs/kind"},
                "text": {
                    "type": "string",
                    "maxLength": 500,
                    "pattern": "^[^\\u0000-\\u001f\\u007f]*$",
                    "description": ("Short display line, one line, key values hidden."),
                },
                "used": {
                    "oneOf": [
                        {"type": "null"},
                        {
                            "type": "object",
                            "required": ["kind", "name", "action", "source", "version"],
                            "additionalProperties": False,
                            "properties": {
                                "kind": {
                                    "enum": ["skill", "tool", "mcp", "key", "helper"],
                                    "description": (
                                        "Shown as Skill, Tool, Connection, Key, "
                                        "Helper (wording: 'MCP' only under "
                                        "Details)."
                                    ),
                                },
                                "name": {"$ref": "#/$defs/name"},
                                "action": {
                                    "oneOf": [{"type": "null"}, {"$ref": "#/$defs/name"}],
                                    "description": (
                                        "Tool of a connection (read_file), key "
                                        "delivery (env, file, exec, get), or "
                                        "null."
                                    ),
                                },
                                "source": {
                                    "enum": ["harness", "admin", "workspace", "builtin", "marketplace"],
                                    "description": (
                                        "harness = the agent tool's own "
                                        "settings, admin = shared by the admin, "
                                        "workspace = this workspace, builtin = "
                                        "part of orch or of the agent tool, "
                                        "marketplace = an installed add-on."
                                    ),
                                },
                                "version": {
                                    "oneOf": [{"type": "null"}, {"$ref": "#/$defs/version"}],
                                    "description": (
                                        "Content hash of the skill or connection "
                                        "config at the time of use "
                                        "(inventory.md)."
                                    ),
                                },
                            },
                        },
                    ]
                },
                "outcome": {
                    "oneOf": [
                        {"type": "null"},
                        {
                            "type": "object",
                            "required": ["ok", "error", "ms"],
                            "additionalProperties": False,
                            "properties": {
                                "ok": {
                                    "type": ["boolean", "null"],
                                    "description": ("null = finished, result unknown to the source."),
                                },
                                "error": {
                                    "oneOf": [
                                        {"type": "null"},
                                        {
                                            "type": "string",
                                            "minLength": 1,
                                            "maxLength": 300,
                                            "pattern": "^[^\\u0000-\\u001f\\u007f]*$",
                                        },
                                    ]
                                },
                                "ms": {"oneOf": [{"type": "null"}, {"type": "integer", "minimum": 0}]},
                            },
                        },
                    ],
                    "description": (
                        "null = started, not finished yet. A "
                        "later line with the same id and kind "
                        "carries the outcome (activity.md, "
                        "Dedupe)."
                    ),
                },
                "detail": {
                    "oneOf": [
                        {"type": "null"},
                        {"type": "string", "pattern": ("^detail/r_[a-z0-9_]{6,32}/[0-9a-f]{32}\\.json$")},
                    ],
                    "description": (
                        "Full payload file, relative to .orch/record/; null = details not available."
                    ),
                },
                "coverage": {
                    "enum": ["full", "partial"],
                    "description": (
                        "full = the source saw everything of "
                        "this step; partial = something is "
                        "missing (no chat text, cut output, no "
                        "helper)."
                    ),
                },
                "data": {
                    "type": "object",
                    "description": ("Per-kind fields (activity.md, Kinds). Unknown fields are kept."),
                },
                "conflict": {
                    "type": "boolean",
                    "description": (
                        "The hook and log lines of one call "
                        "disagree; both are kept, this (log) "
                        "line is the one to believe."
                    ),
                },
                "detail_lost": {
                    "type": "boolean",
                    "description": (
                        "true = a full payload existed but could "
                        "not be stored (name collision with "
                        "another event's file, write problem, "
                        "too large); the line is kept with "
                        "detail null (activity.md, Detail files)."
                    ),
                },
                "files": {"$ref": "#/$defs/files"},
                "detail_hash": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{32}$",
                    "description": (
                        "First 16 bytes of sha256 of the detail "
                        "file's exact bytes, lowercase hex; "
                        "present iff detail is non-null "
                        "(activity.md, Authenticated record). "
                        "Inside the MAC."
                    ),
                },
                "auth": {
                    "$ref": "#/$defs/auth",
                    "description": (
                        "The record MAC suffix of a sealed line "
                        "(activity.md, Authenticated record). "
                        "The event body that is MACed never "
                        "contains it; use $defs/sealed_event to "
                        "require it."
                    ),
                },
            },
            "allOf": [
                {
                    "if": {"properties": {"detail": {"type": "null"}}, "required": ["detail"]},
                    "then": {"not": {"required": ["detail_hash"]}},
                },
                {
                    "if": {"properties": {"agent": {"const": "main"}}},
                    "then": {"properties": {"parent": {"type": "null"}}},
                    "else": {"properties": {"parent": {"$ref": "#/$defs/agent"}}},
                },
                {
                    "if": {"properties": {"kind": {"const": "step"}}},
                    "then": {
                        "properties": {
                            "via": {"enum": ["hook", "log"]},
                            "used": {
                                "type": "object",
                                "properties": {"kind": {"enum": ["skill", "tool", "mcp"]}},
                            },
                        }
                    },
                    "else": {"not": {"required": ["files"]}},
                },
                {
                    "if": {"properties": {"kind": {"enum": ["task.start", "task.done"]}}},
                    "then": {
                        "required": ["data"],
                        "properties": {
                            "via": {"const": "core"},
                            "data": {
                                "anyOf": [
                                    {
                                        "required": ["check"],
                                        "properties": {
                                            "check": {"type": "string", "pattern": "^c[0-9]{1,4}$"}
                                        },
                                    },
                                    {
                                        "type": "object",
                                        "required": ["cut"],
                                        "additionalProperties": False,
                                        "properties": {"cut": {"const": True}},
                                    },
                                ]
                            },
                        },
                    },
                },
                {
                    "if": {"properties": {"kind": {"const": "ask"}}},
                    "then": {
                        "required": ["data"],
                        "properties": {
                            "via": {"const": "core"},
                            "data": {
                                "anyOf": [
                                    {
                                        "required": ["q"],
                                        "properties": {"q": {"type": "string", "pattern": "^q[0-9]{1,4}$"}},
                                    },
                                    {
                                        "type": "object",
                                        "required": ["cut"],
                                        "additionalProperties": False,
                                        "properties": {"cut": {"const": True}},
                                    },
                                ]
                            },
                        },
                    },
                },
                {
                    "if": {"properties": {"kind": {"const": "denial"}}},
                    "then": {
                        "properties": {"outcome": {"type": "object", "properties": {"ok": {"const": False}}}}
                    },
                },
                {
                    "if": {"properties": {"kind": {"enum": ["helper.start", "helper.end"]}}},
                    "then": {
                        "properties": {
                            "agent": {"pattern": "^h_[0-9]{1,4}$"},
                            "used": {"type": "object", "properties": {"kind": {"const": "helper"}}},
                        }
                    },
                },
                {
                    "if": {"properties": {"kind": {"const": "run.state"}}},
                    "then": {
                        "required": ["data"],
                        "properties": {
                            "data": {
                                "anyOf": [
                                    {
                                        "required": ["state"],
                                        "properties": {
                                            "state": {
                                                "enum": [
                                                    "starting",
                                                    "working",
                                                    "waiting_you",
                                                    "idle",
                                                    "done",
                                                    "failed",
                                                    "stopped",
                                                ]
                                            }
                                        },
                                    },
                                    {
                                        "type": "object",
                                        "required": ["cut"],
                                        "additionalProperties": False,
                                        "properties": {"cut": {"const": True}},
                                    },
                                ]
                            }
                        },
                    },
                },
                {
                    "if": {"properties": {"kind": {"const": "usage"}}},
                    "then": {
                        "required": ["data"],
                        "properties": {
                            "data": {
                                "anyOf": [
                                    {
                                        "anyOf": [{"required": ["used"]}, {"required": ["tokens_in"]}],
                                        "properties": {
                                            "used": {"type": "number", "minimum": 0, "maximum": 1},
                                            "window": {"type": "string", "maxLength": 32},
                                            "status": {"enum": ["ok", "warning", "limited"]},
                                            "tokens_in": {"type": "integer", "minimum": 0},
                                            "tokens_out": {"type": "integer", "minimum": 0},
                                        },
                                    },
                                    {
                                        "type": "object",
                                        "required": ["cut"],
                                        "additionalProperties": False,
                                        "properties": {"cut": {"const": True}},
                                    },
                                ]
                            }
                        },
                    },
                },
                {
                    "if": {"properties": {"kind": {"const": "key.use"}}},
                    "then": {
                        "required": ["data"],
                        "properties": {
                            "via": {"const": "broker"},
                            "detail": {"type": "null"},
                            "used": {
                                "type": "object",
                                "required": ["kind"],
                                "properties": {
                                    "kind": {"const": "key"},
                                    "action": {"enum": ["env", "file", "exec", "get"]},
                                    "source": {"enum": ["workspace", "admin"]},
                                },
                            },
                            "outcome": {"type": "object"},
                            "data": {
                                "anyOf": [
                                    {
                                        "required": ["profile", "command"],
                                        "additionalProperties": False,
                                        "properties": {
                                            "profile": {"$ref": "#/$defs/name"},
                                            "command": {
                                                "oneOf": [
                                                    {"type": "null"},
                                                    {"type": "string", "pattern": "^[A-Za-z0-9_.+-]{1,64}$"},
                                                ],
                                                "description": (
                                                    "Base name of the program the key was "
                                                    "handed to; never its arguments."
                                                ),
                                            },
                                            "skill": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/name"}]},
                                            "refused": {
                                                "enum": [
                                                    "not_in_profile",
                                                    "get_off",
                                                    "get_to_terminal",
                                                    "missing",
                                                    "too_short",
                                                    "switched_off",
                                                    "agent_command",
                                                ]
                                            },
                                        },
                                    },
                                    {
                                        "type": "object",
                                        "required": ["cut"],
                                        "additionalProperties": False,
                                        "properties": {"cut": {"const": True}},
                                    },
                                ]
                            },
                        },
                    },
                },
                {
                    "if": {"properties": {"kind": {"const": "secret.change"}}},
                    "then": {
                        "required": ["data"],
                        "properties": {
                            "via": {"const": "broker"},
                            "detail": {"type": "null"},
                            "used": {"type": "null"},
                            "data": {
                                "anyOf": [
                                    {
                                        "required": ["action", "profile", "by"],
                                        "additionalProperties": False,
                                        "properties": {
                                            "action": {
                                                "enum": [
                                                    "profile.set",
                                                    "profile.remove",
                                                    "profile.get_enable",
                                                    "profile.get_disable",
                                                    "profile.agents_enable",
                                                    "profile.agents_disable",
                                                ]
                                            },
                                            "profile": {"$ref": "#/$defs/name"},
                                            "by": {
                                                "type": "string",
                                                "pattern": "^(human:.+|reset)$",
                                                "maxLength": 64,
                                                "description": (
                                                    "human:<name> from the proof, or reset (no proof)."
                                                ),
                                            },
                                        },
                                    },
                                    {
                                        "type": "object",
                                        "required": ["cut"],
                                        "additionalProperties": False,
                                        "properties": {"cut": {"const": True}},
                                    },
                                ]
                            },
                        },
                    },
                },
                {
                    "if": {"properties": {"kind": {"const": "job"}}},
                    "then": {
                        "required": ["data"],
                        "properties": {
                            "via": {"const": "job"},
                            "data": {
                                "anyOf": [
                                    {
                                        "required": ["job", "type", "state"],
                                        "properties": {
                                            "job": {"type": "string", "pattern": "^j_[a-z0-9]{6,32}$"},
                                            "type": {
                                                "enum": [
                                                    "start",
                                                    "step",
                                                    "progress",
                                                    "artifact",
                                                    "metric",
                                                    "table",
                                                    "link",
                                                    "log",
                                                    "end",
                                                    "lost",
                                                ]
                                            },
                                            "state": {
                                                "enum": ["running", "ok", "failed", "cancelled", "lost"]
                                            },
                                        },
                                    },
                                    {
                                        "type": "object",
                                        "required": ["cut"],
                                        "additionalProperties": False,
                                        "properties": {"cut": {"const": True}},
                                    },
                                ]
                            },
                        },
                    },
                },
                {
                    "if": {"properties": {"kind": {"const": "session.input"}}},
                    "then": {
                        "required": ["data"],
                        "properties": {
                            "via": {"const": "core"},
                            "used": {"type": "null"},
                            "detail": {"type": "null"},
                            "data": {
                                "anyOf": [
                                    {
                                        "required": ["by", "from", "since", "ended", "reason", "keys"],
                                        "additionalProperties": False,
                                        "properties": {
                                            "by": {
                                                "type": "string",
                                                "pattern": "^human:[^\\u0000-\\u001f]{1,58}$",
                                                "description": "Only a person can take over.",
                                            },
                                            "from": {"const": "local-page"},
                                            "since": {"$ref": "#/$defs/time"},
                                            "ended": {"$ref": "#/$defs/time"},
                                            "reason": {
                                                "enum": [
                                                    "released",
                                                    "idle",
                                                    "run-ended",
                                                    "switched-off",
                                                    "locked-by-admin",
                                                ]
                                            },
                                            "keys": {
                                                "type": "integer",
                                                "minimum": 0,
                                                "description": (
                                                    "How many key presses were sent. The "
                                                    "typed text is never stored."
                                                ),
                                            },
                                        },
                                    },
                                    {
                                        "type": "object",
                                        "required": ["cut"],
                                        "additionalProperties": False,
                                        "properties": {"cut": {"const": True}},
                                    },
                                ]
                            },
                        },
                    },
                },
            ],
        },
        "auth": {
            "type": "object",
            "additionalProperties": False,
            "required": ["k", "p", "m"],
            "properties": {
                "k": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{8}$",
                    "description": "Key id of the record subkey.",
                },
                "p": {
                    "type": "string",
                    "pattern": "^[A-Za-z0-9_-]{43}$",
                    "description": ("MAC of the previous line of the chain (the genesis MAC for the first)."),
                },
                "m": {
                    "type": "string",
                    "pattern": "^[A-Za-z0-9_-]{43}$",
                    "description": ("HMAC-SHA256 over the line's exact body bytes, run, seq and p."),
                },
            },
        },
        "event_body": {
            "allOf": [
                {"$ref": "#/$defs/event"},
                {"not": {"required": ["auth"]}},
                {
                    "if": {"properties": {"detail": {"type": "string"}}, "required": ["detail"]},
                    "then": {"required": ["detail_hash"]},
                },
            ],
            "description": (
                "What the writer validates and MACs: the "
                "event as it is written, without auth. "
                "detail_hash is required iff detail is "
                "non-null."
            ),
        },
        "sealed_event": {
            "allOf": [
                {"$ref": "#/$defs/event"},
                {"required": ["auth"]},
                {
                    "if": {"properties": {"detail": {"type": "string"}}, "required": ["detail"]},
                    "then": {"required": ["detail_hash"]},
                },
            ],
            "description": (
                "One line of runs/<run>.jsonl as stored "
                "once sealed. A reader checks the MAC "
                "before it trusts any field."
            ),
        },
        "time": {"type": "string", "format": "date-time", "pattern": "Z$"},
        "kind": {
            "enum": [
                "step",
                "task.start",
                "task.done",
                "ask",
                "denial",
                "helper.start",
                "helper.end",
                "run.state",
                "usage",
                "key.use",
                "secret.change",
                "job",
                "session.input",
            ]
        },
        "run": {"type": "string", "pattern": "^r_[a-z0-9_]{6,32}$"},
        "agent": {"type": "string", "pattern": "^(main|h_[0-9]{1,4})$"},
        "event_id": {"type": "string", "minLength": 1, "maxLength": 160, "pattern": "^[A-Za-z0-9_.:-]+$"},
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": 128,
            "pattern": "^[^\\u0000-\\u001f\\u007f<>]+$",
        },
        "version": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "files": {
            "type": "array",
            "maxItems": 8,
            "items": {"$ref": "#/$defs/file_path"},
            "description": (
                "Only on kind step: the workspace files "
                "or folders the step named, display "
                "only, never used for access decisions "
                "(activity.md, Files)."
            ),
        },
        "file_path": {
            "type": "string",
            "minLength": 1,
            "maxLength": 260,
            "pattern": (
                "^(?![A-Za-z]:)(?![A-Za-z][A-Za-z0-9+.-]*"
                ":)(?![~$])(?!/)(?!(?:.*/)?\\.\\.(?:/|$))[^"
                "\\u0000-\\u001f\\u007f-\\u009f\\u00ad\\u0600-\\"
                "u0605\\u061c\\u06dd\\u070f\\u0890-\\u0891\\u08"
                "e2\\u180e\\u200b-\\u200f\\u2028-\\u202e\\u2060"
                "-\\u2064\\u2066-\\u206f\\ufeff\\ufff9-\\ufffb\\"
                "\\]+$"
            ),
            "description": (
                "Workspace-relative POSIX path: no "
                "leading /, no .. segment, no backslash, "
                "no start with ~ $ or a scheme or drive "
                "letter (file: C:), no Unicode control "
                "or format character (Cc Cf Zl Zp: bidi "
                "overrides, zero-width), NFC. The writer "
                "enforces the full rule "
                "(record_files.file_ok); this pattern "
                "lists the BMP characters."
            ),
        },
        "detail_file": {
            "type": "object",
            "required": ["v", "id", "run", "kind", "ticket", "input", "output", "truncated", "hidden"],
            "additionalProperties": False,
            "description": (
                "One file "
                ".orch/record/detail/<run>/<file "
                "name>.json: the full payload of one "
                "event, key values hidden. The file name "
                "is lowercase hex only (activity.md, "
                "Detail files); id, kind and ticket are "
                "stored here so a reader can verify the "
                "file belongs to the event."
            ),
            "properties": {
                "v": {"const": 1},
                "id": {"$ref": "#/$defs/event_id"},
                "run": {"$ref": "#/$defs/run"},
                "kind": {"$ref": "#/$defs/kind"},
                "ticket": {
                    "type": "string",
                    "pattern": "^t_[a-z0-9]{6,16}$",
                    "description": ("The ticket of the event; part of the file name (activity.md, I4)."),
                },
                "input": {"description": ("What went in (tool input, prompt, command), any JSON.")},
                "output": {"description": ("What came out (tool result, chat text), any JSON.")},
                "truncated": {"type": "boolean", "description": "true = cut at the 1 MB per-file cap."},
                "hidden": {
                    "type": "integer",
                    "minimum": 0,
                    "description": ("How many key values were hidden in this file."),
                },
                "checked": {
                    "type": "boolean",
                    "description": (
                        "Computed by the reader, never stored: false when the detail was made before orch "
                        "checked it (not checked, before protection)."
                    ),
                },
            },
        },
        "record_alert": {
            "type": "object",
            "additionalProperties": False,
            "required": ["v", "schema", "at", "target", "run", "reason", "seen_by", "message"],
            "properties": {
                "v": {"const": 1},
                "schema": {"const": "orch.record-alert/1"},
                "at": {"$ref": "#/$defs/time"},
                "target": {"enum": ["run", "detail", "meta", "lock", "folder", "alerts"]},
                "run": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/run"}]},
                "reason": {
                    "enum": [
                        "link",
                        "reparse",
                        "hardlink",
                        "foreign_owner",
                        "not_regular",
                        "not_dir",
                        "swapped",
                        "content",
                        "removed",
                        "unverified",
                        "old_key",
                    ]
                },
                "seen_by": {"enum": ["writer", "reader", "retention", "cli"]},
                "message": {
                    "const": (
                        "Some records of this run were changed "
                        "outside orch. To be safe, orch does not "
                        "show them. Nothing was deleted."
                    )
                },
            },
        },
        "record_change": {
            "type": "object",
            "additionalProperties": False,
            "description": (
                "One audit line in "
                "alerts/<YYYY-MM-DD>.jsonl for a "
                "person's proven change to the record "
                "(activity.md, Delete detail). No path, "
                "no record content."
            ),
            "required": ["v", "schema", "at", "change", "by", "ticket", "deleted"],
            "properties": {
                "v": {"const": 1},
                "schema": {"const": "orch.record-change/1"},
                "at": {"$ref": "#/$defs/time"},
                "change": {"enum": ["record.delete_detail"]},
                "by": {"type": "string", "pattern": "^human:[^\\u0000-\\u001f]{1,58}$"},
                "ticket": {"type": "string", "pattern": "^t_[a-z0-9]{6,16}$"},
                "deleted": {"type": "integer", "minimum": 0},
            },
        },
        "read_status": {
            "type": "object",
            "additionalProperties": False,
            "required": ["run", "status", "reason", "message"],
            "properties": {
                "pending": {"type": "integer", "minimum": 0},
                "changed": {"type": "integer", "minimum": 0},
                "removed": {"type": "integer", "minimum": 0},
                "run": {"oneOf": [{"type": "null"}, {"$ref": "#/$defs/run"}]},
                "status": {"enum": ["ok", "unavailable", "tampered"]},
                "reason": {
                    "enum": [
                        "missing",
                        "io",
                        "skipped",
                        "pending",
                        "link",
                        "reparse",
                        "hardlink",
                        "foreign_owner",
                        "not_regular",
                        "not_dir",
                        "swapped",
                        "content",
                        "removed",
                        "unverified",
                        "old_key",
                        "unchecked",
                    ]
                },
                "message": {"type": "string", "maxLength": 500},
            },
        },
        "record_meta": {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema", "since", "keep_days", "max_mb"],
            "properties": {
                "schema": {"const": "orch.record/1"},
                "since": {"$ref": "#/$defs/time"},
                "keep_days": {"type": "integer", "minimum": 0},
                "max_mb": {"type": "integer", "minimum": 0},
            },
        },
    },
}

_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_BODY_VALIDATOR = Draft202012Validator(
    {"$ref": "#/$defs/event_body", "$defs": _SCHEMA["$defs"]}, format_checker=FormatChecker()
)
_DETAIL_VALIDATOR = Draft202012Validator(
    {"$ref": "#/$defs/detail_file", "$defs": _SCHEMA["$defs"]}, format_checker=FormatChecker()
)
_META_VALIDATOR = Draft202012Validator(
    {"$ref": "#/$defs/record_meta", "$defs": _SCHEMA["$defs"]}, format_checker=FormatChecker()
)
_CHANGE_VALIDATOR = Draft202012Validator(
    {"$ref": "#/$defs/record_change", "$defs": _SCHEMA["$defs"]}, format_checker=FormatChecker()
)
