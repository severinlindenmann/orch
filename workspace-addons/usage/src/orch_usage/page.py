"""What the Usage page shows (GET /api/page): accounts with their use and rule, switching, the all-at-limit
warning and the history. Only labels, numbers and times: never a login, token, key or address (R5.2)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import routing, store, switching
from .store import PERIOD_WORDS

HISTORY_DAYS = 30
HISTORY_MAX = 50
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
            elif lim and lim["period"] == "month":  # when the month's credit starts again (its reset day)
                bar["resets_at"] = store.utc_text(store.month_window(lim, datetime.now(UTC))[1])
        if lim:
            bar["limit"] = lim["value"]
            bar["limit_unit"] = lim["unit"]
        bars.append(bar)
    return bars


def _state(row: dict) -> str:
    """The pill: in use now, ready, off, or not found by the switcher."""
    if not row["on"]:
        return "off"
    if row.get("missing"):
        return "missing"
    if row.get("active"):
        return "in-use"
    return "ready"


def _together(data: dict, accounts: list[dict]) -> list[dict]:
    have = {t["provider"]: t for t in data.get("together") or []}
    providers = []
    for a in accounts:
        if a["type"] in store.MONEY_TYPES and a["provider"] and a["provider"] not in providers:
            providers.append(a["provider"])
    out = []
    for p in providers:
        t = have.get(p)
        row = {
            "provider": p,
            "label": store.together_label(p),
            "limit": None,
            "spent": None,
            "resets_at": None,
        }
        if t:
            row.update(limit=t["limit"]["value"], period=t["limit"]["period"], spent=t["spent"])
            row["resets_at"] = t.get("resets_at")
        row["accounts"] = [
            a["label"] for a in accounts if a["type"] in store.MONEY_TYPES and a["provider"] == p
        ]
        out.append(row)
    return out


_SKILL = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_CREDIT_FIELDS = ("left", "set", "set_at", "spent_since", "spent_today", "spent_month", "over")


def _credit(row: dict) -> dict | None:
    """An API credit's amounts for the page (ORCH-628): what is left (the person's figure minus the spend since),
    spent today and this month, and its end. Numbers and times only; never the skill's key name, path or log."""
    if row["type"] != "api-key":
        return None
    v = row.get("credit") if isinstance(row.get("credit"), dict) else {}
    out = {k: v.get(k) for k in _CREDIT_FIELDS}
    # the credit's own end (ORCH-627 refuses a call past it); without one the rule's end
    out["ends"] = row.get("credit_ends") or row["rule"].get("ends")
    skill = row.get("skill")
    # a skill's name only: anything key-shaped (sk-, a long token) never reaches the page
    good = isinstance(skill, str) and _SKILL.fullmatch(skill) and not store._SECRETISH.search(skill)
    out["skill"] = skill if good else None
    return out


def build(data: dict, root: Path) -> dict:
    """The page model from `cli.gather()` (accounts with use) plus switching, the warning and the history."""
    memory = switching._read(switching.memory_path(root))
    accounts, removed = [], []
    for row in data["accounts"]:
        rule = row["rule"]
        if row.get("removed"):  # kept with its rule, amount left and history; the page offers Bring back
            removed.append({"id": row["id"], "label": row["label"], "type": row["type"]})
            continue
        accounts.append(
            {
                "id": row["id"],
                "label": row["label"],
                "type": row["type"],
                "on": row["on"],
                "order": row["order"],
                "state": _state(row),
                "missing": bool(row.get("missing")),  # gone from the switcher, also while it is off
                "bars": _bars(row),
                "limits": [dict(lim) for lim in rule["limits"]],
                "periods": list(store.allowed_periods(row)),
                "unit": store.default_unit(row),
                # an API credit or helper tool ends itself (credit_ends, ORCH-626); a subscription's rule ends
                "ends": (row.get("credit_ends") if row["type"] in store.MONEY_TYPES else None)
                or rule.get("ends"),
                "for": list(rule.get("for") or []),
                "model": rule.get("model"),
                "provider": row.get("provider") or "",
                "provider_label": store.provider_words(row.get("provider") or "")
                if row.get("provider")
                else "",
                "credit": _credit(row),
                "removable": row["type"] in store.MONEY_TYPES,
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
        "warnings": list(data["warnings"]),
        # kinds of work whose starts wait now (routing): one line each, in the kinds' order
        "waiting": [
            {"kind": store.KIND_WORDS[k], "why": h.get("why") or "", "tickets": len(h.get("tickets") or [])}
            for k, h in sorted(routing.held(root).items(), key=lambda kv: store.KINDS.index(kv[0]))
        ],
        "accounts": accounts,
        "removed": removed,
        # one money limit over every account of a provider (one row per provider with a money account)
        "together": _together(data, accounts),
        "providers": [{"id": p, "label": store.provider_words(p)} for p in store.PROVIDERS],
        "history": history_rows(root),
    }
