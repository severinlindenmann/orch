"""orch usage list|needs|seen|history|limit|period|order|on|off|end|left|spent|for|model|together|add|remove|restore|ask|
share|pick|switching|act|run|start|stop|status|before-start
(store: store.py; readers: readers/; early switching: switching.py; background process: service.py)."""

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

from . import left, page, picker, routing, store, switching, when
from . import share as share_mod
from .readers import cswap
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


def _helper_run() -> bool:
    """Is this command run by a helper (inside an orch run or a helper tool), whatever --by says?"""
    if os.environ.get("ORCH_RUN") or os.environ.get("ORCH_AGENT"):
        return True
    try:
        from orch import tickets

        return bool(tickets.agent_tool())
    except Exception:  # noqa: BLE001 - no core to ask: the environment said no
        return False


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


def parse_money(text: str, *, allow_none: bool = True) -> float | None:
    """'$74', '74', '74.50', '0' -> dollars; 'none' -> None (take the amount away). Never a percent."""
    t = (text or "").strip().replace(" ", "").replace(",", "")
    if allow_none and t.lower() in ("none", "unset", "no"):
        return None
    if t.endswith("%"):
        raise Refused("An API credit counts in dollars, like $74, not in %.")
    t = t.removeprefix("$").removesuffix("$")
    try:
        v = float(t)
    except ValueError:
        raise Refused(f"'{text}' is not an amount. Write it like $74 or 0.") from None
    if not (math.isfinite(v) and v >= 0):
        raise Refused("An amount is a number of dollars, 0 or more.")
    return int(v) if v.is_integer() else round(v, 6)


def find_credit(accounts: list[dict], ref: str, provider: str | None = None) -> dict:
    """An API credit or helper tool by its label, id or the name its credit skill uses (`main`, `key-1`)."""
    money = [a for a in accounts if a["type"] in store.MONEY_TYPES]
    if provider:
        money = [a for a in money if a.get("provider") == provider.strip().lower()]
    try:
        return store.find(money, ref)
    except Refused:
        hits = [a for a in money if (ref or "").strip() in store.credit_names(a)]
        if len(hits) == 1:
            return hits[0]
        if hits:
            raise Refused(
                f"More than one credit uses the name '{ref}'. Add --provider, or use its label from orch usage list."
            ) from None
        raise


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


# ---------------------------------------------------------------- share words (ORCH-657)

_KIND_IN = {
    "lead": "lead",
    "leads": "lead",
    "code": "code",
    "coding": "code",
    "review": "reviews",
    "reviews": "reviews",
    "challenge": "reviews",
    "challenges": "reviews",
    "build": "builds",
    "builds": "builds",
    "script": "scripts",
    "scripts": "scripts",
    "helper": "helpers",
    "helpers": "helpers",
}
_AHEAD_IN = {
    "api": "api",
    "credit": "api",
    "api-credit": "api",
    "apicredit": "api",
    "tool": "tool",
    "helper-tool": "tool",
    "both": "both",
    "api-then-tool": "both",
    "none": "none",
    "no": "none",
    "subscriptions": "none",
    "subscription": "none",
    "stay": "none",
}


def parse_pct(text: str) -> int:
    t = (text or "").strip().replace(" ", "").rstrip("%")
    if not t.isdigit() or not share_mod.MIN_PCT <= int(t) <= share_mod.MAX_PCT:
        raise Refused(f"'{text}' is not a percent of the week. Write a whole number from 10 to 100, like 70.")
    return int(t)


def parse_day(text: str) -> str:
    t = (text or "").strip().lower()
    hits = [d for d in share_mod.DAYS if len(t) >= 2 and d.startswith(t)]
    if len(hits) != 1:
        raise Refused(f"'{text}' is not a weekday. Write it like wed or wednesday.")
    return hits[0]


def parse_kinds(text: str) -> list[str]:
    t = (text or "").strip().lower()
    if t in ("none", "nothing", "no", ""):
        return []
    out = []
    for w in re.split(r"[,\s]+|\band\b", t):
        if not w:
            continue
        k = _KIND_IN.get(w)
        if not k:
            raise Refused(f"'{w}' is not a kind of work. Use " + ", ".join(store.KINDS) + ", or none.")
        if k not in out:
            out.append(k)
    return out


def parse_one_in(text: str) -> int:
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    if t in ("none", "no", "0", "never"):
        return 0
    if t in ("all", "1", "every", "1 in 1", "one in 1"):
        return 1
    m = re.fullmatch(r"(?:(?:1|one) in )?(\d{1,2})", t)
    if not m or not 2 <= int(m.group(1)) <= share_mod.MAX_ONE_IN:
        raise Refused(
            f"'{text}' is not a share of Code tickets. Write 'one in 4' (2 to {share_mod.MAX_ONE_IN}), all or none."
        )
    return int(m.group(1))


def parse_ahead(text: str) -> str:
    a = _AHEAD_IN.get((text or "").strip().lower().replace(" ", "-"))
    if not a:
        raise Refused(
            f"'{text}' is not a choice. Use api, tool (the helper tool), both (API credit, then the helper tool) or none."
        )
    return a


def parse_dollars(text: str) -> float:
    t = (text or "").strip().replace(" ", "").lower()
    if t in ("none", "no", "0", "$0"):
        return 0
    t = t.removeprefix("$").removesuffix("$")
    try:
        v = float(t)
    except ValueError:
        raise Refused(f"'{text}' is not an amount. Write dollars a day like 10 or $10.") from None
    if not (math.isfinite(v) and 0 <= v <= share_mod.MAX_DOLLARS):
        raise Refused(f"Dollars a day are from 0 to {share_mod.MAX_DOLLARS}.")
    return int(v) if v.is_integer() else round(v, 2)


