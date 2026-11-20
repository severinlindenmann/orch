"""A repeating ticket's runs for the role page (ORCH-827), and which of a ticket's files a person opened.

`listing` reads `orch automation role <ticket> --json` (the automation add-on owns runs, results and findings) and
keeps only the fields the page shows, each checked. `note_open` writes the first time the file viewer showed a
ticket file to .orch/addons/dashboard/file-opens.json ({"since": first day measured, "files": {ticket: {name: at}}});
the automation add-on reads it to tell opened, unopened and unknown files apart.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from .data import run_orch

TID = re.compile(r"t_[a-z0-9]{6,16}")
NAME = re.compile(r"[^/\\\x00-\x1f]{1,240}")
KINDS = ("artifacts", "evidence", "files")
TONES = {"ok", "warn", "bad", "none", "working"}
OUTCOMES = {"ok", "problems", "not-finished", "failed", "skipped", "running", "none", "stopped"}
STATES = {"opened", "unopened", "unknown"}
MAX_RUNS = 200
MAX_TICKETS = 500  # file-opens.json keeps at most this many tickets (the oldest go first)
_lock = threading.Lock()


def _s(v, n: int) -> str:
    return " ".join(v.split())[:n] if isinstance(v, str) else ""


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None


def _run(r: dict) -> dict | None:
    if not isinstance(r, dict) or not isinstance(r.get("run"), int) or r.get("outcome") not in OUTCOMES:
        return None
    return {
        "run": r["run"],
        "at": _s(r.get("at"), 40),
        "took": _num(r.get("took")),
        "outcome": r["outcome"],
        "words": _s(r.get("words"), 60),
        "tone": r.get("tone") if r.get("tone") in TONES else "none",
        "text": _s(r.get("text"), 400),
        "checked": [_s(c, 200) for c in (r.get("checked") or [])[:12] if isinstance(c, str)],
        "cost": _num(r.get("cost")),
        "files": [
            {"name": f["name"], "state": f.get("state") if f.get("state") in STATES else "unknown"}
            for f in (r.get("files") or [])[:20]
            if isinstance(f, dict) and isinstance(f.get("name"), str) and NAME.fullmatch(f["name"])
        ],
        "findings": [
            {"title": _s(f.get("title"), 200), "ticket": f["ticket"]}
            for f in (r.get("findings") or [])[:50]
            if isinstance(f, dict) and isinstance(f.get("ticket"), str) and TID.fullmatch(f["ticket"])
        ],
        "script": _s(r.get("script"), 40) or None,
    }


def listing(root: Path, orch_bin: str | None, tid: str) -> dict:
    """{"available": bool, "runs": [...newest first], "totals": {...}}."""
    d = run_orch(orch_bin, ["automation", "role", tid, "--json"], root, timeout=15.0)
    if not isinstance(d, dict) or not isinstance(d.get("runs"), list):
        return {"available": False, "runs": [], "totals": None}
    runs = [x for x in (_run(r) for r in d["runs"][:MAX_RUNS]) if x]
    t = d.get("totals") if isinstance(d.get("totals"), dict) else {}
    ints = ("runs", "findings", "distinct_findings", "tickets", "fixed", "open", "dropped")
    files = t.get("files") if isinstance(t.get("files"), dict) else {}
    totals = {k: t.get(k) if isinstance(t.get(k), int) else 0 for k in ints}
    totals["by_outcome"] = {
        k: v for k, v in (t.get("by_outcome") or {}).items() if k in OUTCOMES and isinstance(v, int)
    }
    totals["files"] = {k: files.get(k) if isinstance(files.get(k), int) else 0 for k in STATES}
    totals["files_measured"] = t.get("files_measured") is True
    totals["cost"] = _num(t.get("cost"))
    sc = d.get("schedule") if isinstance(d.get("schedule"), dict) else {}
    limit = sc.get("time_limit")
    schedule = {
        "repeats": _s(sc.get("repeats"), 120),
        "cron": _s(sc.get("cron"), 60),
        "paused": sc.get("paused") is True,
        "next": [_s(x, 40) for x in (sc.get("next") or [])[:3] if isinstance(x, str)],
        "quick": sc.get("quick") if sc.get("quick") in ("on", "off", "none") else "none",
        "time_limit": limit if isinstance(limit, int) and not isinstance(limit, bool) and 0 < limit <= 600 else None,
        "running": sc.get("running") is True,
    }
    return {"available": True, "runs": runs, "totals": totals, "schedule": schedule}


def note_open(root: Path, tid: str, kind: str, name: str) -> bool:
    """The file viewer showed this file: keep its first open. False when the request is not a ticket file."""
    if not TID.fullmatch(tid or "") or kind not in KINDS or not isinstance(name, str) or not NAME.fullmatch(name):
        return False
    folder = root / ".orch" / "tickets" / tid / kind
    if not (folder / name).is_file():
        return False
    d = root / ".orch" / "addons" / "dashboard"
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _lock:
        if d.is_symlink():
            return False
        d.mkdir(parents=True, exist_ok=True)
        p = d / "file-opens.json"
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() and not p.is_symlink() else {}
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        files = data.get("files") if isinstance(data.get("files"), dict) else {}
        mine = files.get(tid) if isinstance(files.get(tid), dict) else {}
        if name in mine and isinstance(data.get("since"), str):
            return True
        mine[name] = now
        files[tid] = mine
        while len(files) > MAX_TICKETS:
            files.pop(next(iter(files)))
        data = {"since": data.get("since") if isinstance(data.get("since"), str) else now, "files": files}
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".file-opens-")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, p)
    return True
