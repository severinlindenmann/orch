"""The always-on debug log `orch.diag/1` (contracts/diag.md): one structure-only event per line in
.orch/diag/<YYYY-MM-DD>.<src>.<part>.jsonl, local, git-ignored, 7 days / 200 MB per workspace.

Rules enforced here and nowhere else:
- it never raises into the caller: a failed write is counted, a later `diag.dropped` line says how many;
- structure only: kv values are scalars (or short lists of them), strings are cut at 300, then pass the Hider;
  a key that names a secret hides its value; no frame locals and no exception message are ever captured;
- the folder is never reached through a symlink (0700 folder, 0600 files, O_NOFOLLOW);
- off (`orch config set diag.enabled off`) = no new lines, existing files stay.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from orch import __version__

SCHEMA = "orch.diag/1"
KEEP_DAYS = 7
MAX_TOTAL_BYTES = 200 * 1024 * 1024  # per workspace
FILE_MAX = 8 * 1024 * 1024  # one part; the next write opens part n+1
SRC_DAY_BYTES = 60 * 1024 * 1024  # per source and day
SRC_EVENTS_PER_MIN = 1200  # per source and process
LINE_MAX = 4096
STR_MAX = 300
LIST_MAX = 20
KV_MAX = 24
FRAMES_MAX = 12
PRUNE_EVERY = 60.0  # seconds
LEVELS = ("debug", "info", "warn", "error")

_EV = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_SRC = re.compile(r"^[a-z][a-z0-9_-]{0,23}$")
_SECRET_KEY = re.compile(
    r"secret|token|passw|passphrase|key|auth|cookie|credential|bearer|signature|proof", re.I
)
_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")
_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.([a-z][a-z0-9_-]{0,23})\.(\d+)\.jsonl$")

_PROC_START = int(time.time() * 1000)
_lock = threading.Lock()
_busy = threading.local()
_state = {"root": None, "src": "cli", "seq": 0, "last_prune": 0.0}
_dropped: dict[str, int] = {}
_rate: dict[tuple[str, int], int] = {}
_enabled_cache: dict[str, tuple[float, bool]] = {}
_hider_cache: dict[str, tuple[float, object]] = {}
_ws_cache: dict[str, str | None] = {}
_trace: ContextVar[tuple[str, str, str | None] | None] = ContextVar("orch_diag_trace", default=None)


# --- trace (W3C traceparent) ----------------------------------------


def parse_traceparent(value) -> tuple[str, str] | None:
    """(trace_id, span_id) of a valid traceparent header/env value, else None (all-zero ids are invalid)."""
    m = _TRACEPARENT.fullmatch(value.strip().lower()) if isinstance(value, str) else None
    if not m or set(m[1]) == {"0"} or set(m[2]) == {"0"}:
        return None
    return m[1], m[2]


def new_trace(incoming: str | None = None) -> str:
    """Start the trace of one CLI invocation or one dashboard request (a valid `incoming` one is joined:
    its span becomes our parent). Returns the traceparent to hand on."""
    got = parse_traceparent(incoming)
    trace_id, parent = got if got else (secrets.token_hex(16), None)
    span = secrets.token_hex(8)
    _trace.set((trace_id, span, parent))
    return f"00-{trace_id}-{span}-01"


def _current() -> tuple[str, str, str | None]:
    cur = _trace.get()
    if cur is None:
        new_trace(os.environ.get("TRACEPARENT"))
        cur = _trace.get()
    return cur  # type: ignore[return-value]


def traceparent() -> str:
    trace_id, span, _ = _current()
    return f"00-{trace_id}-{span}-01"


def trace_env() -> dict:
    """{"TRACEPARENT": ...} to merge into a child's environment; {} if it cannot be made (never raises)."""
    try:
        return {"TRACEPARENT": traceparent()}
    except Exception:  # noqa: BLE001
        return {}


def child_env(env: dict | None = None) -> dict:
    """`env` (default: this process's) with TRACEPARENT set, for a child process."""
    out = dict(os.environ if env is None else env)
    with contextlib.suppress(Exception):
        out["TRACEPARENT"] = traceparent()
    return out