def _share_cmd(args, root: Path) -> int:
    changes: dict = {}
    if args.week is not None:
        changes["week_pct"] = parse_pct(args.week)
    if args.day is not None:
        changes["by_day"] = parse_day(args.day)
    if args.api is not None:
        changes["api_for"] = parse_kinds(args.api)
    if args.tool is not None:
        changes["tool_one_in"] = parse_one_in(args.tool)
    if args.ahead is not None:
        changes["when_ahead"] = parse_ahead(args.ahead)
    if args.dollars is not None:
        changes["day_dollars"] = parse_dollars(args.dollars)
    preset = args.preset.strip().lower() if args.preset else None
    if args.clear and (changes or preset or args.order):
        raise Refused("--clear removes the share; it does not go with other changes.")
    changed = False
    names = [n.strip() for n in (args.order or "").split(",") if n.strip()]
    if names:  # check the order before anything is saved, so a refused command changes nothing
        gather(root)
        known = store.load(root)["accounts"]
        ids = [store.find(known, n)["id"] for n in names]
        if len(set(ids)) != len(ids):
            raise Refused("An account is named twice in --order. Name each one once.")
    if changes or preset or args.clear:
        who = _actor(args.by)
        changed = share_mod.apply(root, who, changes, preset=preset, clear=args.clear)["changed"]
    if names:
        who = _actor(args.by)
        with store.change(root) as (accounts, rows):
            picked = [store.find(accounts, i) for i in ids]
            for place, a in enumerate(picked, 1):
                store.set_order(accounts, a, rows, who, place)
            changed = changed or bool(rows)
    view = share_mod.view(root, gather(root)["accounts"])
    view["changed"] = changed
    did = bool(changes or preset or args.clear or args.order)
    nxt = (
        (SAVED if changed else "Already like that. Nothing changed.")
        if did
        else (
            "Change it: orch usage share --preset even|save|sub, or --week 70 --day wed --api reviews,scripts "
            "--tool 'one in 4' --ahead api --dollars 10"
        )
    )
    view["next"] = nxt
    lines = [view["sentence"], *view["counts"], *[f"Warning: {w}" for w in view["warnings"]]]
    if view["preset"]:
        lines.insert(0, f"Ready-made spread: {share_mod.PRESETS[view['preset']]['name']}.")
    lines.append(nxt)
    return _emit(args, view, "\n".join(lines))


def parse_resets_day(text: str) -> str:
    """YYYY-MM-DD, past or future: the start of that day, this computer's time, as UTC."""
    t = (text or "").strip()
    if not re.fullmatch(r"\d{4}-\d\d-\d\d", t):
        raise Refused(f"'{text}' is not a day. Write it like 2026-11-17.")
    try:
        d = datetime.strptime(t, "%Y-%m-%d").astimezone()
    except ValueError:
        raise Refused(f"'{text}' is not a day. Write it like 2026-11-17.") from None
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- reading use


