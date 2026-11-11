"""The core write gate `.orch/run/sync.gate`: held by the sync step while it applies a merge to the live tree.

Lock order is GATE -> ticket lock. A writer of synced files waits for the gate BEFORE it takes the ticket lock
and checks again after taking it (tickets._locked); the sync step, while holding the gate, takes each ticket's
lock for every file it writes (its own thread passes the gate). So a writer is either finished before the step
touches the file, or refused/waiting: nothing is written into a merge.

A gate is stale only when its holder is verifiably not a live sync step: the process is gone, the pid has
another start time, the pid is not an orch process, or no step record (`.orch/run/sync/step-<id>.json`,
written by `hold` for the same pid) backs it; an unreadable or garbled gate file is stale too (a live holder
publishes the file whole, so it never shows a partial one; a very recent unreadable one still counts as live,
to be safe with older publishers). Never a timer.

The sync step must do all its writes on the thread that holds the gate: a worker thread is another thread and
is refused like any writer.

One protocol, no hard links needed (FAT/exFAT, some SMB): every change of the gate file (publish, takeover of
a stale one, release) happens under the gate lock `.orch/run/sync.gate.lock`, a directory. The lock is created
whole: a temp directory holding one owner file (`owner-<random>`, our pid, start time, nonce and thread) is
renamed into place, and a directory rename never replaces a non-empty directory, so it fails while another
lock stands. Under the lock the gate is checked and changed: published (a fully written temp file renamed in
when no gate is there), taken over (removed only when it is still the very file judged stale: same bytes and
file identity) or released (removed only when it still carries our identity). Nothing is ever renamed away and
put back. A lock whose owner is verifiably gone is broken by removing its owner file by its unique name (so a
newer lock is never touched), then the empty directory (rmdir removes only an empty one). When the lock
cannot be taken (busy, or the filesystem cannot rename directories) the hold is refused: no sync, never two
holders. The holder checks before each write batch (tickets.sync_apply) that the gate still carries its own
identity (ensure_held); a thread holding no gate there is refused. Step records of holders that are gone are
removed.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import subprocess
import threading
import time
from pathlib import Path

from orch import procs
from orch.errors import Refused

WAIT_SECONDS = 30.0  # a writer waits this long, then says "busy" (it never breaks a live gate)
POLL_SECONDS = 0.02
FRESH_SECONDS = 2.0  # an unreadable gate younger than this may be a holder mid-write (older publishers)
REREAD_SECONDS = 0.05  # an unreadable gate is read once more after this, then counts as stale
REPLACE_TRIES = 10  # Windows: a file open elsewhere refuses os.replace; retried inside the gate
REPLACE_DELAY = 0.2
TAKEOVER_WAIT = 2.0  # how long a gate change waits for another one's short critical section (the gate lock)
BACKOFF_MAX = 0.2  # the longest pause between two tries for the gate lock or the gate

_NONCE = secrets.token_hex(8)  # per process (a forked child inherits it, but has another pid)
_STEP_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_STEP_FILE_RE = re.compile(r"step-[A-Za-z0-9_.-]{1,64}\.json")
_OWNER_RE = re.compile(r"owner-[0-9a-f]{16}")
_local = threading.local()  # the gates this thread holds: (resolved gate path, gate text)


def gate_path(root: Path) -> Path:
    return root / ".orch" / "run" / "sync.gate"


def lock_path(root: Path) -> Path:
    """The gate lock: a directory with one owner file. Every change of the gate file happens under it."""
    return root / ".orch" / "run" / "sync.gate.lock"


def step_path(root: Path, step_id: str) -> Path:
    return root / ".orch" / "run" / "sync" / f"step-{step_id}.json"


def _snapshot(p: Path) -> tuple[bytes, tuple] | None:
    """The file's bytes and identity (device, inode, mtime, size); None when it is missing or unreadable."""
    try:
        with open(p, "rb") as f:
            st = os.fstat(f.fileno())
            data = f.read()
    except OSError:
        return None
    return data, (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size)


def _parse(data: bytes) -> dict | None:
    try:
        rec = json.loads(data.decode("utf-8"))
    except ValueError:
        return None
    return rec if isinstance(rec, dict) else None


def _read_file(p: Path) -> dict | None:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # Windows: PermissionError during a replace is an OSError too
        return None
    return data if isinstance(data, dict) else None


def _read(root: Path) -> dict | None:
    """The gate record, read once more after a short pause when it is unreadable. None = unreadable."""
    rec = _read_file(gate_path(root))
    if rec is None and gate_path(root).exists():
        time.sleep(REREAD_SECONDS)
        rec = _read_file(gate_path(root))
    return rec


