"""Usage on disk, in .orch/addons/usage/: `accounts.json` (accounts and their rules) and `history.jsonl` (append-only).

Plain files a person can read and fix by hand. Only labels, numbers, times and rules: never a login, token, key or
address. Schema `orch.usage/1`:

    {"schema": "orch.usage/1", "accounts": [{
        "id": "a_xxxxxx", "label": "...", "type": "subscription|api-key|helper-tool", "provider": "...",
        "source": {"reader": "cswap", "key": "c_..."},          # how a reader finds it; never a secret
        "on": true, "order": 1,
        "rule": {"limits": [{"value": 95, "unit": "%", "period": "5h"}], "for": [], "ends": null},
        "prev": null}]}                                          # the rule a temporary rule falls back to

History line: {"at", "who" (human:<name> | agent:<name> | usage), "what", "account", "before", "after"}.
"""

from __future__ import annotations

import copy
import json
import os
import re
import secrets
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = "orch.usage/1"
TYPES = ("subscription", "api-key", "helper-tool")
PERIODS = ("5h", "week", "month", "until")
UNITS = ("%", "$")
KINDS = (
    "lead",
    "code",
    "reviews",
    "builds",
    "scripts",
    "helpers",
)  # stage 2 fills "for"; kept in the schema now
PERIOD_WORDS = {"5h": "5 hours", "week": "week", "month": "month", "until": "until a date"}
MAX_LIMITS = 2
USAGE = "usage"

_ID = re.compile(r"a_[a-z0-9]{6}")
_ACTOR = re.compile(r"(human|agent):[^\s<>]{1,64}")
_TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


class Refused(Exception):
    """Plain words for the person; the CLI prints them and exits 2."""


