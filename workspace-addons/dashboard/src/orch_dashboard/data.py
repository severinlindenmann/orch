"""Read .orch/ files of a workspace into one JSON-able state. Read only; never writes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

STATUS_ORDER = ["active", "waiting", "open", "done", "dropped"]
_NAME = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
ICONS = ("clock", "calendar", "inbox", "list", "chart", "bell", "book", "globe", "link", "check", "star", "box",
         "chat", "folder", "user", "bolt")
FORMATS = ("text", "time", "cron-human", "chips", "yes-no")


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
        tickets.append(t)
    tickets.sort(key=lambda t: str(t.get("updated_at", "")), reverse=True)
    return tickets, skipped


def load_addons(root: Path, orch_bin: str | None) -> list[dict]:
    """Active add-ons that have a dashboard tab and/or ticket rows, from `orch addon list --json`, by `order`."""
    raw = run_orch(orch_bin, ["addon", "list", "--json"], root)
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


def load_names(root: Path) -> dict[str, str]:
    """Workspace id -> display name, from the directory the relay refresh wrote (empty if missing)."""
    d = _load(root / ".agents" / "skills" / "orch-relay" / "workspaces.json")
    out: dict[str, str] = {}
    if isinstance(d, dict) and isinstance(d.get("self"), str):
        out[d["self"]] = root.name
    for w in (d.get("workspaces") if isinstance(d, dict) else None) or []:
        if isinstance(w, dict) and isinstance(w.get("id"), str) and isinstance(w.get("name"), str):
            out[w["id"]] = w["name"]
    return out


def _who(sender: str, names: dict[str, str]) -> str:
    if sender in names:
        return names[sender]
    if sender.startswith("ph_"):
        return "Your phone"
    if sender.startswith("ws_"):
        return "Another workspace"
    if sender == "admin":
        return "Admin"
    return "Unknown sender"


def load_inbox(root: Path, names: dict[str, str] | None = None) -> list[dict]:
    seen = _load(root / ".orch" / "inbox-seen.json")
    seen = seen if isinstance(seen, dict) else {}
    out = []
    for f in _json_files(root / ".orch" / "inbox"):
        m = _load(f)
        if not (isinstance(m, dict) and isinstance(m.get("id"), str)):
            continue
        body = m.get("body") if isinstance(m.get("body"), dict) else {}
        out.append({
            "id": m["id"], "from": _who(str(m.get("from", "")), names or {}), "type": str(m.get("type", "")),
            "created_at": m.get("created_at"), "ticket": m.get("ticket"),
            "title": body.get("title") or body.get("name") or "",
            "text": body.get("text") or body.get("answer") or "",
            "seen": m["id"] in seen,
        })
    out.sort(key=lambda m: str(m["created_at"] or ""), reverse=True)
    return out


def load_state(root: Path, include_inbox: bool = True, orch_bin: str | None = None, with_addons: bool = True) -> dict:
    """with_addons=False (snapshots by default): no add-on tabs, no ticket rows, `ext` dropped from tickets."""
    tickets, skipped = load_tickets(root, orch_bin)
    names = load_names(root) if include_inbox else {}
    addons = load_addons(root, orch_bin) if with_addons else []
    if not with_addons:
        for t in tickets:
            t.pop("ext", None)
    state = {
        "workspace": root.name,
        "now": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tickets": tickets,
        "skipped": skipped,
        "addons": addons,
        "names": names if include_inbox else {},
        "inbox": load_inbox(root, names) if include_inbox else None,
        "relay": (root / ".orch" / "secrets" / "relay.json").is_file(),
    }
    state["rev"] = hashlib.sha1(
        json.dumps({k: v for k, v in state.items() if k != "now"}, sort_keys=True).encode()).hexdigest()[:12]
    return state
