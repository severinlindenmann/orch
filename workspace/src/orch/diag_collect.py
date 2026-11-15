"""Read-only collectors for `orch diag inspect` and reports (contracts/diag.md, "inspect").

Hard rule: nothing here writes, repairs or settles anything. A collector reads files directly or calls a
function that is pure (`runs.read`, `runs.state`, `tickets._load_raw`, `record.read_run`). It never
calls a helper
that repairs as a side effect (`runs.settle_orphan`, `tickets.load` re-signs / tombstones). Tests hash
`.orch/`
before and after every collector.

Each collector returns `{collected_at, revision?, data, gaps[]}`. A collector has 5 s and `CAP_BYTES` of
output;
past that its data is replaced by a note and a gap says so. Structure only: ticket text is never
collected here
(it goes to the report's content/ part, which is opt-in).
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import shutil
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from orch import __version__, diag, procs, runs, services, tickets

TIME_LIMIT = 5.0
CAP_BYTES = 256 * 1024
MAX_TICKETS = 50
MAX_LOCKS = 200
HISTORY_LINES = 30


def _iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if ts is None else ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age(iso: str | None, now: float) -> float | None:
    try:
        return max(0.0, now - runs._parse(iso)) if iso else None
    except (ValueError, TypeError):
        return None


def _json_file(p: Path):
    try:
        if p.is_symlink():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _scoped_tickets(root: Path, scope: dict) -> tuple[list[str], list[str]]:
    gaps: list[str] = []
    if scope.get("ticket"):
        return [scope["ticket"]], gaps
    d = tickets.tickets_dir(root)
    if d.is_symlink() or not d.is_dir():
        return [], gaps
    found = []
    for p in sorted(d.glob("*.json")):
        t = _json_file(p)
        if isinstance(t, dict) and t.get("status") == "active":  # Working
            found.append(t.get("id") or p.stem)
    if len(found) > MAX_TICKETS:
        gaps.append(f"{len(found)} tickets are Working, the first {MAX_TICKETS} are shown")
        found = found[:MAX_TICKETS]
    return found, gaps


# ---------------------------------------------------------------- the collectors


def tickets_data(root: Path, scope: dict, now: float) -> tuple[dict, list[str]]:
    ids, gaps = _scoped_tickets(root, scope)
    out: dict[str, dict] = {}
    for tid in ids:
        try:
            t = tickets._load_raw(root, tid)  # the file as it is: no verdict view, no ledger write
        except Exception as e:  # noqa: BLE001
            gaps.append(f"{tid}: {type(e).__name__}")
            continue
        hist = [
            {"at": h.get("at"), "by": h.get("by"), "via": h.get("via")}
            for h in (t.get("history") or [])[-HISTORY_LINES:]
            if isinstance(h, dict)
        ]
        out[tid] = {
            "id": tid,
            "status": t.get("status"),
            "revision": tickets.revision(t),
            "updated_at": t.get("updated_at"),
            "created_at": t.get("created_at"),
            "age_s": _age(t.get("updated_at"), now),
            "history": hist,
            "history_total": len(t.get("history") or []),
        }
    return {"tickets": out}, gaps


def _lock_info(p: Path, now: float) -> dict:
    text = None
    with contextlib.suppress(OSError):
        text = p.read_text(encoding="utf-8")[:200]
    parts = (text or "").split()
    pid = None
    with contextlib.suppress(ValueError, IndexError):
        pid = int(parts[0])
    started = parts[1] if len(parts) > 1 and parts[1] != "-" else None
    age = None
    with contextlib.suppress(OSError):
        age = max(0.0, now - p.stat().st_mtime)
    return {
        "holder_pid": pid,
        "holder_start": started,
        "holder_dead": procs.owner_dead(text) if text else None,  # None: nobody named, cannot say
        "age_s": age,
    }


def runs_data(root: Path, scope: dict, now: float) -> tuple[dict, list[str]]:
    ids, gaps = _scoped_tickets(root, scope)
    d = runs.run_dir(root) / "tickets"
    if d.is_dir() and not d.is_symlink():
        for p in sorted(d.glob("*.json")):  # a claim whose ticket is not Working is still evidence
            if p.stem not in ids and len(ids) < MAX_TICKETS and not scope.get("ticket"):
                ids.append(p.stem)
    out: dict[str, dict] = {}
    for tid in ids:
        try:
            rec = runs.read(root, tid)
        except Exception as e:  # noqa: BLE001
            gaps.append(f"{tid}: run record {type(e).__name__}")
            continue
        if not rec:
            continue
        if scope.get("run") and rec.get("run") != scope["run"]:
            continue
        live = rec.get("live") if isinstance(rec.get("live"), dict) else {}
        lock = runs.run_dir(root) / "tickets" / f"{tid}.lock"
        out[tid] = {
            "run": rec.get("run"),
            "ticket": tid,
            "by": rec.get("by"),
            "agent": rec.get("agent"),
            "model": rec.get("model"),
            "agent_version": rec.get("agent_version"),
            "mode": rec.get("mode"),
            "host": rec.get("host"),
            "folder": rec.get("folder"),
            "session": rec.get("session"),
            "parent_session": rec.get("parent_session"),
            "started_at": rec.get("started_at"),
            "last_heartbeat": rec.get("renewed_at"),
            "heartbeat_age_s": _age(rec.get("renewed_at"), now),
            "pid": rec.get("pid"),
            "pid_started": rec.get("pid_started"),
            "agent_pid": rec.get("agent_pid"),
            "agent_pid_started": rec.get("agent_pid_started"),
            "process": runs.state(rec, now),  # alive | dead | maybe-stale (pure)
            "live_state": live.get("state"),
            "live_since": live.get("since"),
            "stop_requested": rec.get("stop_requested"),
            "exit_code": rec.get("exit_code"),
            "lock": _lock_info(lock, now) if lock.exists() else None,
            "permission_rules": "values hidden",
        }
    if out and not any(r.get("exit_code") is not None for r in out.values()):
        gaps.append("exit codes are not kept in the run record while a run holds the ticket")
    return {"runs": out, "hook_failures": _hook_failures(root)}, gaps


def _hook_failures(root: Path) -> list[dict]:
    d = root / ".orch" / "record" / "alerts"
    out: list[dict] = []
    if d.is_symlink() or not d.is_dir():
        return out
    for p in sorted(d.glob("hook-lost*.jsonl"))[-10:]:
        if p.is_symlink():
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]
        except OSError:
            continue
        for ln in lines:
            with contextlib.suppress(ValueError):
                e = json.loads(ln)
                if isinstance(e, dict):
                    out.append({k: e.get(k) for k in ("at", "run", "reason", "error") if k in e})
    return out[-100:]


def services_data(root: Path, scope: dict, now: float) -> tuple[dict, list[str]]:
    rows = []
    for w in services.status():  # reads the running list; never starts or stops anything
        rows.append(
            {
                "workspace": w.get("workspace"),
                "addons": [
                    {
                        "addon": a.get("addon"),
                        "pid": a.get("pid"),
                        "alive": services.pid_alive(a["pid"]) if isinstance(a.get("pid"), int) else None,
                        "url": a.get("url"),
                    }
                    for a in w.get("addons", [])
                ],
            }
        )
    return {"services": rows}, []


def queues_data(root: Path, scope: dict, now: float) -> tuple[dict, list[str]]:
    gaps: list[str] = []
    out: dict = {}
    box = root / ".orch" / "outbox"
    msgs = []
    if box.is_dir() and not box.is_symlink():
        for p in box.glob("*.json"):
            with contextlib.suppress(OSError):
                msgs.append(max(0.0, now - p.stat().st_mtime))
    problem = None
    with contextlib.suppress(OSError):
        problem = (box / ".problem").read_text(encoding="utf-8").strip()[:200] or None
    out["relay_outbox"] = {
        "count": len(msgs),
        "oldest_age_s": max(msgs) if msgs else None,
        "problem": problem,
    }
    pend = runs.run_dir(root) / "pending"
    n_in = {}
    if pend.is_dir() and not pend.is_symlink():
        for p in sorted(pend.glob("*.jsonl"))[:MAX_TICKETS]:
            with contextlib.suppress(OSError):
                n_in[p.stem] = sum(1 for _ in p.open("rb"))
    out["pending_input"] = n_in
    rec_pend = root / ".orch" / "record" / "pending"
    n_rec = {}
    if rec_pend.is_dir() and not rec_pend.is_symlink():
        for p in sorted(rec_pend.iterdir())[:MAX_TICKETS]:
            if p.is_dir() and not p.is_symlink():
                with contextlib.suppress(OSError):
                    n_rec[p.name] = sum(1 for _ in p.iterdir())
    out["pending_record_writes"] = n_rec
    try:
        from orch import syncgate

        holder = syncgate.live_holder(root)
        out["sync_step_running"] = holder is not None
    except Exception:  # noqa: BLE001
        out["sync_step_running"] = None
        gaps.append("sync state could not be read")
    return out, gaps


def locks_data(root: Path, scope: dict, now: float) -> tuple[dict, list[str]]:
    gaps: list[str] = []
    base = root / ".orch"
    found: list[dict] = []
    if base.is_dir() and not base.is_symlink():
        for dirpath, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = [
                d for d in dirs if d not in ("diag", "worktrees") and not (Path(dirpath) / d).is_symlink()
            ]
            for f in files:
                if f.endswith(".lock") or f == "lock":
                    p = Path(dirpath) / f
                    if p.is_symlink():
                        continue
                    found.append({"path": str(p.relative_to(root)), **_lock_info(p, now)})
                    if len(found) >= MAX_LOCKS:
                        gaps.append(f"more than {MAX_LOCKS} lock files, the rest is not listed")
                        return {"locks": found}, gaps
    return {"locks": found}, gaps


def env_data(root: Path, scope: dict, now: float) -> tuple[dict, list[str]]:
    gaps: list[str] = []
    cfg: dict = {}
    try:
        from orch import config

        for table, value in config.read(root).items():  # key names only, values are never shown
            cfg[table] = sorted(value) if isinstance(value, dict) else "set"
    except Exception as e:  # noqa: BLE001
        gaps.append(f"config could not be read: {type(e).__name__}")
    try:
        from orch import config

        enabled = config.diag_enabled(root)
    except Exception:  # noqa: BLE001
        enabled = None
    return {
        "orch_version": __version__,
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "tz_offset_s": time.localtime().tm_gmtoff,
        "now": _iso(now),
        "config_keys": cfg,
        "diag_enabled": enabled,
    }, gaps


def disk_data(root: Path, scope: dict, now: float) -> tuple[dict, list[str]]:
    u = shutil.disk_usage(root)
    return {
        "free_bytes": u.free,
        "total_bytes": u.total,
        "free_percent": round(100.0 * u.free / u.total, 1),
    }, []


def diag_data(root: Path, scope: dict, now: float) -> tuple[dict, list[str]]:
    """What the debug log itself lost: this process's counters and the `diag.dropped` events of the last
    day."""
    dropped = 0
    last = None
    for e in recent_events(root, now - 86400):
        if e.get("ev") == "diag.dropped":
            dropped += int((e.get("kv") or {}).get("count") or 0)
            last = e.get("at")
    return {
        "dropped_in_this_process": diag.dropped_count(),
        "dropped_events_24h": dropped,
        "last_dropped_at": last,
        "enabled": diag.enabled(root),
    }, []


COLLECTORS = {
    "tickets": tickets_data,
    "runs": runs_data,
    "services": services_data,
    "queues": queues_data,
    "locks": locks_data,
    "env": env_data,
    "disk": disk_data,
    "diag": diag_data,
}


def activity_data(root: Path, scope: dict, now: float) -> tuple[dict, list[str]]:
    """The activity record of the scoped run/ticket, through the record readers (they dedupe), with
    their gaps."""
    from orch import cli_record

    gaps: list[str] = []
    if not (scope.get("ticket") or scope.get("run")):
        return {"events": []}, ["no run or ticket in scope, the activity record was not read"]
    run_ids = [scope["run"]] if scope.get("run") else None
    try:
        known = run_ids or cli_record._known(root)
        by_run, problems = cli_record._events(root, known, scope.get("ticket"), tell=False)
    except Exception as e:  # noqa: BLE001
        return {"events": []}, [f"the activity record could not be read: {type(e).__name__}"]
    for p in problems:
        gaps.append(f"record {p.get('run')}: {p.get('reason') or p.get('status')}")
    events = [e for evs in by_run.values() for e in evs]
    return {"events": events, "runs": sorted(by_run)}, gaps


COLLECTORS["activity"] = activity_data


# ---------------------------------------------------------------- running them


def _bounded(fn, root, scope, now) -> tuple[dict | None, list[str]]:
    box: dict = {}

    def work():
        try:
            box["r"] = fn(root, scope, now)
        except BaseException as e:  # noqa: BLE001
            box["e"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(TIME_LIMIT)
    if t.is_alive():
        return None, [f"took longer than {TIME_LIMIT:.0f} s, not collected"]
    if "e" in box:
        return None, [f"failed: {type(box['e']).__name__}"]
    return box["r"]


def collect(root: Path, name: str, scope: dict | None = None, now: float | None = None) -> dict:
    scope = scope or {}
    now = time.time() if now is None else now
    data, gaps = _bounded(COLLECTORS[name], root, scope, now)
    gaps = list(gaps)
    if data is not None and len(json.dumps(data, default=str)) > CAP_BYTES:
        data = {"truncated": True}
        gaps.append(f"more than {CAP_BYTES // 1024} KB, not kept")
    out = {"collected_at": _iso(now), "data": data if data is not None else {}, "gaps": gaps}
    if name == "tickets" and data:
        out["revision"] = {tid: t["revision"] for tid, t in data.get("tickets", {}).items()}
    return out


def collect_all(root: Path, scope: dict | None = None, now: float | None = None) -> dict[str, dict]:
    now = time.time() if now is None else now
    return {name: collect(root, name, scope, now) for name in COLLECTORS}


# ---------------------------------------------------------------- the debug log, read lazily


def recent_events(root: Path, since: float, until: float | None = None):
    """Debug-log events with `at` in [since, until], oldest file first. Files whose date is before the
    window are
    not opened. Read-only; a bad line is skipped."""
    d = root / ".orch" / "diag"
    if d.is_symlink() or not d.is_dir():
        return
    day_lo = datetime.fromtimestamp(since, UTC).strftime("%Y-%m-%d")
    day_hi = datetime.fromtimestamp(until if until else time.time() + 86400, UTC).strftime("%Y-%m-%d")
    lo, hi = _iso(since), _iso(until) if until else None
    for p in sorted(d.iterdir(), key=lambda p: p.name):
        m = diag._FILE.fullmatch(p.name)
        if not m or p.is_symlink() or not p.is_file() or not (day_lo <= m.group(1) <= day_hi):
            continue
        try:
            fh = p.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for ln in fh:
                try:
                    e = json.loads(ln)
                except ValueError:
                    continue
                at = e.get("at") if isinstance(e, dict) else None
                if isinstance(at, str) and at[:19] + "Z" >= lo and (hi is None or at[:19] + "Z" <= hi):
                    yield e