def _is_me(rec: dict) -> bool:
    """This very thread of this process holds it (not just this process: other threads must not pass)."""
    return (
        rec.get("pid") == os.getpid()
        and rec.get("nonce") == _NONCE
        and rec.get("thread") == threading.get_ident()
    )


def _looks_like_orch(pid: int) -> bool:
    if os.name == "nt":
        return True  # no cheap command line here: the step record and the start time have to do
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:  # Linux: no ps needed
            raw = f.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        if raw:
            return _cmd_is_orch(raw)
    except OSError:
        pass
    try:
        r = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
    except Exception:
        return True  # cannot tell: do not call a holder stale on a guess about ps
    cmd = r.stdout.strip()
    return _cmd_is_orch(cmd) if cmd else True


def _cmd_is_orch(cmd: str) -> bool:
    toks = cmd.split()
    names = {"orch", "orch.exe"}
    if any(re.split(r"[\\/]", t)[-1] in names for t in toks):
        return True  # the orch program itself (tool script or pipx/uv shim)
    return any(a == "-m" and b.split(".")[0] == "orch" for a, b in zip(toks, toks[1:], strict=False))


def _stale(root: Path, rec: dict) -> bool:
    """True when no live sync step stands behind this record."""
    pid, sid = rec.get("pid"), rec.get("step_id")
    if not isinstance(pid, int) or not isinstance(sid, str) or not _STEP_RE.fullmatch(sid):
        return True
    start = rec.get("start_time")
    if not isinstance(start, str) or not start:
        return True
    if procs.owner_dead(f"{pid} {start}"):
        return True
    step = _read_file(step_path(root, sid))
    if step is None or step.get("pid") != pid:
        return True  # a gate with no step record is a fake or a leftover
    return not _looks_like_orch(pid)


def _fresh_unreadable(root: Path) -> bool:
    try:
        return time.time() - gate_path(root).stat().st_mtime < FRESH_SECONDS
    except OSError:
        return False


def live_holder(root: Path) -> dict | None:
    """The gate record when a live sync step of another thread/process holds it, else None."""
    if not gate_path(root).exists():
        return None
    rec = _read(root)
    if rec is None:
        return {"unreadable": True} if _fresh_unreadable(root) else None
    if _is_me(rec) or _stale(root, rec):
        return None
    return rec


def wait_clear(root: Path, what: str = "this", *, wait: float | None = None) -> None:
    """Return when no live gate is held; else after `wait` seconds raise Refused (busy). Writes nothing."""
    end = time.monotonic() + (WAIT_SECONDS if wait is None else wait)
    while live_holder(root) is not None:
        if time.monotonic() > end:
            raise busy(what)
        time.sleep(POLL_SECONDS)


def busy(what: str) -> Refused:
    return Refused(f"orch is syncing, so {what} is busy. Try again in a moment.")


def _write_whole(p: Path, text: str) -> None:
    fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def _publish(root: Path, text: str) -> bool:
    """Create the gate with its whole content; False when one exists. Under the gate lock (every gate change
    takes it, so the place stays empty between the check and the rename): write and fsync a temp file, then
    rename it in. No reader ever sees a half or empty gate; no hard links needed. Refused when the gate lock
    cannot be taken or the rename fails: no sync rather than a gate we are not sure of."""
    p = gate_path(root)
    with _gate_lock(root) as ok:
        if not ok:
            raise Refused("orch could not take the sync gate. Try again in a moment.")
        if os.path.lexists(p):
            return False
        tmp = p.with_name(f"sync.gate.{secrets.token_hex(4)}.tmp")
        try:
            _write_whole(tmp, text)
            os.rename(tmp, p)  # the place is empty (checked under the lock): nothing is replaced
        except OSError as e:
            raise Refused("orch could not take the sync gate. Try again in a moment.") from e
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
        return True


def _release(root: Path, text: str) -> None:
    """Remove the gate only while it still carries our identity, under the gate lock like every gate change
    (so a release never races a takeover). When the lock stays busy the gate is left: without its step record
    it is stale and taken over later."""
    p = gate_path(root)
    with _gate_lock(root) as ok:
        if not ok:
            return
        with contextlib.suppress(OSError):
            if p.read_text(encoding="utf-8") == text:
                procs.unlink(p)


