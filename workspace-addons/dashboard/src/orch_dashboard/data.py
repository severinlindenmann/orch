"""Read .orch/ files of a workspace into one JSON-able state. Read only; never writes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

STATUS_ORDER = ["active", "waiting", "open", "done", "dropped"]
_NAME = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
ICONS = ("clock", "calendar", "inbox", "list", "chart", "bell", "book", "globe", "link", "check", "star", "box",
         "chat", "folder", "user", "bolt")
FORMATS = ("text", "time", "cron-human", "chips", "yes-no", "open-page")


def find_workspace(start: Path) -> Path | None:
    """Walk up from start to the first folder that has .orch/."""
    p = start.resolve()
    for d in [p, *p.parents]:
        if (d / ".orch").is_dir():
            return d
    return None


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _json_files(folder: Path):
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.json") if p.is_file() and not p.is_symlink())


def run_orch(orch_bin: str | None, args: list[str], root: Path, timeout: float = 5.0):
    """Run `$ORCH_BIN <args>` in the workspace and return its parsed stdout JSON, or None on any failure."""
    if not orch_bin:
        return None
    try:
        r = subprocess.run([orch_bin, *args], check=False, cwd=root, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "ORCH_ROOT": str(root), "ORCH_BIN": orch_bin})
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _valid_ticket(t, stem: str | None = None) -> bool:
    return (isinstance(t, dict) and t.get("schema") == "orch.ticket/1" and isinstance(t.get("id"), str)
            and (stem is None or t["id"] == stem) and isinstance(t.get("title"), str)
            and t.get("status") in STATUS_ORDER)


def _file_here(root: Path, tid: str, ref: str) -> bool:
    """Is this proof file on this computer? Looked up under the workspace or the ticket's evidence folder, never outside."""
    base = root.resolve()
    for cand in (root / ref, root / ".orch" / "tickets" / tid / "evidence" / Path(ref).name):
        try:
            p = cand.resolve()
            p.relative_to(base)
        except (OSError, ValueError, RuntimeError):
            continue
        if p.is_file():
            return True
    return False


def _mark_missing_proofs(root: Path, t: dict) -> None:
    for c in t.get("checklist", []):
        for ev in c.get("evidence", []) if isinstance(c, dict) and isinstance(c.get("evidence"), list) else []:
            if isinstance(ev, dict) and ev.get("type") == "file" and isinstance(ev.get("ref"), str) and "\x00" not in ev["ref"]:
                ev["missing"] = not _file_here(root, str(t["id"]), ev["ref"])


def load_tickets(root: Path, orch_bin: str | None = None) -> tuple[list[dict], int]:
    """Valid-looking tickets (schema orch.ticket/1, id, title, status). Returns (tickets, skipped).
    Read through `$ORCH_BIN ticket list --all --json` (without --all, done and dropped tickets would vanish); without the orch command (standalone use) from .orch/tickets."""
    raw = run_orch(orch_bin, ["ticket", "list", "--all", "--json"], root)
    if isinstance(raw, dict):
        raw = raw.get("tickets")
    if isinstance(raw, list):
        items = [(t, None) for t in raw]
    else:
        items = [(_load(f), f.stem) for f in _json_files(root / ".orch" / "tickets")]
    tickets, skipped = [], 0
    for t, stem in items:
        if not _valid_ticket(t, stem):
            skipped += 1
            continue
        for k in ("checklist", "links", "questions", "history"):
            if not isinstance(t.get(k), list):
                t[k] = []
        _mark_missing_proofs(root, t)
        tickets.append(t)
    tickets.sort(key=lambda t: str(t.get("updated_at", "")), reverse=True)
    return tickets, skipped