def _period_start(period: str, lim: dict, at: datetime) -> str | None:
    if period == "month":
        return store.utc_text(store.month_window(lim, at)[0])
    if period == "week":
        return (at - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return lim.get("since")


def declared(root: Path) -> list[dict]:
    """The API credits skills and add-ons declare (orch core reader, ORCH-625). Empty when this orch has no reader
    or it fails: a declaration never breaks the list. Only labels, providers, names and paths come back; the
    reader never resolves a key."""
    try:
        from orch import apicredits
    except ImportError:
        return []
    try:
        return apicredits.declared(root)["credits"]
    except Exception:  # noqa: BLE001 - a broken skill folder must not take the Usage list down
        return []


PREPARE_DEFAULT_LIMIT = 30  # = orch.config.DEFAULT_PREPARE_DAILY_LIMIT (this add-on does not import orch)


def prepare_use(root: Path, now: float | None = None) -> dict:
    """Preparing tickets on Save (ORCH-741): {"on", "used" in the last 24 hours, "limit" per day}. Read from
    the files orch core writes (.orch/config.toml [workflow], .orch/run/prepare-starts.json)."""
    import time
    import tomllib

    now = time.time() if now is None else now
    try:
        wf = tomllib.loads((root / ".orch" / "config.toml").read_text(encoding="utf-8")).get("workflow", {})
    except (OSError, ValueError):
        wf = {}
    wf = wf if isinstance(wf, dict) else {}
    lim = wf.get("prepare_daily_limit")
    ok = isinstance(lim, int) and not isinstance(lim, bool) and 0 <= lim <= 1000
    try:
        starts = json.loads((root / ".orch" / "run" / "prepare-starts.json").read_text(encoding="utf-8"))
        starts = starts.get("starts") if isinstance(starts, dict) else []
    except (OSError, ValueError):
        starts = []
    day = sorted(x for x in starts or [] if isinstance(x, (int, float)) and 0 <= now - x < 24 * 3600)
    limit = lim if ok else PREPARE_DEFAULT_LIMIT
    out = {"on": wf.get("prepare_on_save", True) is True, "used": len(day), "limit": limit}
    if limit and len(day) >= limit:
        # full: the next ticket can be prepared once enough of these are older than a day (ORCH-811)
        out["free_at"] = datetime.fromtimestamp(day[len(day) - limit] + 24 * 3600, UTC).isoformat(
            timespec="seconds"
        )
    return out


def prepare_text(p: dict) -> str:
    if not p["on"]:
        return "Preparing tickets on Save: off (Settings)"
    return f"Preparing tickets on Save: {p['used']} of {p['limit']} in the last 24 hours"


def _now() -> datetime:
    """The clock (a test sets a fixed one)."""
    return datetime.now(UTC)


def _ender(root: Path):
    tz = when.zone(root)
    return lambda ends: when.words(ends, tz)


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
    at = _now()
    with store.change(root) as (accounts, rows):
        store.expire(accounts, rows, at, say=_ender(root))
        if found:
            store.sync_found(accounts, rows, found, provider="anthropic", reader="cswap")
        store.sync_declared(accounts, rows, declared(root))
    d = store.load(root)
    by_key = {f.key: f for f in (found or [])}
    out = []
    for a in d["accounts"]:
        row = {k: v for k, v in a.items() if k != "source"}
        row["reader"] = a.get("source", {}).get("reader", "none")
        row["skill"] = page.skill_name(
            a.get("source", {}).get("skill")
        )  # the declaring skill's name, never a key
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
            for lim in a["rule"]["limits"] or [{"period": "month"}]:
                c = left.credit_use(root, a, _period_start(lim["period"], lim, at))
                use[lim["period"]] = asdict(c)
            row["credit"] = left.view(root, a, at)
        row["use"] = use
        out.append(row)
    if d["unreadable"]:
        warnings.append(
            f"{d['unreadable']} account(s) in the Usage folder could not be read and are skipped."
        )
    together = []
    for t in d["together"]:
        lim = t["limit"]
        spent = routing.together_spent(d["accounts"], t, at, root)
        row = {
            "provider": t["provider"],
            "label": store.together_label(t["provider"]),
            "limit": lim,
            "spent": spent,
        }
        if lim["period"] == "month":
            row["resets_at"] = store.utc_text(store.month_window(lim, at)[1])
        row["accounts"] = [a["label"] for a in store.money_accounts(d["accounts"], t["provider"])]
        together.append(row)
    mem = switching._read(switching.memory_path(root))  # what the loop's last look found (ORCH-620)
    warnings += [w for w in mem.get("alerts") or [] if isinstance(w, str)]
    return {
        "accounts": out,
        "together": together,
        "switcher": cswap.command() is not None,
        "warnings": warnings,
        "prepare": prepare_use(root),
    }


# ---------------------------------------------------------------- output


def _local(at: str, root: Path | None = None) -> str:
    """A stored UTC time in the workspace's zone (this computer's without a root) with the zone, minutes only."""
    return store.local_text(at, when.zone(root) if root is not None else None)


def _rule_text(rule: dict, tz=None) -> str:
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
    text += f", for {store.kinds_text(rule.get('for') or [])}"
    if rule.get("model"):
        text += f", {store.MODEL_WORDS[rule['model']]}"
    if rule.get("ends"):
        text += f" (ends {when.words(rule['ends'], tz)})"
    return text


def _use_text(row: dict) -> str:
    bits = []
    for name, u in row["use"].items():
        word = PERIOD_WORDS.get(name, name)
        if "pct" in u:
            if u["pct"] is not None:
                bits.append(f"{word} {u['pct']:g}% used")
        elif u.get("spent") is not None:
            bits.append(
                f"{word} ${u['spent']:g} spent"
                + (" (estimated)" if u.get("estimated") else "")
                + (f", {u['note']}" if u.get("note") else "")
            )
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


def _pick_cmd(args, root: Path) -> int:
    """One helper start: which tool, account and model, and why; or wait, with the reason and until when."""
    from . import sources

    kind = (args.kind or "helpers").strip().lower()
    if kind not in store.KINDS:
        raise Refused(f"'{args.kind}' is not a kind of work. Use {', '.join(store.KINDS)}.")
    request = {"start": args.start, "ticket": args.ticket, "kind": kind, "model": args.model}
    p = sources.pick(root, request)
    if args.json:
        print(json.dumps(p.to_dict(), ensure_ascii=False))
    else:
        line = p.why[:1].upper() + p.why[1:]
        if p.wait and p.until:
            line += f" Tries again at {_local(p.until, root)}."
        print(line)
    return 3 if p.wait else 0


def _start_state_cmd(args, root: Path) -> int:
    """The starter tells Usage what became of a picked start: started, failed (money back) or finished."""
    spent = None
    if args.cmd == "finished" and args.spent not in (None, "", "unknown"):
        try:
            spent = float(str(args.spent).lstrip("$"))
        except ValueError:
            spent = math.nan
        if not math.isfinite(spent) or spent < 0:
            raise Refused(f"'{args.spent}' is not an amount of dollars. Use a number like 1.20 or unknown.")
    fn = {"started": picker.started, "failed": picker.failed}.get(args.cmd)
    ok = fn(root, args.start) if fn else picker.finished(root, args.start, spent)
    text = "Saved." if ok else "Nothing changed: Usage has no open start with that id."
    if args.json:
        print(json.dumps({"ok": ok, "start": args.start, "state": args.cmd}, ensure_ascii=False))
    else:
        print(text)
    return 0


def run(args) -> int:
    root = _root(args.dir)
    cmd = args.cmd
    if cmd == "list":
        data = gather(root)
        if args.json:
            print(json.dumps(data, ensure_ascii=False))
            return 0
        lines = []
        gone = [r["label"] for r in data["accounts"] if r.get("removed")]
        for r in data["accounts"]:
            if r.get("removed"):
                continue
            state = "on" if r["on"] else "off"
            if r.get("active"):
                state += ", in use"
            if r.get("credit_ends"):
                ended = store.to_time(r["credit_ends"]) <= datetime.now(UTC)
                state += f", {'ended' if ended else 'ends'} {_local(r['credit_ends'], root)}"
            lines.append(f"{r['order']}. {r['label']} ({state}): {_rule_text(r['rule'], when.zone(root))}")
            credit = left.text(r["credit"], when.zone(root)) if r.get("credit") else ""
            use = (
                _use_text(r) if r["rule"]["limits"] or not credit else ""
            )  # no limit: the credit line says it
            if use:
                lines.append(f"   {use}")
            if credit:
                lines.append(f"   {credit}")
        if not lines:
            lines = ["No accounts yet."]
        if gone:
            lines.append(f"Removed: {', '.join(gone)} (bring one back: orch usage restore <name>)")
        for t in data["together"]:
            lim = t["limit"]
            spent = f"${t['spent']:g} spent, " if t["spent"] is not None else ""
            lines.append(
                f"{t['label']} ({', '.join(t['accounts']) or 'none listed'}): {spent}limit "
                f"{store.fmt_value(lim['value'], '$')} per {PERIOD_WORDS[lim['period']]}"
            )
        lines.append(prepare_text(data["prepare"]))
        lines += [f"Warning: {w}" for w in data["warnings"]]
        lines.append(
            "Next: orch usage limit <account> <number>  (or for / period / order / on / off / end / left)"
        )
        print("\n".join(lines))
        return 0
    if cmd in ("follow", "take-over"):
        return _switcher_cmd(args, root)
    if cmd == "history":
        rows = store.history(root)
        if args.account and args.account.strip().lower() in (share_mod.ACCOUNT, share_mod.LABEL.lower()):
            rows = [r for r in rows if r.get("account") == share_mod.ACCOUNT]
        elif args.account:
            acc = store.find(store.load(root)["accounts"], args.account)
            rows = [r for r in rows if r.get("account") == acc["id"]]
        if args.json:
            print(json.dumps({"history": rows}, ensure_ascii=False))
            return 0
        from . import computer

        here = computer.label(root)
        out = [
            f"{_local(r.get('at', ''), root)}  {r.get('label', r.get('account'))}: {r.get('what')}"
            + (f" ({r['why']})" if r.get("why") else "")
            + f"  (by {str(r.get('who', '')).split(':', 1)[-1]}"
            + (f" in {r['workspace']}" if r.get("workspace") and r["workspace"] != here else "")
            + ")"
            for r in rows
        ] or ["No changes yet."]
        print("\n".join(out))
        return 0

    if cmd in ("run", "start", "stop", "status", "switching"):
        return _loop_cmd(args, root)
    if cmd == "needs":
        rows = switching.needs_rows(root) + routing.needs_rows(root)
        return _emit(
            args, rows, "\n".join(f"{r['title']}: {r['text']}" for r in rows) or "Nothing needs you here."
        )
    if cmd == "seen":
        changed = switching.mark_seen(root, _actor(args.by), args.warning, args.since)
        return _emit(
            args,
            {"warning": args.warning, "changed": changed},
            "Hidden until it comes back." if changed else "Already hidden until it comes back.",
        )
    if cmd == "share":
        return _share_cmd(args, root)
    if cmd == "pick":
        return _pick_cmd(args, root)
    if cmd in ("started", "failed", "finished"):
        return _start_state_cmd(args, root)

    if cmd == "before-start":  # the core's start question (contracts/before-start.schema.json)
        try:
            req = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            raise Refused("The start question was not JSON.") from None
        if not isinstance(req, dict):
            raise Refused("The start question was not a JSON object.")
        print(json.dumps(routing.decide(root, req), ensure_ascii=False))
        return 0
    if cmd == "ask":  # a credit skill or a helper's own subagent, before it spends (asking.py)
        from . import asking

        known = None
        if args.known is not None:
            if args.known != "-":
                raise Refused("Give the known credits on stdin: --known -")
            if not args.provider:
                raise Refused("Known credits need --provider anthropic or openai.")
            try:
                raw = json.loads(sys.stdin.read() or "[]")
            except ValueError:
                raise Refused("The known credits were not JSON.") from None
            if not isinstance(raw, list) or len(raw) > 10:
                raise Refused("The known credits must be a list of at most 10.")
            known = [store.check_known(k) for k in raw]
        kind = store.parse_kinds([args.kind])
        if not kind or len(kind) != 1:
            raise Refused("Ask for one kind of work: " + ", ".join(store.KIND_WORDS.values()) + ".")
        ans = asking.ask(root, kind[0], args.provider, args.name, known)
        if args.json:
            print(json.dumps(ans, ensure_ascii=False))
        elif ans["go"] and ans.get("account"):
            room = f" (${ans['left']:g} left)" if ans.get("left") is not None else ""
            print(f"Use {ans['account']}{room}.")
        elif ans["go"]:
            print("Nothing is set for this kind of work in Usage: go ahead as usual.")
        else:
            print(ans["why"])
        return 0 if ans["go"] else 3
    who = _actor(args.by)
    if cmd == "spent":  # a credit skill reports what one call cost; the amount left counts down from it
        a = find_credit(store.load(root)["accounts"], args.account, args.provider)
        amount = parse_money(args.amount, allow_none=False)
        if not amount:
            raise Refused("Say what was spent as an amount above 0, like 0.42.")
        left.record(root, a, amount, who)
        v = left.view(root, a)
        line = left.text(v, when.zone(root))
        return _emit(
            args,
            {"account": a["label"], "spent": amount, "credit": v},
            f"{a['label']}: {left.money(amount)} written down." + (f"\n{line}" if line else ""),
        )
    if cmd in ("add", "together"):
        return _whole_file_cmd(args, root, who)
    tz, at = when.zone(root), _now()
    end_words = getattr(args, "end", None) or getattr(args, "when", None)
    reset, wants_reset = None, when.is_reset(end_words)
    try:
        known = bool(store.find(store.load(root)["accounts"], args.account))
    except Refused:
        known = False
    if not known or wants_reset:
        # a fresh workspace, or an end at the next reset: let the readers find the accounts and their resets first
        data = gather(root)
        if wants_reset:
            reset = when.next_reset(store.find(data["accounts"], args.account), at, tz)
    end = when.parse_end(args.end, at, tz, reset, args.account) if getattr(args, "end", None) else None
    with store.change(root) as (accounts, rows):
        store.expire(accounts, rows, at, say=_ender(root))
        a = store.find(accounts, args.account)
        if cmd == "limit":
            value, unit = parse_value(args.value)
            until = parse_time(args.until) if args.until else None
            store.set_limit(a, rows, who, value, unit, parse_period(args.period), until, end)
            if args.resets:
                store.set_resets(a, rows, who, parse_resets_day(args.resets))
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
        elif cmd == "for":
            store.set_for(a, rows, who, store.parse_kinds(args.kinds), end)
        elif cmd == "order":
            if not re.fullmatch(r"\d+", args.place.strip()):
                raise Refused(f"'{args.place}' is not a place. Write a number such as 1 or 2.")
            store.set_order(accounts, a, rows, who, int(args.place), end)
        elif cmd == "model":
            word = args.model.strip().lower()
            store.set_model(a, rows, who, None if word in store.ANY else word, end)
        elif cmd == "remove":
            store.remove_account(accounts, a, rows, who)
        elif cmd in ("on", "off"):
            store.set_on(a, rows, who, cmd == "on")
        elif cmd == "left":
            store.set_left(a, rows, who, parse_money(args.amount))
        elif cmd == "end":
            ends = (
                None
                if args.when.strip().lower() in ("none", "never", "no")
                else when.parse_end(args.when, at, tz, reset, a["label"])
            )
            if (
                a["type"] in store.MONEY_TYPES
            ):  # an API credit or helper tool itself ends (asking refuses it then)
                store.set_credit_end(a, rows, who, ends)
            else:
                store.set_end(a, rows, who, ends, when.words(ends, tz) if ends else "")
        elif cmd == "restore":
            store.restore_account(a, rows, who)
        else:
            raise Refused(f"Unknown command {cmd}.")
        changed = bool(rows)
        result = {k: v for k, v in a.items() if k != "source"}
    if cmd == "remove":
        back = f'Bring it back: orch usage restore "{result["label"]}"'
        return _emit(
            args,
            {"removed": result["label"], "changed": changed, "next": f"{SAVED} {back}"},
            f"{result['label']} is removed and not used. Its history stays.\n{back}\n{SAVED}",
        )
    if cmd == "left":
        a = store.find(store.load(root)["accounts"], result["id"])
        v = left.view(root, a)
        line = left.text(v, when.zone(root)) or f"{result['label']}: no amount left set."
        return _emit(
            args, {"account": result, "credit": v, "changed": changed, "next": SAVED}, f"{line}\n{SAVED}"
        )
    nxt = SAVED if changed else "Already like that. Nothing changed."
    credit_end = cmd == "end" and result["type"] in store.MONEY_TYPES
    rule_cmd = cmd in ("limit", "period", "end", "for", "model", "order")
    if changed and rule_cmd and not credit_end and result["rule"].get("ends"):
        nxt = SAVED + " The rule falls back to the one before it when it ends."
    ends = f", ends {_local(result['credit_ends'], root)}" if result.get("credit_ends") else ""
    if credit_end and changed:
        nxt = SAVED + (" From then on it is not used." if ends else "")
    return _emit(
        args,
        {"account": result, "changed": changed, "next": nxt},
        f"{result['label']}: {_rule_text(result['rule'], tz)}, {'on' if result['on'] else 'off'}{ends}, "
        f"place {result['order']}.\n{nxt}",
    )


def _whole_file_cmd(args, root: Path, who: str) -> int:
    """`add` (an API credit or helper tool, by a person) and `together` (one money limit over all accounts of a
    provider)."""
    with store.change_all(root) as (doc, rows):
        store.expire(doc["accounts"], rows)
        if args.cmd == "add":
            value, unit = parse_value(args.limit) if args.limit else (None, None)
            if unit == "%":
                raise Refused("The limit of an API credit or helper tool is in dollars, like $100.")
            a = store.add_account(
                doc["accounts"],
                rows,
                who,
                label=args.label,
                provider=args.provider,
                type_=args.type,
                name=args.name,
                kinds=store.parse_kinds(args.kinds) if args.kinds else [],
                limit=value,
                period=parse_period(args.period) or "month",
                since=parse_resets_day(args.resets) if args.resets else None,
                tool=args.tool,
                first=args.first,
            )
            if args.left is not None:
                store.set_left(a, rows, who, parse_money(args.left))
            result = {k: v for k, v in a.items() if k != "source"}
            text = f"{a['label']} added: {_rule_text(a['rule'])}, place {a['order']}."
            if a.get("left"):
                text += f" Left: {left.money(a['left']['value'])}."
            data: dict = {"account": result}
        else:
            value, unit = parse_value(args.value)
            if unit == "%":
                raise Refused("A limit over several accounts is in dollars, like $100.")
            period = parse_period(args.period) or "month"
            store.set_together(
                doc,
                rows,
                who,
                args.provider,
                value,
                period,
                parse_resets_day(args.resets) if args.resets else None,
            )
            label = store.together_label(args.provider.strip().lower())
            text = f"{label}: " + (
                f"limit {store.fmt_value(value, '$')} per {PERIOD_WORDS[period]}." if value else "no limit."
            )
            data = {"together": doc["together"]}
        changed = bool(rows)
    nxt = SAVED if changed else "Already like that. Nothing changed."
    return _emit(args, {**data, "changed": changed, "next": nxt}, f"{text}\n{nxt}")


def _loop_cmd(args, root: Path) -> int:
    from . import service, switching

    cmd = args.cmd
    if cmd == "run":
        import signal

        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        if args.once:
            r = switching.look(root)
            return _emit(args, r, _look_text(r))
        print(f"orch usage for {root.name} started {store.now()}", flush=True)
        from . import server

        page = server.serve_in_background(root, args.port or service.preferred_port())
        port = page.server_address[1] if page else None
        if page is None:
            print("The Usage page could not start: no free port.", flush=True)
        # background run: record pid, start time and the page's port in .orch/run/usage/
        nonce = service.announce(root, port)
        try:
            switching.run_forever(root, log=lambda m: print(m, flush=True))
        except KeyboardInterrupt:
            pass
        finally:
            if page:
                page.shutdown()
            service.forget(root, nonce)
        return 0
    if cmd == "start":
        try:
            pid = service.start(root)
        except RuntimeError as e:
            raise Refused(str(e)) from None
        url = service.page_url(root)
        data = {"running": True, "pid": pid, **({"url": url} if url else {})}
        return _emit(args, data, f"Usage is running: {url}" if url else f"Usage is running (pid {pid}).")
    if cmd == "stop":
        try:
            res = service.stop(root)
        except RuntimeError as e:
            res = str(e)
        if res in ("stopped", "not running"):
            return _emit(
                args,
                {"stopped": res == "stopped"},
                "Usage stopped." if res == "stopped" else "Usage was not running.",
            )
        note = (
            "A file in .orch/run/usage/ names a process that is not the Usage loop; nothing was stopped."
            if res == "not verified"
            else res
        )
        return _emit(args, {"stopped": False, "note": note}, note)
    if cmd == "status":
        pid = service.running_pid(root)
        last = switching._read(switching.memory_path(root)).get("last") or {}
        on = switching.switching_on(root)
        data = {
            "running": bool(pid),
            "pid": pid,
            "switching": on,
            "switcher": bool(cswap.command()),
            "last": last,
        }
        url = service.page_url(root) if pid else None
        if url:
            data["url"] = url
        line = f"Usage is running (pid {pid})." if pid else "Usage is not running. Start it: orch start."
        if not data["switcher"]:
            line += " " + NO_SWITCHER
        else:
            line += " Switching is " + ("on." if on else "off: Usage only shows what it would switch.")
        line += "".join(
            f"\nWarning: {w}" for w in (switching._read(switching.memory_path(root)).get("alerts") or [])
        )
        owner_line = _owner_line(root)
        if owner_line:
            line += "\n" + owner_line
        if last:
            line += f"\nLast look {_local(last.get('at', ''), root)}: {last.get('did')} ({last.get('why')})."
        print(json.dumps(data, ensure_ascii=False) if args.json else line)
        return 0 if pid else 1
    # switching on|off
    who = _actor(args.by)
    if args.state not in ("on", "off"):
        raise Refused(f"'{args.state}' is not on or off. Write: orch usage switching on, or off.")
    on = args.state == "on"
    changed = switching.set_switching(root, who, on)
    if on and not cswap.command():
        nxt = NO_SWITCHER
    elif on:
        nxt = "Usage now switches by itself before an account reaches a limit."
    else:
        nxt = "Usage only shows and warns; it does not switch."
    nxt += " This setting counts for every workspace on this computer."
    owner_line = _owner_line(root)
    if owner_line and on:
        nxt += " " + owner_line
    return _emit(
        args,
        {"switching": on, "changed": changed, "next": nxt},
        (SAVED + " " if changed else "Already like that. ") + nxt,
    )


def _owner_line(root: Path) -> str | None:
    """'<workspace> switches the accounts on this computer' when another workspace's loop switches, else None."""
    from . import computer

    v = computer.view(root, computer.shared_dir(root))
    if not v or v["mine"] or not v.get("running"):
        return None
    w = v["words"]
    return f"{w['title']}. {w['text']} To switch from here: orch usage take-over."


def _switcher_cmd(args, root: Path) -> int:
    from . import computer

    shared = computer.shared_dir(root)
    if shared is None:
        raise Refused(
            "Usage keeps its settings in this workspace only here; there is no other workspace to follow."
        )
    who = _actor(args.by)
    if args.cmd == "follow":
        changed = computer.follow(root, shared, who)
        v = computer.view(root, shared)
        return _emit(
            args,
            {"changed": changed, "switcher": v},
            (SAVED + " " if changed else "Already like that. ") + (v["words"]["tag"] + "."),
        )
    if _helper_run():  # a helper may name a person with --by; the take-over is the person's own click
        raise Refused("Only a person can move account switching to another workspace.")
    changed = computer.take_over(root, shared, who)
    text = (
        "This workspace switches the accounts now. The other workspace follows from its next look (within a minute)."
        if changed
        else "This workspace already switches the accounts."
    )
    return _emit(args, {"changed": changed, "switcher": computer.view(root, shared)}, text)


def _look_text(r: dict) -> str:
    if not r.get("switcher"):
        return NO_SWITCHER
    if r.get("did") == "follow":
        return f"{r.get('owner')} switches the accounts on this computer; this workspace follows."
    if r.get("did") == "nothing":  # installed, but it did not answer: say so, Usage looks again by itself
        return (r.get("note") or "The account switcher did not answer.") + " Usage looks again in a minute."
    text = {
        "stay": f"Staying on {r.get('active')}.",
        "switched": f"Switched from {r.get('active')} to {r.get('target')}.",
        "would switch": f"Would switch from {r.get('active')} to {r.get('target')} (switching is off).",
        "switch failed": f"Could not switch to {r.get('target')}. It is tried again in 10 minutes.",
        "waiting to try again": f"Waiting to try {r.get('target')} again.",
        "held": (
            f"Staying on {r.get('active')}: another program keeps switching back to it. "
            "Which rule should win? See orch usage needs."
        ),
    }.get(r["did"], r["did"])
    if r.get("all_at_limit"):
        text += " Warning: every account is at or near its limit."
    return text


class _Parser(argparse.ArgumentParser):
    """A wrong word is refused in plain words, never with argparse's raw "error: argument ..." line."""

    def error(self, message):
        m = re.search(r"argument (\S+): invalid choice: '([^']*)' \(choose from (.*)\)", message)
        if m:
            what, word, allowed = m.groups()
            allowed = ", ".join(a.strip().strip("'") for a in allowed.split(","))
            if what in ("command", "cmd") or what.startswith("{"):  # the command word itself
                self.exit(2, f'Refused: "{word}" is not an {self.prog} command. Run {self.prog} --help.\n')
            self.exit(2, f'Refused: "{word}" is not a {what} here. Use one of: {allowed}.\n')
        m = re.search(r"required: (.*)", message)
        if m:
            usage = self.format_usage().replace("usage: ", "").strip()
            self.exit(2, f"Refused: missing {m.group(1)}. Usage: {usage}\n")
        self.exit(2, f"Refused: {message}. Run {self.prog} --help.\n")


def main(argv=None) -> int:
    ap = _Parser(prog="orch usage")
    ap.add_argument(
        "--dir",
        default=os.environ.get("ORCH_ROOT", "."),
        help="the workspace folder (default: where you are)",
    )
    sub = ap.add_subparsers(dest="cmd", required=True, parser_class=_Parser, metavar="command")

    def p(name, help_text, **kw):
        s = sub.add_parser(name, help=help_text, description=help_text, **kw)
        s.add_argument("--json", action="store_true", help="print the answer as JSON")
        return s

    ACC = "the account: its name, or its number from `orch usage list`"
    BY = "who makes the change, for the history (default: you)"
    END = "make the rule temporary: it ends then (YYYY-MM-DD or YYYY-MM-DDTHH:MM) and the old rule returns"

    p("list", "The accounts, how far each is used, and its limits")
    p("needs", "What needs a person now: a warning, an account at its limit, a kind of work with no room")
    p("before-start", "The core's question before a helper starts (JSON on stdin): tool, model or wait")
    s = p("ask", "A credit skill or a helper's subagent asks before it spends: go or wait")
    s.add_argument("kind", help="the kind of work: lead, code, reviews, builds, scripts or helpers")
    s.add_argument("--provider", help="anthropic or openai")
    s.add_argument("--name", help="the name the credit skill uses for its credit (never the key)")
    s.add_argument("--known", help="the credits the skill knows, on stdin: --known -")
    s = p("seen", "Mark a warning as seen so it stops showing")
    s.add_argument("warning", choices=("all-at-limit", "switch-failed"), help="which warning")
    s.add_argument("--since", help="the time of the warning that was seen")
    s.add_argument("--by", help=BY)
    s = p("history", "Every rule change and switch, newest first")
    s.add_argument("--account", help="only this account (name or number)")
    s = p("limit", "Set how far an account may go: a %% or dollars")
    s.add_argument("account", help=ACC)
    s.add_argument("value", help="the limit: 90 or 90%% (subscription), $100 (credit), or none to remove it")
    s.add_argument("--period", help="which limit it is: 5h, week, month or until (needed when there are two)")
    s.add_argument("--until", help="for an until limit: the last day it counts (YYYY-MM-DD)")
    s.add_argument("--resets", help="the day a monthly credit starts again, e.g. 2026-11-17")
    s.add_argument("--end", help=END)
    s.add_argument("--by", help=BY)
    s = p("period", "Change the time a limit counts over")
    s.add_argument("account", help=ACC)
    s.add_argument("new", help="the new period: 5h, week, month or until")
    s.add_argument("--of", help="which limit to change: 5h, week, month or until (needed when there are two)")
    s.add_argument("--until", help="for until: the last day it counts (YYYY-MM-DD)")
    s.add_argument("--end", help=END)
    s.add_argument("--by", help=BY)
    s = p("for", "Set the kinds of work an account is used for")
    s.add_argument("account", help=ACC)
    s.add_argument("kinds", nargs="+", help="lead, code, reviews, builds, scripts, helpers, or any")
    s.add_argument("--end", help=END)
    s.add_argument("--by", help=BY)
    s = p("order", "Move an account to a place in the order")
    s.add_argument("account", help=ACC)
    s.add_argument("place", help="the new place: 1 is used first, up to the number of accounts")
    s.add_argument("--end", help="the place holds until then, then the account goes back to its place before")
    s.add_argument("--by", help=BY)
    s = p("model", "Narrow the model an account runs")
    s.add_argument("account", help=ACC)
    s.add_argument(
        "model", help="small (the small model only), first (small first, the big one when needed), any"
    )
    s.add_argument("--end", help=END)
    s.add_argument("--by", help=BY)
    s = p("together", "One money limit over all API credits and helper tools of a provider")
    s.add_argument(
        "provider", help="every API credit and helper tool of this provider, e.g. anthropic or openai"
    )
    s.add_argument("value", help="$100, or none")
    s.add_argument("--period", help="month (default) or week")
    s.add_argument("--resets", help="the day the month starts again, e.g. 2026-11-17")
    s.add_argument("--by", help=BY)
    s = p("add", "Add an API credit or helper tool")
    s.add_argument("label", help="what to call it on the page")
    s.add_argument("--provider", required=True, help="anthropic or openai")
    s.add_argument("--type", choices=store.MONEY_TYPES, default="api-key", help="api-key or helper-tool")
    s.add_argument(
        "--name", required=True, help="the name the credit skill uses to find its key (never the key)"
    )
    s.add_argument(
        "--for", dest="kinds", nargs="+", help="the kinds of work it is used for (default: every kind)"
    )
    s.add_argument("--limit", help="$100")
    s.add_argument("--period", help="month (default) or week")
    s.add_argument("--resets", help="the day the month starts again, e.g. 2026-11-17")
    s.add_argument("--tool", help="the helper tool it runs, as named in Settings")
    s.add_argument("--first", action="store_true", help="use it first")
    s.add_argument("--left", help="what is left on it now, as read at the provider, e.g. $74")
    s.add_argument("--by", help=BY)
    s = p("left", "Write down what is left on an API credit now")
    s.add_argument("account", help=ACC)
    s.add_argument("amount", help="what is left now, as read at the provider: $74, 0, or none")
    s.add_argument("--by", help=BY)
    s = p("spent", "A credit skill reports what one call cost")
    s.add_argument("account", help="the credit's label, or the name its credit skill uses")
    s.add_argument("amount", help="what one call or job cost, in dollars: 0.42")
    s.add_argument("--provider", help="anthropic or openai, when two credits share a name")
    s.add_argument("--by", help=BY)
    s = p("remove", "Take an API credit or helper tool off the list")
    s.add_argument("account", help=ACC)
    s.add_argument("--by", help=BY)
    s = p("restore", "Bring back an API credit or helper tool that was removed")
    s.add_argument("account", help=ACC)
    s.add_argument("--by", help=BY)
    for name, word in (("on", "Use an account again"), ("off", "Stop using an account")):
        s = p(name, word)
        s.add_argument("account", help=ACC)
        s.add_argument("--by", help=BY)
    s = p("end", "Make a rule end at a time")
    s.add_argument("account", help=ACC)
    s.add_argument("when", help="when it ends (YYYY-MM-DD or YYYY-MM-DDTHH:MM), or none to keep the rule")
    s.add_argument("--by", help=BY)
    s = p("share", "How helper work is spread: read it back, or change it")
    s.add_argument("--preset", help="save, even or sub: a ready-made spread")
    s.add_argument("--week", help="at most this %% of a subscription's week ...")
    s.add_argument("--day", help="... by the end of this weekday (wed)")
    s.add_argument("--api", help="kinds of work on API credit: reviews,scripts or none")
    s.add_argument("--tool", help="Code tickets on the helper tool: 'one in 4', all or none")
    s.add_argument("--ahead", help="a subscription ahead of its pace: api, tool, both or none")
    s.add_argument("--dollars", help="dollars a day on API credit while ahead")
    s.add_argument("--order", help="all or the first accounts in order: 'Personal 1, Company'")
    s.add_argument("--clear", action="store_true", help="remove the share")
    s.add_argument("--by", help=BY)
    s = p("pick", "Which tool, account and model one helper start uses, and why")
    s.add_argument("--start", required=True, help="the start's id, the same on every retry")
    s.add_argument("--ticket", help="the ticket the start is for")
    s.add_argument("--kind", help="lead, code, reviews, builds, scripts or helpers")
    s.add_argument("--model", help="orch's model pick: opus, sonnet or haiku")
    for name in ("started", "failed", "finished"):
        s = p(name, f"Tell Usage a picked start {name}")
        s.add_argument("start", help="the start's id")
        if name == "finished":
            s.add_argument("--spent", help="what the helper really spent, in dollars, or unknown")
    s = p("switching", "Turn switching accounts by itself on or off")
    s.add_argument("state", help="on or off")
    s.add_argument("--by", help=BY)
    for name in ("follow", "take-over"):
        s = p(name, "another workspace switches the accounts: follow it, or switch from here (a person only)")
        s.add_argument("--by", help=BY)
    s = p("act", "A change from the Usage page (the page uses it)")
    s.add_argument("verb", help="limit, period, order, on, off, end or switching")
    s.add_argument("target", help="what to change, for example main:90")
    s.add_argument("--by", help=BY)
    s = p("run", "Run the Usage page and the switcher in this window")
    s.add_argument("--once", action="store_true", help="look once and stop")
    s.add_argument("--port", type=int, default=None, help=argparse.SUPPRESS)
    for name, word in (
        ("start", "Start the Usage page and the switcher in the background"),
        ("stop", "Stop them"),
        ("status", "Say whether they run and where the page is"),
    ):
        p(name, word)
    args = ap.parse_args(argv)
    args.json = bool(getattr(args, "json", False)) or "--json" in (argv if argv is not None else sys.argv)
    try:
        if args.cmd == "act":
            from . import acts

            words = acts.argv_for(_root(args.dir), args.verb, args.target, args.by)
            return main(["--dir", args.dir, *words, "--json"])
        return run(args)
    except Refused as e:
        return _fail(args, str(e))
