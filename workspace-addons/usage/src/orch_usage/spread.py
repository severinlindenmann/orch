"""The day's spread on the Usage page (ORCH-660, draft C of ORCH-656): per source, how many helper starts it took
today, its percent of the day, the money, the last 7 days and why a source is skipped now.

It only reads. The starts come from the file Usage writes for every helper start (ORCH-658, `starts.json`, schema
`orch.usage-starts/1`): one entry per start id, with its UTC day, source (account id), state, held dollars and real
spend. A start counts when it is held, started or done (a failed start gave its money back and does not count).
Without the file every source shows 0 starts. Days are UTC, like the starts file. Only labels, numbers and words:
never a key or login.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import store

STARTS = "starts.json"
SCHEMA = "orch.usage-starts/1"
COUNTED = ("held", "started", "done")
DAYS = 7
KIND_WORDS = {
    "lead": "Lead",
    "code": "Code",
    "reviews": "Reviews",
    "builds": "Builds",
    "scripts": "Scripts",
    "helpers": "Helpers",
}
WINDOW_WORDS = {"5h": "5 hours", "week": "week", "month": "month"}
PERIOD_WORDS = {
    "5h": "per 5 hours",
    "week": "a week",
    "month": "a month",
    "day": "a day",
    "until": "until its date",
}


def _starts(root: Path) -> list[dict]:
    """The start entries of the starts file; nothing when it is missing, broken or of another schema."""
    try:
        data = json.loads((store.ensure(root) / STARTS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("starts"), dict):
        return []
    return [e for e in data["starts"].values() if isinstance(e, dict) and e.get("state") in COUNTED]


def _money(e: dict) -> float:
    """What a start cost: its real spend once known, else the dollars held for it."""
    for k in ("spent", "dollars"):
        v = e.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
            return float(v)
    return 0.0


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _amount(v: float, unit: str) -> str:
    text = f"{v:.2f}".rstrip("0").rstrip(".")
    return f"${text}" if unit == "$" else f"{text} %"


def skipped(acc: dict) -> str | None:
    """Why Usage skips this source now, in plain words, or None. `acc` is an account of the page model."""
    if not acc.get("on"):
        return "It is turned off, so the next account takes its work"
    if acc.get("state") == "missing":
        return "It is not found on this computer, so the next account takes its work"
    for b in acc.get("bars") or []:
        used, limit = _num(b.get("used")), _num(b.get("limit"))
        if limit is None and b.get("unit") == "%" and used is not None and used >= 100:
            return f"It used all of its {WINDOW_WORDS.get(str(b.get('period')), 'time')}, so the next account takes its work"
        if used is None or limit is None or used < limit:
            continue
        if b.get("unit") == "$" and b.get("limit_unit") == "$" and b.get("period") == "until":
            return f"{_amount(max(limit - used, 0.0), '$')} left, so the next account takes its work"
        period = PERIOD_WORDS.get(str(b.get("period")), "")
        lim = _amount(limit, str(b.get("limit_unit") or b.get("unit") or "%"))
        return f"Its own limit is {lim} {period}, so the next account takes its work".replace("  ", " ")
    return None


def paid(acc: dict) -> bool:
    """Money is shown for an API key and for a helper tool with a dollar limit; a subscription is already paid."""
    if acc.get("type") == "api-key":
        return True
    return acc.get("type") == "helper-tool" and any(lim.get("unit") == "$" for lim in acc.get("limits") or [])


def build(root: Path, accounts: list[dict], at: datetime | None = None) -> dict:
    """The Today section: per account (page order) starts, percent of today, money, 7 days, kinds and skipped."""
    at = at or datetime.now(UTC)
    today = at.astimezone(UTC).date()
    days = [(today - timedelta(days=DAYS - 1 - i)).isoformat() for i in range(DAYS)]
    index = {d: i for i, d in enumerate(days)}
    per: dict[str, dict] = {}
    for e in _starts(root):
        i = index.get(e.get("day"))
        src = e.get("source")
        if i is None or not isinstance(src, str):
            continue
        p = per.setdefault(
            src, {"starts": [0] * DAYS, "dollars": [0.0] * DAYS, "kinds": {}, "label": e.get("label")}
        )
        p["starts"][i] += 1
        p["dollars"][i] = round(p["dollars"][i] + _money(e), 4)
        if i == DAYS - 1:
            kind = KIND_WORDS.get(str(e.get("kind")), "Helpers")
            p["kinds"][kind] = p["kinds"].get(kind, 0) + 1
    total = sum(p["starts"][-1] for p in per.values())
    # ORCH-943: every workspace on this computer counts toward the same limits; the split shows who used what today
    split: dict[str, dict] = {}
    for e in _starts(root):
        if e.get("day") != days[-1]:
            continue
        w = split.setdefault(str(e.get("workspace") or "This workspace"), {"starts": 0, "dollars": 0.0})
        w["starts"] += 1
        w["dollars"] = round(w["dollars"] + _money(e), 4)
    rows = []
    known = set()
    for a in accounts:
        known.add(a["id"])
        rows.append(_row(a["id"], a["label"], a["type"], per.get(a["id"]), total, skipped(a), paid(a)))
    # starts on a source no longer in the list (removed account) still count in today's 100 %
    for src, p in per.items():
        if src not in known and sum(p["starts"]):
            rows.append(
                _row(src, str(p.get("label") or "Removed account"), "", p, total, None, any(p["dollars"]))
            )
    money = round(sum(r["dollars"] for r in rows if r["dollars"] is not None), 2)
    return {
        "day": today.isoformat(),
        "days": days,
        "starts": total,
        "dollars": money,
        "sources": rows,
        "workspaces": [
            {"name": k, "starts": v["starts"], "dollars": round(v["dollars"], 2)}
            for k, v in sorted(split.items(), key=lambda kv: (-kv[1]["starts"], kv[0]))
        ]
        if len(split) > 1
        else [],
    }


def _row(sid: str, label: str, kind: str, p: dict | None, total: int, skip: str | None, paid: bool) -> dict:
    starts = list(p["starts"]) if p else [0] * DAYS
    dollars = list(p["dollars"]) if p else [0.0] * DAYS
    n = starts[-1]
    kinds = sorted((p or {}).get("kinds", {}).items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "id": sid,
        "label": label,
        "type": kind,
        "starts": n,
        "pct": round(n * 100 / total) if total else 0,
        "dollars": round(dollars[-1], 2) if paid else None,
        "kinds": [k for k, _ in kinds],
        "week": starts,
        "week_starts": sum(starts),
        "week_dollars": round(sum(dollars), 2) if paid else None,
        "skipped": skip,
    }