def load_addons(root: Path, orch_bin: str | None, raw=None) -> list[dict]:
    """Active add-ons that have a dashboard tab and/or ticket rows, from `orch addon list --json`, by `order`."""
    raw = run_orch(orch_bin, ["addon", "list", "--json"], root) if raw is None else raw
    out = []
    for a in raw if isinstance(raw, list) else []:
        if not (isinstance(a, dict) and a.get("active") is True and isinstance(a.get("name"), str)
                and _NAME.match(a["name"])):
            continue
        d = a.get("dashboard") if isinstance(a.get("dashboard"), dict) else None
        if d and not (isinstance(d.get("label"), str) and d.get("icon") in ICONS):
            d = None
        tv = [r for r in a.get("ticket_view") or [] if isinstance(r, dict) and isinstance(r.get("field"), str)
              and isinstance(r.get("label"), str) and r.get("format") in FORMATS]
        if d or tv:
            out.append({"name": a["name"], "dashboard": d and {"label": d["label"][:16], "icon": d["icon"],
                                                               "order": d.get("order", 50)}, "ticket_view": tv})
    out.sort(key=lambda a: (a["dashboard"] or {}).get("order", 50))
    return out


def load_services(root: Path, orch_bin: str | None) -> list[dict]:
    """Background add-ons of this workspace, running or not. Source: `orch status --json` only (rows: addon, running, url)."""
    raw = run_orch(orch_bin, ["status", "--json"], root)
    here = str(root.resolve())
    for w in raw if isinstance(raw, list) else []:
        if isinstance(w, dict) and w.get("workspace") == here and isinstance(w.get("addons"), list):
            return [r for r in w["addons"] if isinstance(r, dict) and isinstance(r.get("addon"), str)]
    return []


_RUNS: dict[tuple[str, str], tuple[float, dict | None]] = {}
RUNS_TTL = 5.0
RUNS_MAX = 30


def load_runs(root: Path, orch_bin: str | None, tickets: list[dict], fresh: bool = False) -> dict[str, dict]:
    """Run status for tickets that can have a run (active or waiting), from `orch run status <id> --json`.
    Cached for a few seconds so the 3 s page poll costs nothing; an action's reply passes fresh=True."""
    if not orch_bin:
        return {}
    ids = [t["id"] for t in tickets if t["status"] in ("active", "waiting")][:RUNS_MAX]
    now = time.monotonic()
    todo = [i for i in ids if fresh or (str(root), i) not in _RUNS or now - _RUNS[(str(root), i)][0] > RUNS_TTL]
    if todo:
        with ThreadPoolExecutor(max_workers=6) as pool:
            got = list(pool.map(lambda i: run_orch(orch_bin, ["run", "status", i, "--json"], root), todo))
        for i, r in zip(todo, got, strict=True):
            _RUNS[(str(root), i)] = (now, r if isinstance(r, dict) else None)
    return {i: _RUNS[(str(root), i)][1] for i in ids if _RUNS[(str(root), i)][1]}


def load_state(root: Path, orch_bin: str | None = None, with_addons: bool = True, fresh: bool = False) -> dict:
    """with_addons=False (snapshots by default): no add-on tabs, no ticket rows, `ext` dropped from tickets."""
    tickets, skipped = load_tickets(root, orch_bin)
    raw = run_orch(orch_bin, ["addon", "list", "--json"], root)
    addons = load_addons(root, orch_bin, raw) if with_addons else []
    if not with_addons:
        for t in tickets:
            t.pop("ext", None)
    needs = run_orch(orch_bin, ["needs", "--json"], root) if with_addons else None
    state = {
        "workspace": root.name,
        "now": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tickets": tickets,
        "skipped": skipped,
        "addons": addons,
        "needs": needs if isinstance(needs, list) else [],
        "services": load_services(root, orch_bin) if with_addons else [],  # snapshots name no add-on
        "runs": load_runs(root, orch_bin, tickets, fresh) if with_addons else {},
    }
    state["rev"] = hashlib.sha1(
        json.dumps({k: v for k, v in state.items() if k != "now"}, sort_keys=True).encode()).hexdigest()[:12]
    return state