@contextlib.contextmanager
def hold(root: Path, step_id: str = "sync"):
    """The sync step's gate. Refused (busy) when another live step holds it; a stale gate is taken over.
    The step record has a name of its own per hold (id + random suffix), written before the gate is published
    (a gate without its record would look stale) and removed only by the hold that wrote it, so a refused
    second hold can never touch the live step's record."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,50}", step_id):
        raise Refused("A sync step id has 1 to 50 letters, digits, dots, dashes or underscores.")
    p = gate_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    me = os.getpid()
    sid = f"{step_id}-{secrets.token_hex(4)}"
    sp = step_path(root, sid)
    sp.parent.mkdir(parents=True, exist_ok=True)
    start = procs.pid_started(me) or "-"
    step_text = json.dumps({"pid": me, "step_id": sid, "start_time": start})
    text = json.dumps(
        {
            "pid": me,
            "start_time": start,
            "nonce": _NONCE,
            "thread": threading.get_ident(),
            "step_id": sid,
        }
    )
    stmp = sp.with_name(f"{sp.name}.tmp")
    stmp.write_text(step_text, encoding="utf-8")
    os.replace(stmp, sp)  # atomic: a reader never sees half a record
    try:
        for i in range(5):
            if _publish(root, text):
                break
            seen, live = _judge(root)
            if live:
                raise Refused("orch is already syncing. Try again in a moment.")
            if seen is not None and not _take_stale(root, seen):
                time.sleep(min(POLL_SECONDS * 2**i, BACKOFF_MAX))  # e.g. Windows: the gate is open elsewhere
        else:
            raise Refused("orch could not take the sync gate. Try again in a moment.")
        entry = (os.path.realpath(p), text)
        if not hasattr(_local, "held"):
            _local.held = []
        held = _local.held
        held.append(entry)
        with contextlib.suppress(OSError):
            _clean_step_records(root)
        try:
            yield
        finally:
            held.remove(entry)
            _release(root, text)  # only a gate that is ours
    finally:
        with contextlib.suppress(OSError):
            if sp.read_text(encoding="utf-8") == step_text:
                sp.unlink()


def _same_path(a: str | Path, b: str | Path) -> bool:
    """One file under two spellings (symlinked root, case-insensitive alias): realpath, then samefile."""
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    try:  # the gate may be gone (that is ensure_held's finding): compare the directories holding it
        return Path(a).name == Path(b).name and os.path.samefile(Path(a).parent, Path(b).parent)
    except OSError:
        return False


def _held_texts(root: Path) -> list[str]:
    """The gate texts this thread published for `root` and still holds."""
    p = gate_path(root)
    return [text for gp, text in getattr(_local, "held", ()) if _same_path(gp, p)]


def ensure_held(root: Path) -> None:
    """For the gate's holder, before each write batch: Refused when this thread holds no gate for `root`
    (sync_apply is only for the holder) or the gate no longer carries this hold's identity (taken over or
    removed meanwhile). Fails closed."""
    texts = _held_texts(root)
    if not texts:
        raise Refused("orch is not holding the sync gate for this write. Try again in a moment.")
    try:
        ok = gate_path(root).read_text(encoding="utf-8") in texts
    except OSError:
        ok = False
    if not ok:
        raise Refused("orch lost the sync gate while syncing. Try again in a moment.")


def _judge(root: Path) -> tuple[tuple[bytes, tuple] | None, bool]:
    """(snapshot of the gate, whether a live holder stands behind it). An unreadable gate is read once more
    after a short pause. Snapshot None = no gate right now. A gate of this very thread counts as live while
    this thread still holds it (a nested hold is refused); a leftover one is judged like any other."""
    p = gate_path(root)
    seen = _snapshot(p)
    if seen is not None and _parse(seen[0]) is None:
        time.sleep(REREAD_SECONDS)
        seen = _snapshot(p)
    if seen is None:
        return None, False
    rec = _parse(seen[0])
    if rec is None:  # a very recent unreadable one may be an older publisher mid-write
        return seen, time.time() - seen[1][2] / 1e9 < FRESH_SECONDS
    if _is_me(rec) and seen[0].decode("utf-8", "replace") in _held_texts(root):
        return seen, True
    return seen, not _stale(root, rec)


def _take_stale(root: Path, seen: tuple[bytes, tuple]) -> bool:
    """Remove the gate judged stale, compare-and-swap: under the gate lock (which every gate change takes),
    re-read the gate and remove it only when it is still exactly what was judged (bytes and file identity).
    A gate published or released meanwhile is never touched; nothing is moved away and put back."""
    p = gate_path(root)
    with _gate_lock(root) as ok:
        if not ok or _snapshot(p) != seen:
            return False  # busy, gone, or another gate now (maybe a live holder's): give up this attempt
        try:
            procs.unlink(p)  # Windows: waits out a reader holding it open
        except OSError:
            return False
        return True


def _lock_try(lk: Path, token: str) -> str | None:
    """Create the gate lock whole: a temp directory with the owner file written and fsynced, renamed into
    place. A directory rename never replaces a non-empty directory (POSIX: ENOTEMPTY/EEXIST; Windows: any
    existing target), so this fails while another lock stands. Returns the owner file's name, or None (busy,
    or this filesystem refused: the caller ends up refused, never two holders)."""
    name = f"owner-{secrets.token_hex(8)}"
    tmp = lk.with_name(f"{lk.name}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.mkdir()
    except OSError:
        return None
    try:
        _write_whole(tmp / name, token)
        os.rename(tmp, lk)
        return name
    except OSError:
        with contextlib.suppress(OSError):
            (tmp / name).unlink()
        with contextlib.suppress(OSError):
            tmp.rmdir()
        return None


def _lock_owner(lk: Path) -> str | None:
    """The owner file name of the lock judged gone, else None: the lock is missing, live, or not something we
    can judge (left alone: fail closed). An empty lock directory (its owner file already removed by a release
    or a break) is removed here; rmdir removes only an empty directory, so never a newer lock."""
    try:
        names = os.listdir(lk)
    except OSError:
        return None
    if not names:
        with contextlib.suppress(OSError):
            os.rmdir(lk)
        return None
    if len(names) != 1 or not _OWNER_RE.fullmatch(names[0]):
        return None
    try:
        owner = (lk / names[0]).read_text(encoding="utf-8")
    except OSError:
        return None
    return names[0] if owner.strip() and procs.owner_dead(owner) else None


def _break(lk: Path, name: str) -> None:
    """Break the lock whose owner file `name` was judged gone: remove that file by its unique name (a newer
    lock has another one, so it is never touched), then the directory if it is empty now."""
    with contextlib.suppress(OSError):
        procs.unlink(lk / name)
    with contextlib.suppress(OSError):
        os.rmdir(lk)


@contextlib.contextmanager
def _gate_lock(root: Path):
    """The gate lock around every gate change (yields False when it stays busy for TAKEOVER_WAIT). Retries
    back off and always sleep, also when a break did not help."""
    lk = lock_path(root)
    lk.parent.mkdir(parents=True, exist_ok=True)
    token = f"{procs.own_token()} {_NONCE} {threading.get_ident()}"
    end = time.monotonic() + TAKEOVER_WAIT
    delay = POLL_SECONDS / 4
    while (name := _lock_try(lk, token)) is None:
        dead = _lock_owner(lk)
        if dead is not None:
            _break(lk, dead)
        if time.monotonic() > end:
            yield False
            return
        time.sleep(delay)
        delay = min(delay * 2, BACKOFF_MAX)
    try:
        yield True
    finally:
        _break(lk, name)  # our own owner file, then the directory


def _clean_step_records(root: Path) -> None:
    """Remove step records (`step-*.json`) whose owner process is verifiably gone: a crashed hold's
    leftovers. Each by its exact path, and only when it still holds what was judged."""
    d = step_path(root, "x").parent
    for sp in d.iterdir():
        if not _STEP_FILE_RE.fullmatch(sp.name):
            continue
        seen = _snapshot(sp)
        rec = _parse(seen[0]) if seen is not None else None
        pid = rec.get("pid") if rec is not None else None
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            continue  # not a record we can judge: left alone
        start = rec.get("start_time")
        if not procs.owner_dead(f"{pid} {start}" if isinstance(start, str) and start else str(pid)):
            continue
        with contextlib.suppress(OSError):
            if _snapshot(sp) == seen:
                sp.unlink()


def clear_stale(root: Path) -> bool:
    """For a doctor-style repair: remove a gate no live sync step stands behind. True when one was removed."""
    seen, live = _judge(root)
    return seen is not None and not live and _take_stale(root, seen)


def replace(src, dst) -> None:
    """os.replace for the sync step: on Windows a file open elsewhere refuses it, so retry 10x / 200 ms,
    then raise (the caller skips the path and retries next tick)."""
    for i in range(REPLACE_TRIES):
        try:
            return os.replace(src, dst)
        except PermissionError:
            if os.name != "nt" or i == REPLACE_TRIES - 1:
                raise
            time.sleep(REPLACE_DELAY)
