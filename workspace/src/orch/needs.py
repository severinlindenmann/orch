"""`orch needs`: what waits for a person. One list for every surface (contracts/needs.schema.json).

Core rows come from tickets and services alone: open questions, waits past their `until`, active background
add-ons that are not running. An active add-on with `needs = true` adds rows through
`orch <name> needs --json` (2 s timeout, last good result cached; on failure the cached rows come back
with stale = true).
The core names no add-on.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from orch import addons, history, services, tickets

PULL_TIMEOUT = 2
TONES = ("needs-you", "bad", "warn")
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}:[A-Za-z0-9_.:-]{1,200}$")
KIND_RE = re.compile(r"^(question|overdue-wait|[a-z][a-z0-9-]{1,31}:[a-z][a-z0-9-]{1,31})$")
TIME_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
TID_RE = re.compile(r"^t_[a-z0-9]{6,16}$")
OPEN = ("done", "dropped")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clip(v: str, n: int) -> str:
    v = " ".join(str(v).split()) or "-"
    return v if len(v) <= n else v[: n - 1] + "…"


def _asked_at(root: Path, t: dict, qid: str) -> str:
    for h in history.lines(root, t):
        if isinstance(h, dict) and h.get("text", "").startswith(f"Asked {qid},") and h.get("at"):
            return h["at"]
    return t.get("updated_at") or t.get("created_at") or _now()


def _bring_back_row(tid: str, title: str, back: dict, now: str) -> dict:
    """The text comes from the fixed reason table by CODE (unknown code: the generic text); never the free
    `reason`/`at` of a record (the pending file is unsigned and agent-writable)."""
    from orch.worktrees import BRING_BACK_REASONS

    code = back.get("reason_code")
    reason = BRING_BACK_REASONS.get(
        code if isinstance(code, str) else "waiting", BRING_BACK_REASONS["waiting"]
    )
    return {
        "id": f"core:bring-back:{tid}",
        "source": "core",
        "kind": "copies:bring-back",
        "ticket": tid,
        "title": _clip(f"Your work from {title} is on its own branch", 200),
        "text": "Bring it back into your project?",
        "reason": reason,
        "tone": "needs-you",
        "since": now,
        "cli": f"orch copy approve {tid}",
        "button": "Review and bring back",
    }


def core_rows(root: Path, now: str | None = None) -> list[dict]:
    now = now or _now()
    rows = []
    seen = set()
    for t in history.shown_json(root, tickets.list_all(root)):  # every person field as proven here
        seen.add(t["id"])
        back = (t.get("work") or {}).get("bring_back") or {}
        if back.get("state") == "waiting":
            rows.append(_bring_back_row(t["id"], t.get("title", t["id"]), back, now))
        if t.get("status") in OPEN or not isinstance(t.get("id"), str):
            continue
        title = _clip(t.get("title", t["id"]), 200)
        for q in t.get("questions") or []:
            if q.get("answer") is not None:
                continue
            rows.append(
                {
                    "id": f"core:q:{t['id']}:{q['id']}",
                    "source": "core",
                    "kind": q.get("kind") or "question",
                    "ticket": t["id"],
                    "title": title,
                    "text": _clip(q.get("text", ""), 500),
                    "tone": "needs-you",
                    "since": _asked_at(root, t, q["id"]),
                    "answer": {
                        "question": q["id"],
                        "options": list(q.get("options") or []),
                        "recommended": q.get("recommended"),
                    },
                }
            )
        w = t.get("waiting_on") or {}
        until = w.get("until")
        if isinstance(until, str) and until < now:
            if w.get("kind") == "time":
                text = f"Wake time passed; nothing started it. Start it: orch run start {t['id']}"
                cli = f"orch run start {t['id']}"
            else:
                text = f"Waiting on {w.get('kind')} {w.get('ref', '')}".strip() + f", past {until}"
                cli = None
            row = {
                "id": f"core:wait:{t['id']}",
                "source": "core",
                "kind": "overdue-wait",
                "ticket": t["id"],
                "title": title,
                "text": _clip(text, 500),
                "tone": "warn",
                "since": until,
            }
            if cli:
                row["cli"] = cli
            rows.append(row)
    from orch import worktrees

    for item in worktrees._pending(root)["kept"]:
        if item.get("bring_back") and item["ticket"] not in seen:
            rows.append(_bring_back_row(item["ticket"], item["ticket"], item, now))
    for r in services.workspace_rows(root):
        if not r["running"]:
            rows.append(
                {
                    "id": f"core:down:{r['name']}",
                    "source": "core",
                    "kind": "addon:not-running",
                    "ticket": None,
                    "title": r["name"],
                    "text": f"{r['name']} is not running (last seen {services.ago(r['last_seen'])})",
                    "tone": "bad",
                    "since": r["last_seen"] or now,
                    "cli": "orch start",
                }
            )
    return rows


# ---------------------------------------------------------------- add-on rows


def _cache_path(root: Path, name: str) -> Path:
    return root / ".orch" / "run" / "needs-cache" / f"{name}.json"


def _valid_row(name: str, r: object) -> dict | None:
    """A row from an add-on: the right shape, its own source, ids under its own name. Else dropped."""
    if not isinstance(r, dict):
        return None
    try:
        ok = (
            r["source"] == name
            and isinstance(r["id"], str)
            and ID_RE.match(r["id"])
            and r["id"].startswith(name + ":")
            and isinstance(r["kind"], str)
            and KIND_RE.match(r["kind"])
            and (r["ticket"] is None or (isinstance(r["ticket"], str) and TID_RE.match(r["ticket"])))
            and isinstance(r["title"], str)
            and 0 < len(r["title"]) <= 200
            and isinstance(r["text"], str)
            and 0 < len(r["text"]) <= 500
            and r["tone"] in TONES
            and isinstance(r["since"], str)
            and TIME_RE.match(r["since"])
        )
    except KeyError:
        return None
    if not ok:
        return None
    out = {k: v for k, v in r.items() if k != "stale"}
    out["stale"] = False
    return out


def _read_cache(root: Path, name: str) -> list[dict] | None:
    try:
        data = json.loads(_cache_path(root, name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    return [r for r in (_valid_row(name, x) for x in data) if r]


def _write_cache(root: Path, name: str, rows: list[dict]) -> None:
    p = _cache_path(root, name)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(rows, f)
        os.replace(tmp, p)
    except OSError:
        pass


def _pull(root: Path, name: str, m: dict) -> list[dict] | None:
    env = {**os.environ, "ORCH_ADDON": name, "ORCH_ROOT": str(root), "ORCH_BIN": addons.orch_bin()}
    try:
        r = subprocess.run(
            [sys.executable, "-P", "-m", m["run"], "needs", "--json"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=PULL_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
        if r.returncode != 0 or len(r.stdout) > 256 * 1024:
            return None
        data = json.loads(r.stdout)
    except (subprocess.SubprocessError, OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    return [x for x in (_valid_row(name, y) for y in data) if x]


def addon_rows(root: Path, name: str, m: dict) -> list[dict]:
    rows = _pull(root, name, m)
    if rows is not None:
        _write_cache(root, name, rows)
        return rows
    cached = _read_cache(root, name)
    if cached is not None:
        return [{**r, "stale": True} for r in cached]
    return [
        {
            "id": f"{name}:needs-unavailable",
            "source": name,
            "kind": f"{name}:needs",
            "ticket": None,
            "title": name,
            "text": f"{name} did not answer, so what it needs from you may be missing.",
            "tone": "warn",
            "since": _now(),
            "stale": True,
        }
    ]


def needs(root: Path) -> list[dict]:
    core = core_rows(root)
    seen = {r["id"] for r in core}
    answered = {(r["ticket"], r["answer"]["question"]) for r in core if "answer" in r}
    rows = list(core)
    for name, m in sorted(addons.active_manifests(root).items()):
        if not m.get("needs"):
            continue
        for r in addon_rows(root, name, m):
            ans = r.get("answer")
            same_q = isinstance(ans, dict) and (r["ticket"], ans.get("question")) in answered
            if r["id"] in seen or same_q:
                continue
            seen.add(r["id"])
            rows.append(r)
    order = {t: i for i, t in enumerate(TONES)}
    rows.sort(key=lambda r: (order[r["tone"]], r["since"], r["id"]))
    return rows
