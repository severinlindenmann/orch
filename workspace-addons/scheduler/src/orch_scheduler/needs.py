"""`orch scheduler needs --json`: rows for `orch needs` (needs.schema.json). Warnings only, nothing is blocked.
1. A run that failed and was not asked as a question. 2. "Ran N× today without you" (N >= 10, LS-07 c / SA-16 c)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import orchcli
from .cron import fmt
from .loop import KIND, OPEN
from .runner import load_state, sdir

LOOP_WARN = 10


def _failed_runs(root: Path) -> list[dict]:
    try:
        lines = (sdir(root) / "runs.jsonl").read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines[-200:]:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("exit") not in (0, None) and isinstance(r.get("at"), str):
            out.append(r)
    return out


def rows(root: Path, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    today = fmt(now)[:10]
    day_ago = fmt(now - timedelta(days=1))
    tickets = {t["id"]: t for t in orchcli.tickets(root)}
    state = load_state(root)
    out: list[dict] = []
    for r in _failed_runs(root):
        t = tickets.get(r.get("ticket"))
        if t is None or t["status"] not in OPEN or r["at"] < day_ago:
            continue
        if any(q.get("kind") == KIND for q in t.get("questions") or []):
            continue  # already a question: core shows it
        out.append({"id": f"scheduler:failed-{t['id']}-{r['at']}", "source": "scheduler", "kind": "scheduler:failed-run",
                    "ticket": t["id"], "title": t["title"][:200], "text": "The last automatic run did not work.",
                    "tone": "bad", "since": r["at"], "cli": f"orch run start {t['id']}"})
    for tid, t in tickets.items():
        if t["status"] not in OPEN:
            continue
        human = max((h.get("at", "") for h in t.get("history") or [] if str(h.get("by", "")).startswith("human:")),
                    default="")
        starts = [s for s in (state.get(tid, {}).get("starts") or []) if isinstance(s, str)
                  and s[:10] == today and s > human]
        if len(starts) >= LOOP_WARN:
            out.append({"id": f"scheduler:loop-{tid}-{today}", "source": "scheduler", "kind": "scheduler:loop",
                        "ticket": tid, "title": t["title"][:200], "text": f"Ran {len(starts)}× today without you",
                        "tone": "warn", "since": starts[-1]})
    return out
