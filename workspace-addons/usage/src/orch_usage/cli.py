"""orch usage list|history|limit|period|order|on|off|end (store: store.py; readers: readers/)."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import store
from .readers import credit_reader, cswap
from .store import PERIOD_WORDS, Refused

SAVED = "Saved. It is in the history (orch usage history)."
NO_SWITCHER = (
    "The account switcher is not installed: Usage shows the accounts it knows and warns, but does not switch."
)


def _root(start: str) -> Path:
    p = Path(start).absolute()
    for q in (p, *p.parents):
        if (q / ".orch").is_dir():
            return q
    raise Refused("No orch workspace here. Run orch init first, or go to your workspace folder.")


def _actor(explicit: str | None) -> str:
    if explicit:
        if not store.valid_actor(explicit) or explicit == store.USAGE:
            raise Refused(f"'{explicit}' is not a valid name. Use agent:<tool> or human:<name>.")
        return explicit
    inside_run = os.environ.get("ORCH_RUN") or os.environ.get("ORCH_AGENT")
    try:
        from orch import tickets

        tool = tickets.agent_tool()
    except Exception:  # noqa: BLE001 - no core to ask: fall back to the environment
        tool = None
    if inside_run or tool:
        name = re.sub(r"[^A-Za-z0-9_.@-]", "_", os.environ.get("ORCH_AGENT") or tool or "helper")[:64]
        return f"agent:{name or 'helper'}"
    try:
        import getpass

        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return "human:" + (re.sub(r"[^A-Za-z0-9_.@-]", "_", user)[:64] or "user")


# ---------------------------------------------------------------- input words


def parse_value(text: str) -> tuple[float | None, str | None]:
    """'90', '90%', '$100', '100$', 'none' -> (value, unit or None). Any positive number."""
    t = (text or "").strip().replace(" ", "")
    if t.lower() in ("none", "off", "no"):
        return None, None
    unit = None
    if t.endswith("%"):
        unit, t = "%", t[:-1]
    elif t.startswith("$"):
        unit, t = "$", t[1:]
    elif t.endswith("$"):
        unit, t = "$", t[:-1]
    try:
        v = float(t)
    except ValueError:
        raise Refused(f"'{text}' is not a number. Write a limit like 90%, $100 or none.") from None
    if not (v > 0 and math.isfinite(v)):
        raise Refused("A limit is a number above 0. To take a limit away, write none.")
    return (int(v) if v.is_integer() else round(v, 4)), unit


_PERIOD_IN = {
    "5h": "5h",
    "5hours": "5h",
    "5-hours": "5h",
    "five-hours": "5h",
    "week": "week",
    "weekly": "week",
    "7d": "week",
    "month": "month",
    "monthly": "month",
    "until": "until",
    "date": "until",
}


def parse_period(text: str | None) -> str | None:
    if text is None:
        return None
    p = _PERIOD_IN.get(text.strip().lower().replace(" ", ""))
    if not p:
        raise Refused(f"'{text}' is not a period. Use 5h, week, month or until.")
    return p


def parse_time(text: str, now: datetime | None = None) -> str:
    """YYYY-MM-DD (to the end of that day, this computer's time), YYYY-MM-DDTHH:MM (this computer's time), or
    a full time with Z or an offset. Must be in the future. Returns UTC 'YYYY-MM-DDTHH:MM:SSZ'."""
    now = now or datetime.now(UTC)
    t = (text or "").strip()
    try:
        if re.fullmatch(r"\d{4}-\d\d-\d\d", t):
            d = datetime.strptime(t, "%Y-%m-%d") + timedelta(days=1)
            when = d.astimezone()  # naive -> this computer's zone
        else:
            when = datetime.fromisoformat(t)
            if when.tzinfo is None:
                when = when.astimezone()
    except ValueError:
        raise Refused(f"'{text}' is not a date. Write it like 2026-11-20 or 2026-11-20T18:00.") from None
    when = when.astimezone(UTC).replace(microsecond=0)
    if when <= now:
        raise Refused(f"{text} has already passed. Pick a time in the future.")
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- reading use


def _period_start(period: str, lim: dict, at: datetime) -> str | None:
    if period == "month":
        local = at.astimezone()
        return (
            local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            .astimezone(UTC)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    if period == "week":
        return (at - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return lim.get("since")


def gather(root: Path) -> dict:
    """Sync what the readers see, let ended rules fall back, and return accounts with their use."""
    warnings: list[str] = []
    found = None
    try:
        found = cswap.read()
    except cswap.ReaderError as e:
        warnings.append(str(e))
    if found is None and not warnings:
        warnings.append(NO_SWITCHER)
    with store.change(root) as (accounts, rows):
        store.expire(accounts, rows)
        if found:
            store.sync_found(accounts, rows, found, provider="anthropic", reader="cswap")
    d = store.load(root)
    by_key = {f.key: f for f in (found or [])}
    at = datetime.now(UTC)
    out = []
    for a in d["accounts"]:
        row = {k: v for k, v in a.items() if k != "source"}
        row["reader"] = a.get("source", {}).get("reader", "none")
        use: dict = {}
        src = a.get("source", {})
        if a["type"] == "subscription":
            f = by_key.get(src.get("key"))
            if f:
                row["active"] = f.active
                use = {name: asdict(w) for name, w in f.windows.items()}
                row["fetched_at"] = f.fetched_at
            else:
                row["active"] = False
                row["missing"] = found is not None
        else:
            reader = credit_reader(src.get("reader", "none")) or credit_reader("none")
            for lim in a["rule"]["limits"] or [{"period": "month"}]:
                c = reader(src, _period_start(lim["period"], lim, at))
                use[lim["period"]] = asdict(c)
        row["use"] = use
        out.append(row)
    if d["unreadable"]:
        warnings.append(
            f"{d['unreadable']} account(s) in .orch/addons/usage could not be read and are skipped."
        )
    return {"accounts": out, "switcher": found is not None, "warnings": warnings}


# ---------------------------------------------------------------- output


def _rule_text(rule: dict) -> str:
    parts = []
    for lim in rule["limits"]:
        p = PERIOD_WORDS[lim["period"]]
        if lim["period"] == "until":
            p = f"until {lim['until'][:10]}"
        parts.append(
            f"{store.fmt_value(lim['value'], lim['unit'])} per {p}"
            if lim["period"] != "until"
            else f"{store.fmt_value(lim['value'], lim['unit'])} {p}"
        )
    text = ", ".join(parts) or "no limit"
    if rule.get("ends"):
        text += f" (ends {rule['ends'][:16].replace('T', ' ')} UTC)"
    return text


def _use_text(row: dict) -> str:
    bits = []
    for name, u in row["use"].items():
        word = PERIOD_WORDS.get(name, name)
        if "pct" in u:
            if u["pct"] is not None:
                bits.append(f"{word} {u['pct']:g}% used")
        elif u.get("spent") is not None:
            bits.append(f"{word} ${u['spent']:g} spent" + (" (estimated)" if u.get("estimated") else ""))
        elif u.get("note"):
            bits.append(u["note"])
    return "; ".join(bits)


def _emit(args, data: dict, text: str) -> int:
    print(json.dumps(data, ensure_ascii=False) if args.json else text)
    return 0


def _fail(args, msg: str) -> int:
    if args.json:
        print(json.dumps({"error": msg}, ensure_ascii=False))
    else:
        print(f"Refused: {msg}", file=sys.stderr)
    return 2


# ---------------------------------------------------------------- commands


def run(args) -> int:
    root = _root(args.dir)
    cmd = args.cmd
    if cmd == "list":
        data = gather(root)
        if args.json:
            print(json.dumps(data, ensure_ascii=False))
            return 0
        lines = []
        for r in data["accounts"]:
            state = "on" if r["on"] else "off"
            if r.get("active"):
                state += ", in use"
            lines.append(f"{r['order']}. {r['label']} ({state}): {_rule_text(r['rule'])}")
            use = _use_text(r)
            if use:
                lines.append(f"   {use}")
        if not lines:
            lines = ["No accounts yet."]
        lines += [f"Warning: {w}" for w in data["warnings"]]
        lines.append("Next: orch usage limit <account> <number>  (or period / order / on / off / end)")
        print("\n".join(lines))
        return 0
    if cmd == "history":
        rows = store.history(root)
        if args.account:
            acc = store.find(store.load(root)["accounts"], args.account)
            rows = [r for r in rows if r.get("account") == acc["id"]]
        if args.json:
            print(json.dumps({"history": rows}, ensure_ascii=False))
            return 0
        out = [
            f"{r.get('at', '')[:16].replace('T', ' ')}  {r.get('label', r.get('account'))}: {r.get('what')}"
            f"  (by {str(r.get('who', '')).split(':', 1)[-1]})"
            for r in rows
        ] or ["No changes yet."]
        print("\n".join(out))
        return 0

    who = _actor(args.by)
    end = parse_time(args.end) if getattr(args, "end", None) else None
    with store.change(root) as (accounts, rows):
        store.expire(accounts, rows)
        a = store.find(accounts, args.account)
        if cmd == "limit":
            value, unit = parse_value(args.value)
            until = parse_time(args.until) if args.until else None
            store.set_limit(a, rows, who, value, unit, parse_period(args.period), until, end)
            if until:
                for lim in a["rule"]["limits"]:
                    if lim["period"] == "until" and "since" not in lim:
                        lim["since"] = store.now()
        elif cmd == "period":
            until = parse_time(args.until) if args.until else None
            store.set_period(a, rows, who, parse_period(args.new), parse_period(args.of), until, end)
            for lim in a["rule"]["limits"]:
                if lim["period"] == "until" and "since" not in lim:
                    lim["since"] = store.now()
        elif cmd == "order":
            store.set_order(accounts, a, rows, who, args.place)
        elif cmd in ("on", "off"):
            store.set_on(a, rows, who, cmd == "on")
        elif cmd == "end":
            when = None if args.when.strip().lower() in ("none", "never", "no") else parse_time(args.when)
            store.set_end(a, rows, who, when)
        else:
            raise Refused(f"Unknown command {cmd}.")
        changed = bool(rows)
        result = {k: v for k, v in a.items() if k != "source"}
    nxt = SAVED if changed else "Already like that. Nothing changed."
    if changed and cmd in ("limit", "period", "end") and result["rule"].get("ends"):
        nxt = SAVED + " The rule falls back to the one before it when it ends."
    return _emit(
        args,
        {"account": result, "changed": changed, "next": nxt},
        f"{result['label']}: {_rule_text(result['rule'])}, {'on' if result['on'] else 'off'}, "
        f"place {result['order']}.\n{nxt}",
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="orch usage")
    ap.add_argument("--dir", default=os.environ.get("ORCH_ROOT", "."))
    sub = ap.add_subparsers(dest="cmd", required=True)

    def p(name, **kw):
        s = sub.add_parser(name, **kw)
        s.add_argument("--json", action="store_true")
        return s

    p("list")
    s = p("history")
    s.add_argument("--account")
    s = p("limit")
    s.add_argument("account")
    s.add_argument("value")
    s.add_argument("--period")
    s.add_argument("--until")
    s.add_argument("--end")
    s.add_argument("--by")
    s = p("period")
    s.add_argument("account")
    s.add_argument("new")
    s.add_argument("--of")
    s.add_argument("--until")
    s.add_argument("--end")
    s.add_argument("--by")
    s = p("order")
    s.add_argument("account")
    s.add_argument("place", type=int)
    s.add_argument("--by")
    for name in ("on", "off"):
        s = p(name)
        s.add_argument("account")
        s.add_argument("--by")
    s = p("end")
    s.add_argument("account")
    s.add_argument("when")
    s.add_argument("--by")
    args = ap.parse_args(argv)
    args.json = bool(getattr(args, "json", False)) or "--json" in (argv if argv is not None else sys.argv)
    try:
        return run(args)
    except Refused as e:
        return _fail(args, str(e))
