"""What the Usage page shows (GET /api/page): accounts with their use and rule, switching, the all-at-limit
warning, the day's spread of helper starts (spread.py) and the history. Only labels, numbers and times: never a login, token, key or address (R5.2)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import computer, routing, share, spread, store, switching, when
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
    """The last 30 days, newest first, at most 50 lines, each one plain sentence. Repeated lines next to each other
    fold into one with `count` (how many) and `since` (the first one's time); `at` is the newest one's."""
    since = (at or datetime.now(UTC)) - timedelta(days=HISTORY_DAYS)
    here = computer.label(root)
    out: list[dict] = []
    keys: list[tuple] = []
    tos: list = []  # each kept line's account switched to: a fold with another one is a back and forth
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
        ws = r.get("workspace")
        if isinstance(ws, str) and ws and ws != here and what.startswith("switched to"):
            text = f"{computer.words(ws)['switched']}: {r.get('before') or '?'} → {r.get('after') or label}"
        why = r.get("why")
        if isinstance(why, str) and why.strip():
            text += f" ({why.strip()})"
        who = who_words(str(r.get("who") or ""))
        if isinstance(ws, str) and ws and ws != here and who != "Usage":
            who = f"{who} in {ws}"  # a change made in another workspace on this computer says where
        key = _fold_key(r, who, what)
        last = out[-1] if out else None
        if last is not None and keys[-1] == key:
            # ORCH-640: the same line again just before: one line that says how often, from the first one on
            last["count"] += 1
            last["since"] = when
            if key[0] == "switch" and r.get("after") != tos[-1]:
                a, b = sorted(key[2])
                last["text"] = f"Switched back and forth between {a} and {b}"
            continue
        if len(out) >= HISTORY_MAX:
            break
        out.append({"at": when, "who": who, "text": text[:300], "count": 1, "since": when})
        keys.append(key)
        tos.append(r.get("after"))
    return out


def _fold_key(r: dict, who: str, what: str) -> tuple:
    """Lines with the same key next to each other fold into one (ORCH-640). A switch between the same two accounts
    folds whichever way it went; any other line folds when only its reason differs."""
    if what.startswith(("switched to", "another program switched")):
        pair = frozenset(str(x) for x in (r.get("before"), r.get("after") or r.get("label")) if x)
        if len(pair) == 2:
            return ("switch", who, pair, str(r.get("workspace") or ""))
    return ("line", who, str(r.get("label") or ""), what, str(r.get("workspace") or ""))


# ORCH-640: the status line's words for the window that has the least left
LEFT_WORDS = {
    "5h": "in this 5-hour window",
    "week": "this week",
    "month": "this month",
    "until": "until its end",
}
LOW_LEFT = 10.0  # this share left or less: the line asks for attention


def _left(bar: dict) -> tuple[float, str, float] | None:
    """What is left in one bar: (amount, unit, share of the whole in %), or None when nothing is known."""
    used = bar.get("used")
    if not isinstance(used, (int, float)):
        return None
    if bar.get("unit") == "%":
        left = max(0.0, 100.0 - used)
        return left, "%", left
    lim = bar.get("limit")
    if bar.get("limit_unit") == "$" and isinstance(lim, (int, float)) and lim > 0:
        left = max(0.0, lim - used)
        return left, "$", left / lim * 100
    return None


def _amount(value: float, unit: str) -> str:
    if unit == "$":
        return f"${value:.2f}"
    return f"{value:.0f}%"


def status_line(accounts: list[dict], all_at_limit: bool = False) -> dict | None:
    """The one plain line at the top of the page (ORCH-640): the account in use, what is left and when it resets.

    `text` is the sentence without the time; `resets_at` is the time the page writes after it (UI.stamp, R7.5).
    `tone`: ok, attn (little left, full, over its limit, every account at its limit) or none (no account in use).
    None when the workspace has no subscription: the page's empty card says that already."""
    subs = [a for a in accounts if a["type"] == "subscription"]
    if not subs:
        return None
    cur = next((a for a in subs if a.get("active")), None)
    if cur is None:
        if all_at_limit:
            resets = sorted(
                str(b["resets_at"]) for a in subs if a["on"] for b in a["bars"] if b.get("resets_at")
            )
            return {
                "tone": "attn",
                "account": None,
                "text": "Every account is at its limit",
                "resets_at": resets[0] if resets else None,
            }
        return {"tone": "none", "account": None, "text": "No account in use right now", "resets_at": None}
    tight = None
    for b in cur["bars"]:
        left = _left(b)
        if left is None:
            continue
        rank = (left[2], str(b.get("resets_at") or "9"))
        if tight is None or rank < tight[0]:
            tight = (rank, left, b)
    head = f"{cur['label']} in use"
    if tight is None:
        return {
            "tone": "ok",
            "account": cur["label"],
            "text": f"{head} · use not read yet",
            "resets_at": None,
        }
    (_, (value, unit, share), b) = tight
    window = LEFT_WORDS.get(b["period"], str(b.get("label") or "").lower())
    low = share <= LOW_LEFT or cur["state"] in ("full", "limit") or all_at_limit
    return {
        "tone": "attn" if low else "ok",
        "account": cur["label"],
        "text": f"{head} · {_amount(value, unit)} left {window}",
        "resets_at": b.get("resets_at") or b.get("until"),
    }


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
        elif "pct" in u and switching.DEFAULT_EARLY.get(name, 100.0) < 100.0:
            # ORCH-643: no own limit for this window: Usage still switches early here (the default)
            bar["early"] = switching.DEFAULT_EARLY[name]
        bars.append(bar)
    return bars


def _full_until(row: dict) -> str | None:
    """When the 5-hour window of an account that has used all of it opens again (None when it is not full)."""
    u = row.get("use", {}).get("5h") or {}
    if isinstance(u.get("pct"), (int, float)) and u["pct"] >= 100:
        return u.get("resets_at") or ""
    return None


def _state(row: dict) -> str:
    """The pill: in use now, full (the 5-hour window is used up), ready, off, or not found by the switcher.

    build() turns a ready account that is over its own limit into "limit" (Today skips it for that)."""
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


def skill_name(v) -> str | None:
    """The name of the skill that declared a credit, or None: a plain lowercase name only; anything key-shaped
    (sk-, a long token) is dropped, so it never reaches `orch usage list` or the page."""
    if isinstance(v, str) and _SKILL.fullmatch(v) and not store._SECRETISH.search(v):
        return v
    return None


def _credit(row: dict) -> dict | None:
    """An API credit's amounts for the page (ORCH-628): what is left (the person's figure minus the spend since),
    spent today and this month, and its end. Numbers and times only; never the skill's key name, path or log."""
    if row["type"] != "api-key":
        return None
    v = row.get("credit") if isinstance(row.get("credit"), dict) else {}
    out = {k: v.get(k) for k in _CREDIT_FIELDS}
    # the credit's own end (ORCH-627 refuses a call past it); without one the rule's end
    out["ends"] = row.get("credit_ends") or row["rule"].get("ends")
    out["skill"] = skill_name(row.get("skill"))
    return out


def build(data: dict, root: Path) -> dict:
    """The page model from `cli.gather()` (accounts with use) plus switching, the warning and the history."""
    memory = switching._read(switching.memory_path(root))
    tz, now = when.zone(root), datetime.now(UTC)
    accounts, removed = [], []
    for row in data["accounts"]:
        rule = row["rule"]
        if row.get("removed"):  # kept with its rule, amount left and history; the page offers Bring back
            removed.append({"id": row["id"], "label": row["label"], "type": row["type"]})
            continue
        reset = when.next_reset(row, now, tz)
        accounts.append(
            {
                "id": row["id"],
                "label": row["label"],
                "type": row["type"],
                "on": row["on"],
                "active": bool(row.get("active")),  # the account helpers use now (the status line, ORCH-640)
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
                # the workspace's wall clock ('YYYY-MM-DD' = to the end of that day); the page writes it with UI.stamp
                "ends_local": when.local(rule["ends"], tz) if rule.get("ends") else None,
                "next_reset_local": when.local(reset, tz) if reset else None,
                "full_until": _full_until(row),
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
        acc = accounts[-1]
        # ORCH-1468: one state per account across the page: a ready account Today skips for its limit says so here too
        # ORCH-1837: also the account in use (Today skipped ALTYCA for its limit while Subscriptions said In use now)
        if acc["state"] in ("ready", "in-use") and spread.skipped(acc):
            acc["state"] = "limit"
    subs = [a for a in accounts if a["type"] == "subscription"]
    on_subs = [a for a in subs if a["on"]]
    all_at_limit = bool(memory.get("all_at_limit")) and len(on_subs) > 0
    return {
        "schema": "orch.usage-page/1",
        "at": store.now(),
        "switcher": bool(data["switcher"]),
        "switching": switching.switching_on(root),
        # ORCH-943: the one workspace on this computer that switches (None: the workspace keeps Usage alone)
        "switcher_owner": computer.view(root, computer.shared_dir(root)),
        # the loop's last look said no account is good: helpers wait soon
        "all_at_limit": all_at_limit,
        "one_account": len(subs) <= 1,
        "flapping": switch_flapping(root),
        # the page draws its own banner for "every account is at its limit": no second box with the same sentence
        "warnings": [w for w in data["warnings"] if not (all_at_limit and w == switching.ALL_AT_LIMIT_ALERT)],
        # kinds of work whose starts wait now (routing): one line each, in the kinds' order
        "waiting": [
            {"kind": store.KIND_WORDS[k], "why": h.get("why") or "", "tickets": len(h.get("tickets") or [])}
            for k, h in sorted(routing.held(root).items(), key=lambda kv: store.KINDS.index(kv[0]))
        ],
        "accounts": accounts,
        "status": status_line(accounts, all_at_limit),
        "removed": removed,
        "spread": spread.build(root, accounts),
        # one money limit over every account of a provider (one row per provider with a money account)
        "together": _together(data, accounts),
        "providers": [{"id": p, "label": store.provider_words(p)} for p in store.PROVIDERS],
        "history": history_rows(root),
        "share": share.view(root, data["accounts"]),
        "prepare": data.get("prepare"),  # preparing tickets on Save: used today of the daily limit (ORCH-741)
    }
