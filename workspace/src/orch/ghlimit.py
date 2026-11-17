"""How many GitHub writes per hour this computer makes (the GitHub add-on's write limit), without an AI call.

GitHub blocks an account that writes in bursts around the clock (24 Oct 2026: the helpers' bot account was
suspended after 10-20 merges an hour plus pull requests and comments). So every GitHub write of orch, and of
any helper or script that asks first (`orch github wait <kind>`), takes a slot of its kind:

- at most `<kind>_per_hour` writes of that kind in the last hour (a setting: `orch config set
  github.merge_per_hour 12`), and
- a short pause between two writes of the same kind, so even a free hour is not used in one burst.

The slots are counted for the whole computer (every workspace and helper together) in one file in the orch
folder, `github-writes.jsonl`, guarded by a lock folder. A write that finds no room waits until there is,
up to a time limit, then says so in plain words; it never writes anyway.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

from orch.errors import Refused

KINDS = ("merge", "pr", "comment", "other")
WHAT = {
    "merge": "merges",
    "pr": "new pull requests",
    "comment": "comments",
    "other": "other GitHub writes",
}
DEFAULT_PER_HOUR = {"merge": 12, "pr": 12, "comment": 20, "other": 30}
PAUSE_SECS = {"merge": 120, "pr": 90, "comment": 30, "other": 20}  # between two writes of one kind
MAX_PER_HOUR = 200  # GitHub's own documented limit is 500 content writes an hour; stay far below it
HOUR = 3600
WAIT_SECS = 3600  # how long a write waits for room before it gives up
POLL_SECS = 20
STALE_LOCK_SECS = 60  # a lock folder older than this was left by a process that died holding it
SETTING_KEYS = {f"github.{k}_per_hour": k for k in KINDS}


def _home() -> Path:
    from orch import addons

    return addons.home()


def _limits_file() -> Path:
    return _home() / "github-limits.json"


def _log_file() -> Path:
    return _home() / "github-writes.jsonl"


def _lock_dir() -> Path:
    return _home() / ".github-writes.lock"


def kind_of(word: str) -> str:
    """A kind of write; anything unknown counts as `other` (a label, a rerun, a close)."""
    return word if word in KINDS else "other"


def limits() -> dict[str, int]:
    """Writes per hour allowed for each kind: the saved setting, else the default."""
    try:
        doc = json.loads(_limits_file().read_text(encoding="utf-8"))
    except (OSError, ValueError, Refused):
        doc = {}
    doc = doc if isinstance(doc, dict) else {}
    out = {}
    for k in KINDS:
        v = doc.get(k)
        ok = isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= MAX_PER_HOUR
        out[k] = v if ok else DEFAULT_PER_HOUR[k]
    return out


def set_limit(kind: str, value: str | int) -> int:
    """Save the writes per hour of one kind for this computer."""
    if kind not in KINDS:
        raise Refused(f"Choose one of: {', '.join(KINDS)}.")
    text = str(value).strip()
    if not (text.isascii() and text.isdigit()) or not 1 <= int(text) <= MAX_PER_HOUR:
        raise Refused(f"Choose a number from 1 to {MAX_PER_HOUR} {WHAT[kind]} per hour.")
    n = int(text)
    doc = {k: v for k, v in limits().items() if v != DEFAULT_PER_HOUR[k]}
    if n == DEFAULT_PER_HOUR[kind]:
        doc.pop(kind, None)
    else:
        doc[kind] = n
    _write_atomic(_limits_file(), json.dumps(doc, indent=1) + "\n")
    return n


def pause_secs(kind: str, per_hour: int) -> int:
    """The pause between two writes of one kind: the built-in one, shorter when the hour allows more."""
    return min(PAUSE_SECS[kind], HOUR // per_hour)


def _write_atomic(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(text.encode("utf-8"))
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


def _read_log(now: float) -> list[dict]:
    """The writes of the last hour, oldest first; an unreadable line is skipped."""
    rows = []
    try:
        lines = _log_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        t = r.get("t") if isinstance(r, dict) else None
        if isinstance(t, (int, float)) and now - HOUR <= t <= now + 60 and r.get("kind") in KINDS:
            rows.append(r)
    return rows


def _lock(clock) -> bool:
    d = _lock_dir()
    d.parent.mkdir(parents=True, exist_ok=True)
    try:
        d.mkdir()
        return True
    except FileExistsError:
        try:
            if clock() - d.stat().st_mtime > STALE_LOCK_SECS:
                d.rmdir()  # left by a process that died holding it; the next try takes it
        except OSError:
            pass
        return False


def _unlock() -> None:
    try:
        _lock_dir().rmdir()
    except OSError:
        pass


def _room(rows: list[dict], kind: str, per_hour: int, now: float) -> float:
    """0 when a write of `kind` fits now, else roughly how many seconds until it does."""
    mine = [r["t"] for r in rows if r["kind"] == kind]
    waits = [0.0]
    if len(mine) >= per_hour:
        waits.append(mine[len(mine) - per_hour] + HOUR - now)
    if mine:
        waits.append(max(mine) + pause_secs(kind, per_hour) - now)
    return max(waits)


def _try(kind: str, what: str, force: bool, clock) -> float:
    """Take a slot (or, with force, count the write without asking for room). 0 = taken."""
    if not _lock(clock):
        return POLL_SECS / 4
    try:
        now = clock()
        rows = _read_log(now)
        left = 0.0 if force else _room(rows, kind, limits()[kind], now)
        if left > 0:
            return left
        rows.append({"t": round(now, 3), "kind": kind, "what": str(what)[:200]})
        _write_atomic(_log_file(), "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        return 0.0
    finally:
        _unlock()


def take(kind: str, what: str = "", wait: float = WAIT_SECS, sleep=time.sleep, clock=time.time) -> bool:
    """Wait until one GitHub write of `kind` fits this computer's hourly limit, then count it. False when no
    room came within `wait` seconds (nothing is counted then: the caller must not write)."""
    kind = kind_of(kind)
    waited = 0.0
    while True:
        left = _try(kind, what, False, clock)
        if left <= 0:
            return True
        if waited >= wait:
            return False
        nap = max(1.0, min(left, POLL_SECS, wait - waited))
        sleep(nap)
        waited += nap


def wait_room(kind: str, wait: float = WAIT_SECS, sleep=time.sleep, clock=time.time) -> bool:
    """Wait until a write of `kind` would fit, WITHOUT counting it (the writer counts it when it writes:
    `orch ref wait --merge` takes the merge place when it merges). False when no room came in time."""
    kind = kind_of(kind)
    waited = 0.0
    while True:
        try:
            left = _room(_read_log(clock()), kind, limits()[kind], clock())
        except (OSError, Refused):
            return True
        if left <= 0:
            return True
        if waited >= wait:
            return False
        nap = max(1.0, min(left, POLL_SECS, wait - waited))
        sleep(nap)
        waited += nap


def give_back(kind: str, what: str, clock=time.time) -> bool:
    """Take back the newest counted write of `kind` for `what` when it did not happen after all (a merge
    GitHub refused). Never raises. True when a place was given back."""
    kind = kind_of(kind)
    for _ in range(20):
        try:
            if not _lock(clock):
                time.sleep(0.05)
                continue
            try:
                rows = _read_log(clock())
                for i in range(len(rows) - 1, -1, -1):
                    if rows[i]["kind"] == kind and rows[i].get("what") == str(what)[:200]:
                        del rows[i]
                        _write_atomic(
                            _log_file(), "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
                        )
                        return True
                return False
            finally:
                _unlock()
        except (OSError, Refused):
            return False
    return False


def count(kind: str, what: str = "", clock=time.time) -> None:
    """Count a write that already happened or must not wait (a person's own Merge click). Never raises: a
    count that cannot be written must not undo the person's action."""
    for _ in range(20):
        try:
            if _try(kind_of(kind), what, True, clock) <= 0:
                return
        except (OSError, Refused):
            return
        time.sleep(0.05)


def status(clock=time.time) -> list[dict]:
    """Per kind: writes in the last hour, the limit, seconds since the last one (None: none this hour) and
    seconds until the next one fits."""
    now = clock()
    rows = _read_log(now)
    lim = limits()
    out = []
    for k in KINDS:
        mine = [r["t"] for r in rows if r["kind"] == k]
        out.append(
            {
                "kind": k,
                "used": len(mine),
                "per_hour": lim[k],
                "last_secs_ago": round(now - max(mine)) if mine else None,
                "next_in_secs": round(_room(rows, k, lim[k], now)),
            }
        )
    return out