# --- setup ----------------------------------------------------------


def bind(root: Path | None, src: str = "cli") -> None:
    """Tell the log which workspace this process writes to and who it is (cli, dashboard, run, ...)."""
    _state["root"] = Path(root) if root is not None else None
    _state["src"] = src if _SRC.fullmatch(src) else "cli"


def enabled(root: Path | None) -> bool:
    """The setting (default on), cached for 5 s so a hot path never reads the file each time."""
    if root is None:
        return False
    key = str(root)
    now = time.monotonic()
    hit = _enabled_cache.get(key)
    if hit and now - hit[0] < 5.0:
        return hit[1]
    try:
        from orch import config

        value = config.diag_enabled(root)
    except Exception:  # noqa: BLE001 - an unreadable setting never stops the program
        value = True
    _enabled_cache[key] = (now, value)
    return value


def forget_settings() -> None:
    _enabled_cache.clear()


def read_events(root: Path) -> list[dict]:
    """Every event of this workspace's debug log, oldest file first (read-only; bad lines are skipped)."""
    d = root / ".orch" / "diag"
    out: list[dict] = []
    if d.is_symlink() or not d.is_dir():
        return out
    for p in sorted(d.iterdir(), key=lambda p: p.name):
        if not _FILE.fullmatch(p.name) or p.is_symlink() or not p.is_file():
            continue
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            with contextlib.suppress(ValueError):
                out.append(json.loads(ln))
    return out


def dropped_count(reason: str | None = None) -> int:
    with _lock:
        return sum(v for k, v in _dropped.items() if reason is None or k == reason)


def _drop(reason: str) -> None:
    with _lock:
        _dropped[reason] = _dropped.get(reason, 0) + 1


# --- content rules --------------------------------------------------


def _hider(root: Path):
    """The registered hider, else one from this workspace's keys (cached 30 s); None: cannot hide."""
    from orch import hider

    try:
        return hider.current_hider().hide_text
    except hider.NoHiderError:
        pass
    key = str(root)
    now = time.monotonic()
    hit = _hider_cache.get(key)
    if hit and now - hit[0] < 30.0:
        return hit[1]
    try:
        from orch import addons, keystore

        addons.home()  # an orch home that is refused (strict, untrusted) means: write nothing, create nothing
        h = hider.Hider(keystore.all_needles(root)).hide_text
    except Exception:  # noqa: BLE001
        h = None
    _hider_cache[key] = (now, h)
    return h


def _scalar(value, hide):
    if value is None or isinstance(value, (bool, int)):
        return value, True
    if isinstance(value, float):
        return (value, True) if value == value and abs(value) != float("inf") else (None, True)
    if isinstance(value, str):
        return hide(value)[:STR_MAX], True  # hide the whole string first: a cut could split a key value
    return None, False


def _clean_kv(kv: dict, hide) -> dict:
    out = {}
    for key, value in kv.items():
        if len(out) >= KV_MAX:
            break
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            continue
        if _SECRET_KEY.search(key) and isinstance(value, (str, list, tuple)):
            out[key] = "[hidden]"
        elif isinstance(value, (list, tuple)):
            items = [_scalar(v, hide) for v in list(value)[:LIST_MAX]]
            if all(ok for _, ok in items):
                out[key] = [v for v, _ in items]
        else:
            v, ok = _scalar(value, hide)
            if ok:  # a dict, an object, bytes: not structure, left out
                out[key] = v
    return out


def _err(exc: BaseException) -> dict:
    """{type, fingerprint, frames}: the type's name and the code places; never the message, never locals."""
    frames = []
    for fs in traceback.extract_tb(exc.__traceback__)[-FRAMES_MAX:]:
        mod = Path(fs.filename).stem
        frames.append(f"{mod}:{fs.name}:{fs.lineno}")
    kind = type(exc).__name__
    fp = hashlib.sha256(("\0".join([kind, *[f.rsplit(":", 1)[0] for f in frames]])).encode()).hexdigest()[:16]
    return {"type": kind, "fingerprint": fp, "frames": frames}


