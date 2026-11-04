"""Read .orch/ files of a workspace into one JSON-able state. Read only; never writes."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

STATUS_ORDER = ["active", "waiting", "open", "done", "dropped"]
_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


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


def load_tickets(root: Path) -> tuple[list[dict], int]:
    """Valid-looking tickets (need schema orch.ticket/1, id, title, status). Returns (tickets, skipped)."""
    tickets, skipped = [], 0
    for f in _json_files(root / ".orch" / "tickets"):
        t = _load(f)
        if not (isinstance(t, dict) and t.get("schema") == "orch.ticket/1" and t.get("id") == f.stem
                and isinstance(t.get("title"), str) and t.get("status") in STATUS_ORDER):
            skipped += 1
            continue
        for k in ("checklist", "links", "questions", "history"):
            if not isinstance(t.get(k), list):
                t[k] = []
        tickets.append(t)
    tickets.sort(key=lambda t: str(t.get("updated_at", "")), reverse=True)
    return tickets, skipped


def load_scheduler(tickets: list[dict], root: Path) -> list[dict]:
    state = _load(root / ".orch" / "scheduler" / "state.json")
    state = state if isinstance(state, dict) else {}
    rows = []
    for t in tickets:
        if t["status"] in ("done", "dropped"):
            continue
        sched = (t.get("ext") or {}).get("scheduler") or {}
        recurring = t.get("type") == "recurring"
        if not (recurring or t.get("wake_at")):
            continue
        st = state.get(t["id"]) if isinstance(state.get(t["id"]), dict) else {}
        rows.append({
            "ticket": t["id"], "title": t["title"], "status": t["status"],
            "kind": "recurring" if recurring else "once",
            "cron": sched.get("cron"), "wake_at": t.get("wake_at"),
            "last_run": st.get("last_run"), "next_run": st.get("next_run"),
        })
    rows.sort(key=lambda r: str(r["next_run"] or r["wake_at"] or "~"))
    return rows


def load_inbox(root: Path) -> list[dict]:
    seen = _load(root / ".orch" / "inbox-seen.json")
    seen = seen if isinstance(seen, dict) else {}
    out = []
    for f in _json_files(root / ".orch" / "inbox"):
        m = _load(f)
        if not (isinstance(m, dict) and isinstance(m.get("id"), str)):
            continue
        body = m.get("body") if isinstance(m.get("body"), dict) else {}
        out.append({
            "id": m["id"], "from": str(m.get("from", "")), "type": str(m.get("type", "")),
            "created_at": m.get("created_at"), "ticket": m.get("ticket"),
            "title": body.get("title") or body.get("name") or "",
            "text": body.get("text") or body.get("answer") or "",
            "seen": m["id"] in seen,
        })
    out.sort(key=lambda m: str(m["created_at"] or ""), reverse=True)
    return out


def load_state(root: Path, include_inbox: bool = True) -> dict:
    tickets, skipped = load_tickets(root)
    state = {
        "workspace": root.name,
        "now": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tickets": tickets,
        "skipped": skipped,
        "scheduler": load_scheduler(tickets, root),
        "inbox": load_inbox(root) if include_inbox else None,
        "relay": (root / ".orch" / "secrets" / "relay.json").is_file(),
    }
    state["rev"] = hashlib.sha1(
        json.dumps({k: v for k, v in state.items() if k != "now"}, sort_keys=True).encode()).hexdigest()[:12]
    return state
