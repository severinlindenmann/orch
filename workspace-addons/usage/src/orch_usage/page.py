"""What the Usage page shows (GET /api/page): accounts with their use and rule, switching, the all-at-limit
warning, the day's spread of helper starts (spread.py) and the history. Only labels, numbers and times: never a login, token, key or address (R5.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import share, spread, store, switching, when
from .store import PERIOD_WORDS

HISTORY_DAYS = 30
HISTORY_MAX = 50
FLAP_HOURS = 3  # this many switches within this many hours is a back and forth
FLAP_MIN = 6
# The page's words for a use window (subscription) or a limit's period (API key, helper tool).
WINDOW_WORDS = {"5h": "Last 5 hours", "week": "This week", "month": "This month", "until": "Until the date"}


def who_words(who: str) -> str:
    if who == store.USAGE:
        return "Usage"
    if who.startswith("human:"):
        return "You"
    return "A helper"


def history_rows(root: Path, at: datetime | None = None) -> list[dict]:
    """The last 30 days, newest first, at most 50 lines, each one plain sentence."""
    since = (at or datetime.now(UTC)) - timedelta(days=HISTORY_DAYS)
    out = []
    for r in store.history(root, limit=500):
        when = r.get("at")
        try:
            if store.to_time(str(when)) < since:
                continue
        except ValueError:
            continue
        what = str(r.get("what") or "").strip()
        if not what:
            continue
        label = str(r.get("label") or "Usage")
        text = what[:1].upper() + what[1:] if label == "Usage" else f"{label}: {what}"
        why = r.get("why")
        if isinstance(why, str) and why.strip():
            text += f" ({why.strip()})"
        out.append({"at": when, "who": who_words(str(r.get("who") or "")), "text": text[:300]})
        if len(out) >= HISTORY_MAX:
            break
    return out


def _bars(row: dict) -> list[dict]:
    """One bar per use window or limit: how far it is, against which limit, and when it starts again."""
    limits = {lim["period"]: lim for lim in row["rule"]["limits"]}
    bars = []
    for name, u in row.get("use", {}).items():
        lim = limits.get(name)
        bar = {"period": name, "label": WINDOW_WORDS.get(name, PERIOD_WORDS.get(name, name))}
        if "pct" in u:
            bar.update(unit="%", used=u.get("pct"), resets_at=u.get("resets_at"))
        else:
            bar.update(unit="$", used=u.get("spent"), estimated=bool(u.get("estimated")), note=u.get("note"))
            if lim and lim["period"] == "until":
                bar["until"] = lim.get("until")
        if lim:
            bar["limit"] = lim["value"]
            bar["limit_unit"] = lim["unit"]
        bars.append(bar)
    return bars


def _full_until(row: dict) -> str | None:
    """When the 5-hour window of an account that has used all of it opens again (None when it is not full)."""
    u = row.get("use", {}).get("5h") or {}
    if isinstance(u.get("pct"), (int, float)) and u["pct"] >= 100:
        return u.get("resets_at") or ""
    return None


def _state(row: dict) -> str:
    """The pill: in use now, full (the 5-hour window is used up), ready, off, or not found by the switcher."""
    if not row["on"]:
        return "off"
    if row.get("missing"):
        return "missing"
    if row.get("active"):
        return "in-use"
    if _full_until(row) is not None:
        return "full"
    return "ready"


def switch_flapping(root: Path, at: datetime | None = None) -> dict | None:
    """One warning when the account was switched many times in a short while (back and forth)."""
    since = (at or datetime.now(UTC)) - timedelta(hours=FLAP_HOURS)
    times = []
    for r in store.history(root, limit=500):
        what = str(r.get("what") or "")
        if not what.startswith(("switched to", "another program switched back")):
            continue
        try:
            t = store.to_time(str(r.get("at")))
        except ValueError:
            continue
        if t >= since:
            times.append(t)
    if len(times) < FLAP_MIN:
        return None
    return {
        "count": len(times),
        "from": min(times).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": max(times).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def build(data: dict, root: Path) -> dict:
    """The page model from `cli.gather()` (accounts with use) plus switching, the warning and the history."""
    memory = switching._read(switching.memory_path(root))
    tz, now = when.zone(root), datetime.now(UTC)
    accounts = []
    for row in data["accounts"]:
        rule = row["rule"]
        reset = when.next_reset(row, now, tz)
        accounts.append(
            {
                "id": row["id"],
                "label": row["label"],
                "type": row["type"],
                "on": row["on"],
                "order": row["order"],
                "state": _state(row),
                "bars": _bars(row),
                "limits": [dict(lim) for lim in rule["limits"]],
                "periods": list(store.allowed_periods(row)),
                "unit": store.default_unit(row),
                "ends": rule.get("ends"),
                # the workspace's wall clock ('YYYY-MM-DD' = to the end of that day); the page writes it with UI.stamp
                "ends_local": when.local(rule["ends"], tz) if rule.get("ends") else None,
                "next_reset_local": when.local(reset, tz) if reset else None,
                "full_until": _full_until(row),
                "falls_back": bool(row.get("prev")),
                "fetched_at": row.get("fetched_at"),
            }
        )
    subs = [a for a in accounts if a["type"] == "subscription"]
    on_subs = [a for a in subs if a["on"]]
    return {
        "schema": "orch.usage-page/1",
        "at": store.now(),
        "switcher": bool(data["switcher"]),
        "switching": switching.switching_on(root),
        # the loop's last look said no account is good: helpers wait soon
        "all_at_limit": bool(memory.get("all_at_limit")) and len(on_subs) > 0,
        "one_account": len(subs) <= 1,
        "flapping": switch_flapping(root),
        "warnings": list(data["warnings"]),
        "accounts": accounts,
        "spread": spread.build(root, accounts),
        "history": history_rows(root),
        "share": share.view(root, data["accounts"]),
    }
