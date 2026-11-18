"""orch usage list|history|limit|period|order|on|off|end|for|model|together|add|remove|ask|switching|act|run|start|
stop|status
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

from . import routing, store
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


def parse_day(text: str) -> str:
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
    together = []
    for t in d["together"]:
        lim = t["limit"]
        spent = routing.together_spent(d["accounts"], t, at)
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
    return {"accounts": out, "together": together, "switcher": found is not None, "warnings": warnings}


# ---------------------------------------------------------------- output


def _local(at: str) -> str:
    """A stored UTC time in this computer's local time, minutes only."""
    try:
        return store.to_time(at).astimezone().strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return at[:16].replace("T", " ")


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
    text += f", for {store.kinds_text(rule.get('for') or [])}"
    if rule.get("model"):
        text += f", {store.MODEL_WORDS[rule['model']]}"
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
        for t in data["together"]:
            lim = t["limit"]
            spent = f"${t['spent']:g} spent, " if t["spent"] is not None else ""
            lines.append(
                f"{t['label']} ({', '.join(t['accounts']) or 'none listed'}): {spent}limit "
                f"{store.fmt_value(lim['value'], '$')} per {PERIOD_WORDS[lim['period']]}"
            )
        lines += [f"Warning: {w}" for w in data["warnings"]]
        lines.append("Next: orch usage limit <account> <number>  (or for / period / order / on / off / end)")
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
            f"{_local(r.get('at', ''))}  {r.get('label', r.get('account'))}: {r.get('what')}"
            + (f" ({r['why']})" if r.get("why") else "")
            + f"  (by {str(r.get('who', '')).split(':', 1)[-1]})"
            for r in rows
        ] or ["No changes yet."]
        print("\n".join(out))
        return 0

    if cmd in ("run", "start", "stop", "status", "switching"):
        return _loop_cmd(args, root)
    if cmd == "before-start":  # the core's start question (contracts/before-start.schema.json)
        from . import routing

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
            left = f" (${ans['left']:g} left)" if ans.get("left") is not None else ""
            print(f"Use {ans['account']}{left}.")
        elif ans["go"]:
            print("Nothing is set for this kind of work in Usage: go ahead as usual.")
        else:
            print(ans["why"])
        return 0 if ans["go"] else 3
    if cmd == "needs":
        from . import routing

        print(json.dumps(routing.needs_rows(root), ensure_ascii=False))
        return 0

    who = _actor(args.by)
    end = parse_time(args.end) if getattr(args, "end", None) else None
    if cmd in ("add", "together"):
        return _whole_file_cmd(args, root, who)
    try:
        store.find(store.load(root)["accounts"], args.account)
    except Refused:
        gather(root)  # a fresh workspace: let the readers find the accounts first
    with store.change(root) as (accounts, rows):
        store.expire(accounts, rows)
        a = store.find(accounts, args.account)
        if cmd == "limit":
            value, unit = parse_value(args.value)
            until = parse_time(args.until) if args.until else None
            store.set_limit(a, rows, who, value, unit, parse_period(args.period), until, end)
            if args.resets:
                store.set_resets(a, rows, who, parse_day(args.resets))
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
            store.set_order(accounts, a, rows, who, args.place, end)
        elif cmd == "model":
            word = args.model.strip().lower()
            store.set_model(a, rows, who, None if word in store.ANY else word, end)
        elif cmd == "remove":
            store.remove_account(accounts, a, rows, who)
        elif cmd in ("on", "off"):
            store.set_on(a, rows, who, cmd == "on")
        elif cmd == "end":
            when = None if args.when.strip().lower() in ("none", "never", "no") else parse_time(args.when)
            store.set_end(a, rows, who, when)
        else:
            raise Refused(f"Unknown command {cmd}.")
        changed = bool(rows)
        result = {k: v for k, v in a.items() if k != "source"}
    if cmd == "remove":
        return _emit(
            args,
            {"removed": result["label"], "changed": True, "next": SAVED},
            f"{result['label']} is no longer listed. Its history stays.\n{SAVED}",
        )
    nxt = SAVED if changed else "Already like that. Nothing changed."
    if changed and cmd in ("limit", "period", "end", "for", "model", "order") and result["rule"].get("ends"):
        nxt = SAVED + " The rule falls back to the one before it when it ends."
    return _emit(
        args,
        {"account": result, "changed": changed, "next": nxt},
        f"{result['label']}: {_rule_text(result['rule'])}, {'on' if result['on'] else 'off'}, "
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
                since=parse_day(args.resets) if args.resets else None,
                tool=args.tool,
                first=args.first,
            )
            result = {k: v for k, v in a.items() if k != "source"}
            text = f"{a['label']} added: {_rule_text(a['rule'])}, place {a['order']}."
            data: dict = {"account": result}
        else:
            value, unit = parse_value(args.value)
            if unit == "%":
                raise Refused("A limit over several accounts is in dollars, like $100.")
            period = parse_period(args.period) or "month"
            store.set_together(
                doc, rows, who, args.provider, value, period, parse_day(args.resets) if args.resets else None
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
        if last:
            line += f"\nLast look {last.get('at', '')[:16].replace('T', ' ')} UTC: {last.get('did')} ({last.get('why')})."
        print(json.dumps(data, ensure_ascii=False) if args.json else line)
        return 0 if pid else 1
    # switching on|off
    who = _actor(args.by)
    on = args.state == "on"
    changed = switching.set_switching(root, who, on)
    if on and not cswap.command():
        nxt = NO_SWITCHER
    elif on:
        nxt = "Usage now switches by itself before an account reaches a limit."
    else:
        nxt = "Usage only shows and warns; it does not switch."
    return _emit(
        args,
        {"switching": on, "changed": changed, "next": nxt},
        (SAVED + " " if changed else "Already like that. ") + nxt,
    )


def _look_text(r: dict) -> str:
    if not r.get("switcher"):
        return NO_SWITCHER
    text = {
        "stay": f"Staying on {r.get('active')}.",
        "switched": f"Switched from {r.get('active')} to {r.get('target')}.",
        "would switch": f"Would switch from {r.get('active')} to {r.get('target')} (switching is off).",
        "switch failed": f"Could not switch to {r.get('target')}. It is tried again in 10 minutes.",
        "waiting to try again": f"Waiting to try {r.get('target')} again.",
    }.get(r["did"], r["did"])
    if r.get("all_at_limit"):
        text += " Warning: every account is at or near its limit."
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="orch usage")
    ap.add_argument("--dir", default=os.environ.get("ORCH_ROOT", "."))
    sub = ap.add_subparsers(dest="cmd", required=True)

    def p(name, **kw):
        s = sub.add_parser(name, **kw)
        s.add_argument("--json", action="store_true")
        return s

    p("list")
    p("before-start")
    p("needs")
    s = p("ask")
    s.add_argument("kind")
    s.add_argument("--provider")
    s.add_argument("--name")
    s.add_argument("--known")
    s = p("history")
    s.add_argument("--account")
    s = p("limit")
    s.add_argument("account")
    s.add_argument("value")
    s.add_argument("--period")
    s.add_argument("--until")
    s.add_argument("--resets", help="the day a monthly credit starts again, e.g. 2026-11-17")
    s.add_argument("--end")
    s.add_argument("--by")
    s = p("period")
    s.add_argument("account")
    s.add_argument("new")
    s.add_argument("--of")
    s.add_argument("--until")
    s.add_argument("--end")
    s.add_argument("--by")
    s = p("for")
    s.add_argument("account")
    s.add_argument("kinds", nargs="+")
    s.add_argument("--end")
    s.add_argument("--by")
    s = p("order")
    s.add_argument("account")
    s.add_argument("place", type=int)
    s.add_argument("--end", help="the place holds until then, then the account goes back to its place before")
    s.add_argument("--by")
    s = p("model")
    s.add_argument("account")
    s.add_argument(
        "model", help="small (the small model only), first (small first, the big one when needed), any"
    )
    s.add_argument("--end")
    s.add_argument("--by")
    s = p("together")
    s.add_argument(
        "provider", help="every API credit and helper tool of this provider, e.g. anthropic or openai"
    )
    s.add_argument("value", help="$100, or none")
    s.add_argument("--period", help="month (default) or week")
    s.add_argument("--resets", help="the day the month starts again, e.g. 2026-11-17")
    s.add_argument("--by")
    s = p("add")
    s.add_argument("label")
    s.add_argument("--provider", required=True)
    s.add_argument("--type", choices=store.MONEY_TYPES, default="api-key")
    s.add_argument(
        "--name", required=True, help="the name the credit skill uses to find its key (never the key)"
    )
    s.add_argument("--for", dest="kinds", nargs="+")
    s.add_argument("--limit", help="$100")
    s.add_argument("--period", help="month (default) or week")
    s.add_argument("--resets", help="the day the month starts again, e.g. 2026-11-17")
    s.add_argument("--tool", help="the helper tool it runs, as named in Settings")
    s.add_argument("--first", action="store_true", help="use it first")
    s.add_argument("--by")
    s = p("remove")
    s.add_argument("account")
    s.add_argument("--by")
    for name in ("on", "off"):
        s = p(name)
        s.add_argument("account")
        s.add_argument("--by")
    s = p("end")
    s.add_argument("account")
    s.add_argument("when")
    s.add_argument("--by")
    s = p("switching")
    s.add_argument("state", choices=("on", "off"))
    s.add_argument("--by")
    s = p("act")
    s.add_argument("verb")
    s.add_argument("target")
    s.add_argument("--by")
    s = p("run")
    s.add_argument("--once", action="store_true")
    s.add_argument("--port", type=int, default=None, help=argparse.SUPPRESS)
    for name in ("start", "stop", "status"):
        p(name)
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
