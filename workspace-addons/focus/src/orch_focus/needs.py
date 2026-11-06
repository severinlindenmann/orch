"""`orch focus needs --json`: rows for `orch needs` (needs.schema.json), only what is not already a ticket question.

1. A live run that waits for the person's OK (the tool's Notification hook).
2. A tool the agent was refused in a run, when the ticket has no open question about it (the question comes
   from the ticket itself, so it is never doubled here)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from . import livedata
from .events import RUN_ID, EventLog
from .permissions import KIND, TOOL


def _denials(root: Path, run: str) -> list[dict]:
    if not RUN_ID.fullmatch(run):
        return []
    try:
        events, _ = EventLog(root, run).read()
    except (OSError, ValueError):
        return []
    return [
        e for e in events if e.get("kind") == "denial" and isinstance((e.get("data") or {}).get("tool"), str)
    ]


def rows(root: Path, orch_bin: str | None = None, now: datetime | None = None) -> list[dict]:
    now = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recs = livedata.records(root)
    if not recs:
        return []
    titles = livedata.tickets(root, orch_bin)
    out: list[dict] = []
    for rec in recs:
        tid = rec["ticket"]
        t = titles.get(tid) or {}
        since = str((rec.get("live") or {}).get("since") or rec.get("renewed_at") or now)
        if (rec.get("live") or {}).get("state") == "attention":
            out.append({"id": f"focus:waiting-{tid}", "source": "focus", "kind": "focus:waiting", "ticket": tid,
                        "title": livedata.title(t), "text": str((rec.get("live") or {}).get("why") or "Waiting for your OK in the live session.")[:400],
                        "tone": "needs-you", "since": since, "cli": f"orch run attach {tid}"})  # fmt: skip
        asked = {
            (q.get("action") or {}).get("tool") for q in t.get("questions") or [] if q.get("kind") == KIND
        }
        seen: set[str] = set()
        for e in _denials(root, rec["run"]):
            tool = e["data"]["tool"]
            if tool in seen or tool in asked or not TOOL.fullmatch(tool):
                continue
            seen.add(tool)
            out.append({"id": f"focus:denied-{tid}-{rec['run']}-{tool}"[:200], "source": "focus", "kind": "focus:denied",
                        "ticket": tid, "title": livedata.title(t), "text": f"{tool} was refused. Open the live page to allow it."[:500],
                        "tone": "warn", "since": str(e.get("at") or now), "cli": f"orch focus open {tid}"})  # fmt: skip
    return out