def usage_dir(root: Path) -> Path:
    return root / ".orch" / "addons" / "usage"


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_time(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def valid_actor(who: str) -> bool:
    return who == USAGE or bool(_ACTOR.fullmatch(who))


def empty_rule() -> dict:
    return {"limits": [], "for": [], "ends": None}


# ---------------------------------------------------------------- reading and checking


def _check_limit(lim) -> bool:
    if not isinstance(lim, dict):
        return False
    v = lim.get("value")
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not v > 0:
        return False
    if lim.get("unit") not in UNITS or lim.get("period") not in PERIODS:
        return False
    return not (lim["period"] == "until" and not _TIME.fullmatch(str(lim.get("until", ""))))


def _check_rule(rule) -> bool:
    if not isinstance(rule, dict):
        return False
    limits, kinds, ends = rule.get("limits"), rule.get("for", []), rule.get("ends")
    if not isinstance(limits, list) or len(limits) > MAX_LIMITS or not all(_check_limit(x) for x in limits):
        return False
    if len({x["period"] for x in limits}) != len(limits):
        return False
    if not isinstance(kinds, list) or not all(k in KINDS for k in kinds):
        return False
    return ends is None or bool(_TIME.fullmatch(str(ends)))


def _check_account(a) -> bool:
    if not isinstance(a, dict) or not _ID.fullmatch(str(a.get("id", ""))):
        return False
    if a.get("type") not in TYPES or not isinstance(a.get("label"), str) or not a["label"].strip():
        return False
    if (
        not isinstance(a.get("on"), bool)
        or not isinstance(a.get("order"), int)
        or isinstance(a["order"], bool)
    ):
        return False
    if not isinstance(a.get("source", {}), dict):
        return False
    return _check_rule(a.get("rule")) and (a.get("prev") is None or _check_rule(a["prev"]))


def load(root: Path) -> dict:
    """{"accounts": [...] (in order), "unreadable": n}. A bad file or row is counted, never rewritten here."""
    p = usage_dir(root) / "accounts.json"
    out = {"accounts": [], "unreadable": 0}
    if not p.exists():
        return out
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        out["unreadable"] = 1
        return out
    if (
        not isinstance(data, dict)
        or data.get("schema") != SCHEMA
        or not isinstance(data.get("accounts"), list)
    ):
        out["unreadable"] = 1
        return out
    for a in data["accounts"]:
        if _check_account(a):
            a.setdefault("source", {})
            a.setdefault("provider", "")
            a.setdefault("prev", None)
            a["rule"].setdefault("for", [])
            out["accounts"].append(a)
        else:
            out["unreadable"] += 1
    out["accounts"].sort(key=lambda a: (a["order"], a["label"].lower()))
    return out


def history(root: Path, account: str | None = None, limit: int = 200) -> list[dict]:
    p = usage_dir(root) / "history.jsonl"
    if not p.exists():
        return []
    rows = []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and (account is None or r.get("account") == account):
            rows.append(r)
    return rows[-limit:][::-1]  # newest first


# ---------------------------------------------------------------- writing


@contextmanager
def _lock(root: Path):
    d = usage_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    lock = d / ".lock"
    deadline = time.monotonic() + 10
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 30:  # left by a crashed writer
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise Refused("Usage is busy saving another change. Try again in a moment.") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _write_accounts(root: Path, accounts: list[dict]) -> None:
    d = usage_dir(root)
    body = json.dumps({"schema": SCHEMA, "accounts": accounts}, indent=1, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".accounts.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, d / "accounts.json")
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _append_history(root: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(usage_dir(root) / "history.jsonl", "a", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def _line(who: str, what: str, account: dict, before, after) -> dict:
    return {
        "at": now(),
        "who": who,
        "what": what,
        "account": account["id"],
        "label": account["label"],
        "before": before,
        "after": after,
    }


@contextmanager
def change(root: Path):
    """Read, change, write: yields (accounts, history_rows). Writes only when something changed."""
    with _lock(root):
        d = load(root)
        if d["unreadable"] and (usage_dir(root) / "accounts.json").exists() and not d["accounts"]:
            raise Refused(
                "The Usage accounts file could not be read. Fix or move .orch/addons/usage/accounts.json, then try again."
            )
        accounts = d["accounts"]
        before = json.dumps(accounts, sort_keys=True)
        rows: list[dict] = []
        yield accounts, rows
        _renumber(accounts)
        if json.dumps(accounts, sort_keys=True) != before or rows:
            _write_accounts(root, accounts)
            _append_history(root, rows)


def _renumber(accounts: list[dict]) -> None:
    accounts.sort(key=lambda a: (a["order"], a["label"].lower()))
    for i, a in enumerate(accounts, 1):
        a["order"] = i


def new_id(accounts: list[dict]) -> str:
    taken = {a["id"] for a in accounts}
    while True:
        i = "a_" + "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(6))
        if i not in taken:
            return i


# ---------------------------------------------------------------- the changes


def find(accounts: list[dict], ref: str) -> dict:
    ref = (ref or "").strip()
    for a in accounts:
        if a["id"] == ref:
            return a
    hits = [a for a in accounts if a["label"].lower() == ref.lower()]
    if not hits:
        hits = [a for a in accounts if a["label"].lower().startswith(ref.lower())] if ref else []
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise Refused(f"No account called '{ref}'. Run `orch usage list` to see the accounts.")
    raise Refused(f"More than one account matches '{ref}'. Use its full name or id from `orch usage list`.")


def expire(accounts: list[dict], rows: list[dict], at: datetime | None = None) -> None:
    """A temporary rule whose end has passed falls back to the rule before it."""
    at = at or datetime.now(UTC)
    for a in accounts:
        ends = a["rule"].get("ends")
        if ends and to_time(ends) <= at:
            old = copy.deepcopy(a["rule"])
            a["rule"] = copy.deepcopy(a["prev"]) if a.get("prev") else empty_rule()
            a["rule"]["ends"] = None
            a["prev"] = None
            rows.append(_line(USAGE, "rule ended", a, old, copy.deepcopy(a["rule"])))


def sync_found(accounts: list[dict], rows: list[dict], found, provider: str, reader: str) -> None:
    """Add subscriptions the reader sees that Usage does not know yet (on, last in order, no limits)."""
    known = {a.get("source", {}).get("key") for a in accounts}
    for f in found:
        if f.key in known:
            continue
        a = {
            "id": new_id(accounts),
            "label": f.label,
            "type": "subscription",
            "provider": provider,
            "source": {"reader": reader, "key": f.key},
            "on": True,
            "order": len(accounts) + 1,
            "rule": empty_rule(),
            "prev": None,
        }
        accounts.append(a)
        known.add(f.key)
        rows.append(_line(USAGE, "account found", a, None, {"label": a["label"], "order": a["order"]}))


def _rule_change(a: dict, rows: list[dict], who: str, what: str, new_rule: dict, end: str | None) -> None:
    old = copy.deepcopy(a["rule"])
    if not _check_rule(new_rule):
        raise Refused("That rule cannot be saved. Run `orch usage list` and try again.")
    if end:
        new_rule["ends"] = end
    if new_rule == old:
        return
    if not old.get("ends"):
        a["prev"] = old  # the rule before this change; a temporary rule falls back to it
    a["rule"] = new_rule
    rows.append(_line(who, what, a, old, copy.deepcopy(new_rule)))


def default_unit(a: dict) -> str:
    return "%" if a["type"] == "subscription" else "$"


def allowed_periods(a: dict) -> tuple[str, ...]:
    return ("5h", "week") if a["type"] == "subscription" else ("week", "month", "until")


def set_limit(
    a: dict,
    rows: list[dict],
    who: str,
    value: float | None,
    unit: str | None,
    period: str | None,
    until: str | None,
    end: str | None,
) -> None:
    rule = copy.deepcopy(a["rule"])
    limits = rule["limits"]
    if period is None:
        if len(limits) == 1:
            period = limits[0]["period"]
        elif not limits:
            period = "week" if a["type"] == "subscription" else "month"
        else:
            raise Refused(
                f"{a['label']} has two limits. Say which one: --period "
                + " or --period ".join(x["period"] for x in limits)
                + "."
            )
    if period not in allowed_periods(a):
        raise Refused(
            f"A limit of {a['label']} counts over "
            + " or ".join(PERIOD_WORDS[p] for p in allowed_periods(a))
            + "."
        )
    unit = unit or default_unit(a)
    if a["type"] == "subscription" and unit != "%":
        raise Refused("A subscription limit is a percent, for example 90%.")
    if unit == "%" and value is not None and value > 100:
        raise Refused("A percent limit is at most 100%.")
    if period == "until" and value is not None and not until:
        raise Refused("Say until when it counts: --until YYYY-MM-DD.")
    same = [x for x in limits if x["period"] == period]
    if value is None:
        if not same:
            raise Refused(f"{a['label']} has no {PERIOD_WORDS[period]} limit. Nothing changed.")
        limits.remove(same[0])
        what = f"limit removed ({PERIOD_WORDS[period]})"
    else:
        lim = {"value": value, "unit": unit, "period": period}
        if period == "until":
            lim["until"] = until
        if same:
            limits[limits.index(same[0])] = lim
        elif len(limits) >= MAX_LIMITS:
            raise Refused(
                f"{a['label']} already has two limits. Change one of them or remove one with 'none'."
            )
        else:
            limits.append(lim)
        what = f"limit {fmt_value(value, unit)} ({PERIOD_WORDS[period]})"
    limits.sort(key=lambda x: PERIODS.index(x["period"]))
    _rule_change(a, rows, who, what, rule, end)


def set_period(
    a: dict, rows: list[dict], who: str, new: str, of: str | None, until: str | None, end: str | None
) -> None:
    rule = copy.deepcopy(a["rule"])
    limits = rule["limits"]
    if not limits:
        raise Refused(
            f"{a['label']} has no limit yet. Set one first: orch usage limit {a['label']} <number>."
        )
    if of is None:
        if len(limits) > 1:
            raise Refused(
                f"{a['label']} has two limits. Say which one: --of "
                + " or --of ".join(x["period"] for x in limits)
                + "."
            )
        of = limits[0]["period"]
    hit = [x for x in limits if x["period"] == of]
    if not hit:
        raise Refused(f"{a['label']} has no {PERIOD_WORDS.get(of, of)} limit.")
    if new not in allowed_periods(a):
        raise Refused(
            f"A limit of {a['label']} counts over "
            + " or ".join(PERIOD_WORDS[p] for p in allowed_periods(a))
            + "."
        )
    if new != of and any(x["period"] == new for x in limits):
        raise Refused(f"{a['label']} already has a {PERIOD_WORDS[new]} limit.")
    if new == "until" and not until:
        raise Refused("Say until when it counts: --until YYYY-MM-DD.")
    lim = hit[0]
    lim["period"] = new
    if new == "until":
        lim["until"] = until
    else:
        lim.pop("until", None)
    limits.sort(key=lambda x: PERIODS.index(x["period"]))
    _rule_change(a, rows, who, f"counts over {PERIOD_WORDS[new]}", rule, end)


def set_end(a: dict, rows: list[dict], who: str, end: str | None) -> None:
    """End the current rule at a time; it then falls back to the rule before its last change. None: no end."""
    old = copy.deepcopy(a["rule"])
    if end is None:
        if not old.get("ends"):
            return
        a["rule"]["ends"] = None
        rows.append(_line(who, "rule kept, no end", a, old, copy.deepcopy(a["rule"])))
        return
    a["rule"]["ends"] = end
    if a["rule"] != old:
        rows.append(_line(who, "rule ends", a, old, copy.deepcopy(a["rule"])))


def set_on(a: dict, rows: list[dict], who: str, on: bool) -> None:
    if a["on"] == on:
        return
    a["on"] = on
    rows.append(_line(who, "turned on" if on else "turned off", a, not on, on))


def set_order(accounts: list[dict], a: dict, rows: list[dict], who: str, place: int) -> None:
    _renumber(accounts)
    place = max(1, min(place, len(accounts)))
    old = a["order"]
    if place == old:
        return
    accounts.remove(a)
    accounts.insert(place - 1, a)
    for i, x in enumerate(accounts, 1):
        x["order"] = i
    rows.append(_line(who, f"order {old} to {place}", a, old, place))


def fmt_value(value: float, unit: str) -> str:
    n = f"{value:g}"
    return f"${n}" if unit == "$" else f"{n}%"
