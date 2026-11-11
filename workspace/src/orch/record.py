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
from orch.collect_execjson import _hash, detail_name
from orch.errors import Refused
from orch.hider import Hider, NoHiderError
from orch.phone_view import redact

_OFF = "Recording is off until key hiding is ready."
_INVALID = "This record entry is not valid."
_RUN = r"r_[a-z0-9_]{6,32}"
_FILE = r"[0-9a-f]{32}"
_PART = r"[A-Za-z0-9_.-]{1,80}"
# One `files` entry (activity.md, Files; $defs/file_path); NFC is checked by redact() leaving it unchanged.
_FILE_PATH = r"(?![A-Za-z]:)(?!/)(?!(?:.*/)?\.\.(?:/|$))[^\x00-\x1f\x7f\\]{1,260}"
_MAX_FILES = 8
TAMPER_REASONS = ("link", "reparse", "hardlink", "foreign_owner", "not_regular", "not_dir", "swapped")
_MESSAGES = {
    "tampered": (
        "Some records of this run were changed outside orch. "
        "To be safe, orch does not show them. Nothing was deleted."
    ),
    "io": "The records of this run cannot be read right now. Try again later.",
    "missing": "There are no records for this run.",
    "pending": "Some records of this run are waiting to be written.",
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


class RecordBusy(RecordRefused):
    code = "busy"


class RecordUnavailable(RecordRefused):
    code = "not_available"

    def __init__(self, reason="io"):
        super().__init__(_MESSAGES[reason], reason=reason)


class RecordTampered(RecordRefused):
    code = "tampered"

    def __init__(self, reason):
        super().__init__(_MESSAGES["tampered"], reason=reason)


T = TypeVar("T")
Status = Literal["ok", "unavailable", "tampered"]


@dataclass(frozen=True)
class ReadResult(Generic[T]):
    status: Status
    value: T | None = None
    reason: str | None = None
    message: str | None = None
    skipped: int = 0
    pending: int = 0
    alert: dict | None = None

    def unwrap(self) -> T:
        if self.status != "ok":
            error = (
                RecordTampered(self.reason) if self.status == "tampered" else RecordUnavailable(self.reason)
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


def _write_new(ws, rel, payload):
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
            _verify_walk(directory)
            try:
                existing = _open(ws, rel, "read", _directory=directory)
            except RecordUnavailable as error:
                if error.reason != "missing":
                    raise
            else:
                _close(existing)
            os.replace(
                name,
                rel[-1] if _FD else directory.path / rel[-1],
                **({"src_dir_fd": directory.fd, "dst_dir_fd": directory.fd} if _FD else {}),
            )
        finally:
            os.close(fd)
            try:
                os.unlink(name, **kw)
            except FileNotFoundError:
                pass
    return True


def _size(ws, rel):
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
    # Preflight the entire tree before deleting anything; directory links refuse.
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


def _conflict(a, b):
    return (
        {a["via"], b["via"]} == {"hook", "log"}
        and a["outcome"] is not None
        and b["outcome"] is not None
        and any(a["outcome"][k] != b["outcome"][k] for k in ("ok", "error"))
    )


def _decision(previous, event):
    matching = [old for old in previous if _key(old) == _key(event)]
    if any(old["via"] == event["via"] for old in matching):
        return False
    if any(_conflict(old, event) for old in matching):
        event["conflict"] = True
        return True
    return not any(old["via"] == event["via"] or old["via"] == "hook" for old in matching)


def _dedupe(events, run):
    kept = []
    for event in events:
        if event["run"] != run or not _decision(kept, event):
            continue
        kept = [old for old in kept if not (_key(old) == _key(event) and not _conflict(old, event))]
        kept.append(event)
    return sorted(kept, key=lambda e: e["seq"])


def _parse(fd, run):
    events, skipped = [], 0
    for line in _read_bytes(fd).splitlines():
        try:
            event = json.loads(line)
            _validate(event)
            if event["run"] != run:
                raise RecordInvalid()
            events.append(event)
        except (ValueError, TypeError, UnicodeError, RecursionError, RecordInvalid):
            skipped += 1
    return events, skipped


def _read_run_strict(ws, run, fd):
    _check_fd(fd)
    raw = _read_bytes(fd)
    previous = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
            if isinstance(event, dict) and event.get("run") == run:
                outcome = event.get("outcome")
                if outcome is not None and not (
                    isinstance(outcome, dict) and {"ok", "error"} <= outcome.keys()
                ):
                    continue
                _key(event)
                previous.append(event)
        except (ValueError, TypeError, KeyError, RecursionError):
            continue
    return previous, len(raw.splitlines()), bool(raw and not raw.endswith(b"\n"))


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
)  # after the caller is proven to be in the run
UNPROVEN_REASONS = ("not_active", "other_run", "not_provable")  # before it is: never under a run id
_LOST_RUN_LINES = 50  # per run and day; the next one is a "trimmed" marker, then nothing
_LOST_FILE_BYTES = 1024**2  # per file; over it only a global "trimmed" marker is written


def _note(ws, name, run, reason, now, run_lines):
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
                    write = dict(run=run, reason=reason)
            note = dict(v=1, schema="orch.record-lost/1", at=stamp, **write)
            _write(fd, (_json(note) + "\n").encode())
        finally:
            _close(fd)
    except (RecordTampered, RecordUnavailable):
        pass  # a trace that cannot be stored is not worth failing the hook


def note_lost(ws, run, reason, *, now=None):
    """A hook entry of a PROVEN caller (live claim, inside its process tree) that could not be written leaves
    one short trace (orch.record-lost/1, no content): alerts/hook-lost-<day>.jsonl, at most one per run and
    reason per minute, at most 50 lines per run, then one "trimmed" line. Never raises."""
    if reason in LOST_REASONS and isinstance(run, str) and re.fullmatch(_RUN, run):
        _note(ws, "hook-lost", run, reason, now, _LOST_RUN_LINES)


def note_unattributed(ws, reason, *, now=None):
    """A hook entry whose caller could not be proven to be in the run: nothing under any run id (the claimed
    run is the caller's word), only the reason, in alerts/hook-lost-unattributed-<day>.jsonl, 1 per minute."""
    if reason in UNPROVEN_REASONS:
        _note(ws, "hook-lost-unattributed", None, reason, now, 0)


def _report(ws, error, target, run, seen_by):
    return ReadResult.from_error(error, ws, getattr(error, "target", target), run, seen_by)


def _pending_count(workspace, run):
    try:
        with _io("folder"):
            return len(_entries(workspace, ("pending", run)))
    except RecordUnavailable as error:
        if error.reason == "missing":
            return 0
        raise


def read_run(workspace, run, *, seen_by="reader") -> RunRead:
    _name(run, _RUN)
    pending = 0
    try:
        pending = _pending_count(workspace, run)
        fd = _open(workspace, ("runs", run + ".jsonl"), "read")
        try:
            events, skipped = _parse(fd, run)
        finally:
            _close(fd)
        pending = max(pending, _pending_count(workspace, run))
        return ReadResult(
            "ok",
            _dedupe(events, run),
            skipped=skipped,
            pending=pending,
            reason="pending" if pending else None,
            message=_MESSAGES["pending"] if pending else None,
        )
    except (RecordTampered, RecordUnavailable) as error:
        if isinstance(error, RecordUnavailable) and error.reason == "missing" and pending:
            return ReadResult("ok", [], reason="pending", message=_MESSAGES["pending"], pending=pending)
        return _report(workspace, error, "run", run, seen_by)


def _read_json(ws, rel):
    fd = _open(ws, rel, "read")
    try:
        try:
            return json.loads(_read_bytes(fd))
        except (ValueError, UnicodeError, RecursionError):
            raise RecordTampered("swapped") from None
    finally:
        _close(fd)


def read_detail(workspace, run, file_id):
    _name(run, _RUN)
    _name(file_id, _FILE)
    try:
        value = _read_json(workspace, ("detail", run, file_id + ".json"))
        if (
            not _DETAIL_VALIDATOR.is_valid(value)
            or value["run"] != run
            or detail_name(run, value["kind"], value["id"]) != file_id
        ):
            raise RecordTampered("swapped")
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
    try:
        names = _entries(workspace, ("runs",))
        return ReadResult("ok", sorted(n[:-6] for n in names if re.fullmatch(_RUN + r"\.jsonl", n)))
    except (RecordTampered, RecordUnavailable) as error:
        return _report(workspace, error, "folder", None, "reader")


@dataclass(frozen=True)
class _Detail:
    created: bool = False
    reason: str | None = None
    alert: dict | None = None


def _store_detail(ws, event, payload, previous):
    rel = tuple(event["detail"].split("/"))
    exists = False
    try:
        try:
            stored = _read_json(ws, rel)
            exists = True
        except RecordUnavailable as error:
            if error.reason != "missing":
                raise
        if exists:
            if not isinstance(stored, dict) or (stored.get("run"), stored.get("kind"), stored.get("id")) != (
                event["run"],
                event["kind"],
                event["id"],
            ):
                return _Detail(reason="collision")
            finished = any(
                old.get("detail") == event["detail"] and old.get("outcome") is not None for old in previous
            )
            if finished or event["outcome"] is None:
                return _Detail()
        _write_new(ws, rel, payload)
        return _Detail(created=not exists)
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
        line = _json(obj)
        if self.hider.hide_text(line) != line:
            raise RecordInvalid("This record cannot be hidden safely.")
        return line.encode("utf-8")

    def _prepare_detail(self, event, detail, hidden=0):
        if detail is None:
            return None
        try:
            before = _json(detail).count("[hidden: ")
            payload = self.hider.hide_json(detail)
            wrapped = dict(
                v=1,
                id=event["id"],
                run=event["run"],
                kind=event["kind"],
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
            files = [f for f in files if type(f) is str and re.fullmatch(_FILE_PATH, f)]
        before = _json(event).count("[hidden: ")
        event = self.hider.hide_json(event)
        hidden = max(0, _json(event).count("[hidden: ") - before)
        if files is not None:
            # A path that changes under the hider or the plain-text cleaner (which also makes NFC) is dropped,
            # never stored hidden.
            files = [f for f in files if self.hider.hide_text(f) == f and redact(f) == f]
            event["files"] = _files_in_budget(files[:_MAX_FILES])
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
                prepared["detail"] = f"detail/{run}/{detail_name(run, event['kind'], event['id'])}.json"
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
        if len(line) > 8192:
            raise RecordInvalid("The record entry is too large.")
        return line

    def _commit(self, event, payload, default_id, *, check_lock=lambda: None):
        run = event["run"]
        fd = _open(self.workspace, ("runs", run + ".jsonl"), "read_append", create_dirs=True)
        try:
            check_lock()
            previous, count, torn = _read_run_strict(self.workspace, run, fd)
            event = dict(event, seq=count + 1)
            if default_id:
                # a hook's default id has its own namespace: <run>:<seq> belongs to the collectors, so a hook
                # line can never take the id of a collector line that is still to come (dedupe would drop it)
                event["id"] = f"{'h_' if event.get('via') == 'hook' else ''}{run}:{event['seq']}"
                if payload is not None:
                    wrapped = json.loads(payload)
                    wrapped["id"] = event["id"]
                    payload = _json(wrapped).encode()
            if not _decision(previous, event):
                return None
            if payload is not None:
                event["detail"] = f"detail/{run}/{detail_name(run, event['kind'], event['id'])}.json"
            line = (_json(event) + "\n").encode()
            lost_line = (_json(dict(event, detail=None, detail_lost=True)) + "\n").encode()
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
                    line = lost_line
            try:
                check_lock()
                _write(fd, (b"\n" if torn else b"") + line)
            except (RecordUnavailable, RecordTampered):
                if stored.created:
                    try:
                        _unlink(self.workspace, tuple(event["detail"].split("/")))
                    except (RecordTampered, RecordUnavailable) as cleanup:
                        if isinstance(cleanup, RecordTampered):
                            _report(self.workspace, cleanup, "detail", run, "writer")
                raise
            return event
        finally:
            _close(fd)

    def _spool(self, event, payload, default_id):
        rel = ("pending", event["run"], f"{time.time_ns():020d}_{uuid.uuid4().hex}.json")
        try:
            fd = _open(self.workspace, rel, "create_excl", create_dirs=True)
            if fd is None:
                raise RecordUnavailable("io")
            try:
                _write(
                    fd,
                    _json(
                        dict(
                            event=event, payload=payload.decode() if payload else None, default_id=default_id
                        )
                    ).encode(),
                )
            finally:
                _close(fd)
        except (RecordTampered, RecordUnavailable) as error:
            _report(self.workspace, error, "folder", event["run"], "writer")
            raise  # the real cause (tampered / unavailable) stays visible to the caller
        result = dict(event, pending=True, seq=None)
        if default_id:
            result.pop("id", None)
        return result

    def _drain(self, run, *, check_lock=lambda: None):
        try:
            names = _entries(self.workspace, ("pending", run))
        except RecordUnavailable as error:
            if error.reason == "missing":
                return
            raise
        for name in sorted(names):
            check_lock()
            if not re.fullmatch(_PART, name) or name in (".", ".."):
                _alert(self.workspace, target="folder", run=run, reason="swapped", seen_by="writer")
                continue
            rel = ("pending", run, name)
            try:
                pending = _read_json(self.workspace, rel)
            except (RecordTampered, RecordUnavailable) as error:
                _report(self.workspace, error, "folder", run, "writer")
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
                _alert(self.workspace, target="folder", run=run, reason="swapped", seen_by="writer")
                continue
            self._commit(event, payload, pending["default_id"], check_lock=check_lock)
            _unlink(self.workspace, rel)


def _files_in_budget(files: list[str]) -> list[str]:
    """Each entry at most 512 serialized bytes, all together at most 2048: trailing entries are dropped."""
    sizes = [len(_json(f).encode()) + 1 for f in files]
    keep = 0
    while keep < len(files) and sizes[keep] <= 512 and sum(sizes[: keep + 1]) <= 2048:
        keep += 1
    return files[:keep]


def hook_entry_filter(line: dict) -> dict | None:
    if not isinstance(line, dict) or line.get("kind") not in (
        "step",
        "denial",
        "helper.start",
        "helper.end",
        "usage",
    ):
        raise RecordRefused("This kind of record is not allowed here.")
    return dict(line, via="hook")


def plan_retention(runs: list[dict], now: str, keep_days: int = 90, max_mb: int = 2048) -> dict:
    plan: dict[str, list[str]] = dict(fold_first=[], delete_detail=[], delete_run=[])
    cutoff = datetime.fromisoformat(now) - timedelta(days=keep_days)
    ended = sorted((r for r in runs if r["ended"]), key=lambda r: datetime.fromisoformat(r["ended"]))
    total = sum(r["detail_mb"] + r["file_mb"] for r in runs)
    for run in ended:
        if datetime.fromisoformat(run["ended"]) < cutoff:
            plan["delete_detail"].append(run["run"])
            plan["delete_run"].append(run["run"])
            total -= run["detail_mb"] + run["file_mb"]
    for field, size in (("delete_detail", "detail_mb"), ("delete_run", "file_mb")):
        for run in ended:
            if total <= max_mb:
                break
            if run["run"] not in plan[field] and run[size] > 0:
                plan[field].append(run["run"])
                total -= run[size]
    plan["fold_first"] = plan["delete_run"].copy()
    return plan


def delete_detail(workspace, runs, *, seen_by="cli"):
    rels = [("detail", _name(run, _RUN)) for run in runs]
    try:
        for rel in rels:
            _size(workspace, rel)
        for rel in rels:
            _rmtree(workspace, rel)
    except (RecordTampered, RecordUnavailable) as error:
        _report(workspace, error, "folder", rel[-1], seen_by)
        raise


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
        if read.status != "ok":
            failed(read)
            continue
        try:
            runs.append(
                dict(
                    run=run,
                    ended=_ended_run(run, read.value, now),
                    detail_mb=_size(workspace, ("detail", run)) / 1024**2,
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
                if read.status != "ok":
                    failed(read)
                    continue
                if read.pending:
                    failed(ReadResult("unavailable", reason="pending", message=_MESSAGES["pending"]))
                    continue
                ended_now = _ended_run(run, read.value, now)
                if not ended_now or ended_now != snapshots[run]:
                    continue
                # Check every deletion target before invoking the irreversible fold.
                for rel in (("pending", run), ("detail", run), ("jobs", run), ("runs", run + ".jsonl")):
                    check_lock()
                    _size(workspace, rel)
                check_lock()
                if _pending_count(workspace, run):
                    failed(ReadResult("unavailable", reason="pending", message=_MESSAGES["pending"]))
                    continue
                fold(run, read.value)
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
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://orch.severin.io/contracts/activity.schema.json",
    "title": "orch activity event v1 (orch.activity/1, one line of .orch/record/runs/<run>.jsonl)",
    "description": "One thing an agent run did, the same for every agent tool. See activity.md. "
    "Written only by the core record writer, which hides exact key values first (fail "
    "closed). Readers skip unknown kinds and keep unknown fields. text and every "
    "string are plain text (shown with textContent).",
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
            "description": "The agent tool's own tool-call id when the source has one, "
            "else '<run>:<seq>' (activity.md, Ids).",
        },
        "seq": {
            "type": "integer",
            "minimum": 1,
            "description": "Position in this run file, +1 per written line, set by the single writer.",
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
            "description": "Who started this agent: null for main, else main or another helper.",
        },
        "at": {"$ref": "#/$defs/time"},
        "ticket": {"type": "string", "pattern": "^t_[a-z0-9]{6,16}$"},
        "harness": {
            "type": "string",
            "pattern": "^[a-z][a-z0-9-]{0,31}$",
            "description": "Adapter name of the run (agent-adapter.schema.json key "
            "or [agents.<name>] entry); 'generic' for a user entry; "
            "'none' for a job run without an agent.",
        },
        "via": {
            "enum": ["hook", "log", "broker", "job", "core"],
            "description": "Who wrote it: hook = the tool's own hook (instant), log = "
            "a collector reading the tool's log or stream, broker = "
            "orch secret, job = orch job / $ORCH_EVENTS, core = orch "
            "itself (ticket changes, run state, take-over).",
        },
        "kind": {"$ref": "#/$defs/kind"},
        "text": {
            "type": "string",
            "maxLength": 500,
            "pattern": "^[^\\u0000-\\u001f\\u007f]*$",
            "description": "Short display line, one line, key values hidden.",
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
                            "description": "Shown as Skill, Tool, "
                            "Connection, Key, "
                            "Helper (wording: 'MCP' "
                            "only under Details).",
                        },
                        "name": {"$ref": "#/$defs/name"},
                        "action": {
                            "oneOf": [{"type": "null"}, {"$ref": "#/$defs/name"}],
                            "description": "Tool of a connection "
                            "(read_file), key "
                            "delivery (env, file, "
                            "exec, get), or "
                            "null.",
                        },
                        "source": {
                            "enum": ["harness", "admin", "workspace", "builtin", "marketplace"],
                            "description": "harness = the agent "
                            "tool's own settings, "
                            "admin = shared by "
                            "the admin, workspace "
                            "= this workspace, "
                            "builtin = part of "
                            "orch or of the agent "
                            "tool, marketplace = "
                            "an installed "
                            "add-on.",
                        },
                        "version": {
                            "oneOf": [{"type": "null"}, {"$ref": "#/$defs/version"}],
                            "description": "Content hash of the "
                            "skill or connection "
                            "config at the time "
                            "of use "
                            "(inventory.md).",
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
                            "description": "null = finished, result unknown to the source.",
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
            "description": "null = started, not finished yet. A later line with "
            "the same id and kind carries the outcome (activity.md, "
            "Dedupe).",
        },
        "detail": {
            "oneOf": [
                {"type": "null"},
                {"type": "string", "pattern": "^detail/r_[a-z0-9_]{6,32}/[0-9a-f]{32}\\.json$"},
            ],
            "description": "Full payload file, relative to .orch/record/; null = details not available.",
        },
        "coverage": {
            "enum": ["full", "partial"],
            "description": "full = the source saw everything of this step; "
            "partial = something is missing (no chat text, cut "
            "output, no helper).",
        },
        "data": {
            "type": "object",
            "description": "Per-kind fields (activity.md, Kinds). Unknown fields are kept.",
        },
        "detail_lost": {
            "type": "boolean",
            "description": "true = a full payload existed but could not be "
            "stored (name collision with another event's file, "
            "write problem, too large); the line is kept with "
            "detail null (activity.md, Detail files).",
        },
        "conflict": {
            "type": "boolean",
            "description": "Hook and log finished outcomes disagree; both lines are kept.",
        },
        "files": {"$ref": "#/$defs/files"},
    },
    "allOf": [
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
                    "used": {"type": "object", "properties": {"kind": {"enum": ["skill", "tool", "mcp"]}}},
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
                                "properties": {"check": {"type": "string", "pattern": "^c[0-9]{1,4}$"}},
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
            "then": {"properties": {"outcome": {"type": "object", "properties": {"ok": {"const": False}}}}},
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
                                        "description": "Base "
                                        "name "
                                        "of "
                                        "the "
                                        "program "
                                        "the "
                                        "key "
                                        "was "
                                        "handed "
                                        "to; "
                                        "never "
                                        "its "
                                        "arguments.",
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
                                        "description": "human:<name> from the proof, or reset (no proof).",
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
                                    "state": {"enum": ["running", "ok", "failed", "cancelled", "lost"]},
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
                                        "description": "How "
                                        "many "
                                        "key "
                                        "presses "
                                        "were "
                                        "sent. "
                                        "The "
                                        "typed "
                                        "text "
                                        "is "
                                        "never "
                                        "stored.",
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
    "$defs": {
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
            "description": "Only on kind step: the workspace files or folders the step named, display "
            "only, never used for access decisions (activity.md, Files).",
        },
        "file_path": {
            "type": "string",
            "minLength": 1,
            "maxLength": 260,
            "pattern": "^(?![A-Za-z]:)(?!/)(?!(?:.*/)?\\.\\.(?:/|$))[^\\u0000-\\u001f\\u007f\\\\]+$",
            "description": "Workspace-relative POSIX path: no leading /, no .. segment, no backslash or "
            "drive letter, no control character, NFC (the writer checks NFC).",
        },
        "detail_file": {
            "type": "object",
            "required": ["v", "id", "run", "kind", "input", "output", "truncated", "hidden"],
            "additionalProperties": False,
            "description": "One file .orch/record/detail/<run>/<file name>.json: "
            "the full payload of one event, key values hidden. The "
            "file name is lowercase hex only (activity.md, Detail "
            "files); id and kind are stored here so a reader can "
            "verify the file belongs to the event.",
            "properties": {
                "v": {"const": 1},
                "id": {"$ref": "#/$defs/event_id"},
                "run": {"$ref": "#/$defs/run"},
                "kind": {"$ref": "#/$defs/kind"},
                "input": {"description": "What went in (tool input, prompt, command), any JSON."},
                "output": {"description": "What came out (tool result, chat text), any JSON."},
                "truncated": {"type": "boolean", "description": "true = cut at the 1 MB per-file cap."},
                "hidden": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "How many key values were hidden in this file.",
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
                    ]
                },
                "seen_by": {"enum": ["writer", "reader", "retention", "cli"]},
                "message": {
                    "const": "Some records of this run were "
                    "changed outside orch. To be safe, "
                    "orch does not show them. Nothing "
                    "was deleted."
                },
            },
        },
        "read_status": {
            "type": "object",
            "additionalProperties": False,
            "required": ["run", "status", "reason", "message"],
            "properties": {
                "pending": {"type": "integer", "minimum": 0},
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
_DETAIL_VALIDATOR = Draft202012Validator(
    {"$ref": "#/$defs/detail_file", "$defs": _SCHEMA["$defs"]}, format_checker=FormatChecker()
)
_META_VALIDATOR = Draft202012Validator(
    {"$ref": "#/$defs/record_meta", "$defs": _SCHEMA["$defs"]}, format_checker=FormatChecker()
)