def _workspace_id(root: Path) -> str | None:
    key = str(root)
    if key not in _ws_cache:
        try:
            from orch import addons

            _ws_cache[key] = addons.workspace_id(root)
        except Exception:  # noqa: BLE001
            _ws_cache[key] = None
    return _ws_cache[key]


# --- the writer -----------------------------------------------------


def _folder(root: Path) -> Path | None:
    """.orch/diag, created 0700, or None when it (or .orch) is a link or cannot be made."""
    orch = root / ".orch"
    d = orch / "diag"
    if orch.is_symlink() or d.is_symlink():
        return None
    if not orch.is_dir():
        return None
    d.mkdir(mode=0o700, exist_ok=True)
    if hasattr(os, "chmod") and os.name == "posix":
        with contextlib.suppress(OSError):
            os.chmod(d, 0o700)
    return d if d.is_dir() and not d.is_symlink() else None


def _append(d: Path, src: str, day: str, data: bytes) -> bool:
    """Append one line to the newest part of today's file of `src` (a full part starts the next)."""
    part = 1
    for p in d.glob(f"{day}.{src}.*.jsonl"):
        m = _FILE.fullmatch(p.name)
        if m and not p.is_symlink():
            part = max(part, int(m[3]))
    total_day = 0
    for _ in range(2):
        path = d / f"{day}.{src}.{part}.jsonl"
        flags = (
            os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        )
        fd = os.open(path, flags, 0o600)
        try:
            size = os.fstat(fd).st_size
            if size + len(data) > FILE_MAX and size > 0:
                part += 1
                continue
            total_day = size + (part - 1) * FILE_MAX
            if total_day + len(data) > SRC_DAY_BYTES:
                _drop("source_bytes")
                return False
            os.write(fd, data)
            return True
        finally:
            os.close(fd)
    return False


def prune(root: Path) -> None:
    """Retention: files older than KEEP_DAYS go, then the oldest until the folder is under MAX_TOTAL_BYTES."""
    d = root / ".orch" / "diag"
    if d.is_symlink() or not d.is_dir():
        return
    cutoff = datetime.fromtimestamp(time.time() - KEEP_DAYS * 86400, UTC).strftime("%Y-%m-%d")
    files = []
    for p in d.iterdir():
        m = _FILE.fullmatch(p.name)
        if not m or p.is_symlink() or not p.is_file():
            continue
        if m[1] < cutoff:
            with contextlib.suppress(OSError):
                p.unlink()
            continue
        with contextlib.suppress(OSError):
            files.append((m[1], int(m[3]), p, p.stat().st_size))
    files.sort(key=lambda f: (f[0], f[1], f[2].name))
    total = sum(f[3] for f in files)
    for _day, _part, p, size in files:
        if total <= MAX_TOTAL_BYTES:
            break
        with contextlib.suppress(OSError):
            p.unlink()
            total -= size


