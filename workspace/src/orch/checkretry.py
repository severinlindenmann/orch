"""Checks orch ran once more after a timeout or network error (`orch ref wait`), or once in a merge queue
group before it is split (reason "flaky", ORCH-1118), counted for Insights.

One line per retried check in `check-retries.jsonl` in the orch folder (all workspaces of this computer):
{"t": <epoch seconds>, "repo", "pr", "check", "reason": "timeout" | "network" | "flaky"}. No text from any
log. A check that shows up again and again is a flaky test or a bad runner: `summary()` lists them, most
retried first.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

DAY = 86400
KEEP_DAYS = 90
REASONS = ("timeout", "network", "flaky")


def _file() -> Path:
    from orch import addons

    return addons.home() / "check-retries.jsonl"


def record(repo: str, pr: str, check: str, reason: str, now: float | None = None) -> None:
    """Write one retry down. Never raises: counting must not stop a wait."""
    row = {"t": time.time() if now is None else now, "repo": str(repo)[:120], "pr": str(pr)[:12],
           "check": str(check)[:120], "reason": reason if reason in REASONS else "network"}  # fmt: skip
    try:
        p = _file()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


def summary(days: int = 30, now: float | None = None) -> dict:
    """{"days", "total", "checks": [{"check", "repo", "count", "timeout", "network", "flaky"}]} for the last
    `days`."""
    now = time.time() if now is None else now
    by: dict[tuple[str, str], dict] = {}
    total = 0
    try:
        lines = _file().read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        t = r.get("t") if isinstance(r, dict) else None
        if not isinstance(t, (int, float)) or isinstance(t, bool) or not now - days * DAY <= t <= now + 60:
            continue
        if not isinstance(r.get("check"), str) or r.get("reason") not in REASONS:
            continue
        e = by.setdefault(
            (str(r.get("repo")), r["check"]),
            {
                "check": r["check"],
                "repo": str(r.get("repo")),
                "count": 0,
                "timeout": 0,
                "network": 0,
                "flaky": 0,
            },
        )
        e["count"] += 1
        e[r["reason"]] += 1
        total += 1
    rows = sorted(by.values(), key=lambda e: (-e["count"], e["check"]))
    return {"days": days, "total": total, "checks": rows}