def _emit(
    root: Path, ev: str, lvl: str, kv: dict, *, err: BaseException | None, dur_ms: int | None, depth: int
) -> None:
    if not enabled(root):
        return
    if not _EV.fullmatch(ev) or lvl not in LEVELS:
        return _drop("invalid")
    hide = _hider(root)
    if hide is None:
        return _drop("hider_off")
    src = _state["src"]
    minute = int(time.time() // 60)
    with _lock:
        for k in [k for k in _rate if k[1] != minute]:
            del _rate[k]
        n = _rate.get((src, minute), 0) + 1
        _rate[(src, minute)] = n
        if n > SRC_EVENTS_PER_MIN:
            _dropped["source_events"] = _dropped.get("source_events", 0) + 1
            return
        pending = dict(_dropped)
        _dropped.clear()
        _state["seq"] += 2 if pending else 1
        seq = _state["seq"]
    try:
        frame = sys._getframe(depth)
        code = f"{Path(frame.f_code.co_filename).stem}:{frame.f_code.co_name}:{frame.f_lineno}"
    except ValueError:
        code = "unknown:unknown:0"
    trace_id, span, parent = _current()
    now = datetime.now(UTC)
    event = {
        "v": 1,
        "at": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z",
        "mono_ms": int(time.monotonic() * 1000),
        "seq": seq,
        "src": src,
        "ver": __version__,
        "lvl": lvl,
        "ev": ev,
        "trace": {"trace_id": trace_id, "span_id": span, "parent_span_id": parent},
        "ws": _workspace_id(root),
        "ticket": kv.pop("ticket", None) or os.environ.get("ORCH_TICKET") or None,
        "run": kv.pop("run", None) or os.environ.get("ORCH_RUN") or None,
        "job": os.environ.get("ORCH_JOB") or None,
        "code": code,
        "pid": os.getpid(),
        "proc_start": _PROC_START,
        "dur_ms": dur_ms,
        "kv": _clean_kv(kv, hide),
        "err": _err(err) if err is not None else None,
    }
    for field in ("ticket", "run", "job", "ws"):
        if event[field] is not None:
            event[field] = hide(str(event[field]))[:STR_MAX]
    lines = []
    if pending:
        lines.append(_dropped_event(event, pending))  # takes seq - 1
    lines.append(event)
    d = _folder(root)
    if d is None:
        return _restore(pending, "no_folder")
    day = now.strftime("%Y-%m-%d")
    for i, line in enumerate(lines):
        data = json.dumps(line, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(data) > LINE_MAX:
            line["kv"] = {}
            data = json.dumps(line, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        if not _append(d, src, day, data):
            return _restore(pending if i == 0 else {}, "write")
    mono = time.monotonic()
    if mono - _state["last_prune"] > PRUNE_EVERY:
        _state["last_prune"] = mono
        prune(root)


def _dropped_event(base: dict, pending: dict) -> dict:
    ev = dict(base)
    ev.update(
        ev="diag.dropped",
        lvl="warn",
        seq=base["seq"] - 1,
        err=None,
        dur_ms=None,
        kv={"count": sum(pending.values()), **{f"n_{k}": v for k, v in sorted(pending.items())}},
    )
    return ev


def _restore(pending: dict, reason: str) -> None:
    with _lock:
        for k, v in pending.items():
            _dropped[k] = _dropped.get(k, 0) + v
        _dropped[reason] = _dropped.get(reason, 0) + 1


def _safe(root, ev, lvl, kv, err, dur_ms, depth) -> None:
    if getattr(_busy, "on", False):
        return  # a diag call made while diag works (config -> home -> trace): never recurse
    _busy.on = True
    try:
        r = Path(root) if root is not None else _state["root"]
        if r is None:
            return
        _emit(r, ev, lvl, dict(kv), err=err, dur_ms=dur_ms, depth=depth)
    except BaseException as e:  # noqa: BLE001 - never raises into the caller, not even KeyboardInterrupt
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        with contextlib.suppress(Exception):
            _drop("error")
    finally:
        _busy.on = False


# --- the API --------------------------------------------------------


def log(ev: str, lvl: str = "debug", *, root: Path | None = None, **kv) -> None:
    """One event. `ev` is `area.thing_happened`; kv are scalars (or short lists of scalars)."""
    _safe(root, ev, lvl, kv, None, None, 3)


def error(ev: str, exc: BaseException, *, root: Path | None = None, **kv) -> None:
    """One error event: the exception's type, a fingerprint and the code places (no message, no locals)."""
    _safe(root, ev, "error", kv, exc, None, 3)


@contextlib.contextmanager
def span(ev: str, lvl: str = "debug", *, root: Path | None = None, **kv):
    """A child span: one event at the end with dur_ms (an exception adds err and is re-raised)."""
    trace_id, cur_span, _ = _current()
    token = _trace.set((trace_id, secrets.token_hex(8), cur_span))
    t0 = time.monotonic()
    err = None
    try:
        yield
    except BaseException as e:
        err = e
        raise
    finally:
        dur = int((time.monotonic() - t0) * 1000)
        _safe(
            root, ev, "error" if err is not None and not isinstance(err, SystemExit) else lvl, kv, err, dur, 4
        )
        _trace.reset(token)
