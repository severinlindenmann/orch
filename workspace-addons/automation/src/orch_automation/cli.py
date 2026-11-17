"""`orch automation`: run, start, stop, status, list, repeat, view. Exit 0 ok, 2 refused (plain words), like the core."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import actions, orchcli, plain, scripts, service
from .cron import fmt, next_after, valid
from .listen import NOT_LISTENING
from .loop import Scheduler, scheduled
from .runner import load_state
from .view import cron_human


class Refused(Exception):
    pass


def find_workspace(start: Path) -> Path | None:
    p = start.resolve()
    for d in (p, *p.parents):
        if (d / ".orch").is_dir():
            return d
    return None


def local_text(at: str | None) -> str | None:
    """A UTC time as the computer's local time with its zone: "Fri 07 Nov 09:00 CET"."""
    try:
        return datetime.fromisoformat(at).astimezone().strftime("%a %d %b %H:%M %Z") if at else None
    except (ValueError, AttributeError):
        return None


def list_line(x: dict) -> str:
    name = x["key"] or x["ticket"]
    if x["kind"] == "wake":
        return f"{name}  Wakes {x.get('local') or x['at']}  {x['title']}"
    nxt = "switched off" if x.get("off") else f"next {x.get('local') or x['at'] or 'unknown'}"
    return f"{name}  {x['when']}, {nxt}  {x['title']}"


def describe(root: Path) -> list[dict]:
    """Next wake-ups and repeats, soonest first: the tickets the scheduler plans (a repeat survives Done)."""
    state = load_state(root)
    rows = []
    for t in orchcli.tickets(root):
        if not scheduled(t):
            continue
        w = t.get("waiting_on") or {}
        if w.get("kind") == "time" and w.get("until"):
            rows.append(
                {
                    "ticket": t["id"],
                    "key": t.get("key"),
                    "title": t["title"],
                    "kind": "wake",
                    "at": w["until"],
                    "local": local_text(w["until"]),
                }
            )
        s = (t.get("ext") or {}).get("automation") or {}
        if s.get("recurring") is True and s.get("cron"):
            if s.get("paused") is True:  # switched off: listed, no next time
                rows.append(
                    {
                        "ticket": t["id"],
                        "key": t.get("key"),
                        "title": t["title"],
                        "kind": "repeat",
                        "cron": s["cron"],
                        "at": None,
                        "off": True,
                        "when": cron_human(s["cron"], plain.zone(s.get("tz"))),
                    }
                )
                continue
            nxt = next_after(s["cron"], datetime.now(UTC), plain.zone(s.get("tz")))
            at = fmt(nxt) if nxt else state.get(t["id"], {}).get("next_run")
            rows.append(
                {
                    "ticket": t["id"],
                    "key": t.get("key"),
                    "title": t["title"],
                    "kind": "repeat",
                    "cron": s["cron"],
                    "at": at,
                    "when": cron_human(s["cron"], plain.zone(s.get("tz"))),
                    "local": local_text(at),
                }
            )
    return sorted(rows, key=lambda r: r["at"] or "")


def repeat(
    root: Path,
    tid: str,
    phrase: str | None,
    off: bool,
    agent: str | None = None,
    tz: str | None = None,
    each_run: bool = False,
    by: str | None = None,
    script: str | None = None,
) -> dict:
    want = tid.strip().upper()  # the ticket id, or its key (DM1-12, any case)
    t = next(
        (x for x in orchcli.tickets(root) if x["id"] == tid or str(x.get("key") or "").upper() == want), None
    )
    if t is None:
        raise Refused(f"There is no ticket {tid}.")
    tid = t["id"]
    if off:
        if not orchcli.set_ext(root, t, remove=("each_run", "next_run"), by=by, recurring=False):
            raise Refused("The ticket changed or the change was not accepted. Try again.")
        return {"ticket": tid, "recurring": False}
    if not phrase:
        raise Refused(f"Say when. For example: {plain.EXAMPLES}.")
    daily = re.fullmatch(r"every day at ([0-9]{1,2})(?::([0-9]{2}))?", phrase.strip().lower())
    if daily:
        phrase = f"daily {int(daily[1]):02d}:{daily[2] or '00'}"
    zone_name = tz or plain.workspace_tz(root) or plain.local_tz_name()
    try:
        plan = plain.Plan(cron=phrase) if valid(phrase) else plain.parse(phrase, zone_name)
    except plain.Plain as e:
        raise Refused(str(e)) from None
    if plan.until:  # a one-off is a core wait
        if each_run:
            raise Refused("Each run as its own ticket is only for repeats.")
        if orchcli.call(root, "wait", tid, "--until", plan.until, by=by or True) is None:
            raise Refused("The wait was not accepted. Try again.")
        return {"ticket": tid, "recurring": False, "until": plan.until}
    if plain.zone(zone_name) is None:
        raise Refused(f"'{zone_name}' is not a time zone. Use a name like Europe/Zurich.")
    changes = {"recurring": True, "cron": plan.cron, "tz": zone_name}
    nxt = next_after(plan.cron, datetime.now(UTC), plain.zone(zone_name))
    if nxt:  # read by core's scheduled health checks: a repeat whose planned time passed long ago stopped
        changes["next_run"] = fmt(nxt)
    if each_run and not plain.daily_or_slower(plan.cron):
        raise Refused('Each run as its own ticket needs a repeat daily or slower, like "daily 07:30".')
    remove = [] if each_run else ["each_run"]
    if script is not None:
        if agent or each_run:
            raise Refused(
                "A repeat runs either a script or an agent, and a script never gets its own sub-tickets."
            )
        if not scripts.NAME_RE.match(script):
            raise Refused(
                "A script name may only have a-z, 0-9 and -. It names a script (orch automation script list)."
            )
        if not scripts.defined(root, script):
            why = scripts.missing(root, script)
            raise Refused(why[0].upper() + why[1:] + ".")
        changes["script"] = script
    if agent:
        remove.append("script")  # an agent again instead of a script
        if not orchcli.AGENT_RE.match(agent):
            raise Refused("The agent name may only have a-z, 0-9 and -. It names an agent (orch agents).")
        changes["agent"] = agent
    if each_run:
        changes["each_run"] = "sub-ticket"
    if not orchcli.set_ext(root, t, remove=tuple(remove), by=by, **changes):
        raise Refused("The ticket changed or the change was not accepted. Try again.")
    return {"ticket": tid, **changes}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="orch automation", description="Starts helper runs: at a time, on a repeat, from the relay inbox."
    )
    ap.add_argument(
        "--dir",
        default=os.environ.get("ORCH_ROOT", "."),
        help="workspace folder (default: ORCH_ROOT or current)",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    r = sub.add_parser("run", parents=[common], help="run in the foreground")
    r.add_argument("--once", action="store_true", help="one pass, wait for the agents, then stop")
    sub.add_parser("start", parents=[common], help="run in the background")
    sub.add_parser("stop", parents=[common], help="stop the background run")
    sub.add_parser("status", parents=[common], help="is it running? (exit 0 when running, 1 when stopped)")
    sub.add_parser("list", parents=[common], help="next wake-ups and repeats")
    sub.add_parser("needs", parents=[common], help="rows for `orch needs`")
    sub.add_parser("view", parents=[common], help="dashboard tab data")
    rp = sub.add_parser(
        "repeat", parents=[common], help="repeat a ticket, or wake it once; say when in plain words"
    )
    rp.add_argument("ticket")
    rp.add_argument("when", nargs="?", help=f"for example: {plain.EXAMPLES}")
    rp.add_argument("--agent", help="name of the agent for this repeat")
    rp.add_argument("--tz", help="time zone of the times (default: this computer's, e.g. Europe/Zurich)")
    rp.add_argument(
        "--each-run", choices=("sub-ticket",), help="give every run its own sub-ticket (daily or slower)"
    )
    rp.add_argument("--script", help="run this script (orch automation script list) instead of an agent")
    rp.add_argument("--off", action="store_true")
    sc = sub.add_parser(
        "script", parents=[common], help="commands a repeat can run instead of an agent (this computer only)"
    )
    scs = sc.add_subparsers(dest="script_cmd", required=True)
    sa = scs.add_parser(
        "add", parents=[common], help="add a script: orch automation script add <name> -- <command>"
    )
    sa.add_argument("name")
    sa.add_argument("command", nargs=argparse.REMAINDER)
    scs.add_parser("list", parents=[common], help="the scripts on this computer")
    sw = scs.add_parser("allow", parents=[common], help="a person allows a script on this computer")
    sw.add_argument("name")
    sw.add_argument("--key", required=True, help="the key orch automation script list shows")
    sr = scs.add_parser("remove", parents=[common], help="remove a script")
    sr.add_argument("name")
    sx = scs.add_parser(
        "run", parents=[common], help="run a ticket's script now and wait (what a repeat does)"
    )
    sx.add_argument("ticket")
    ac = sub.add_parser(
        "act",
        parents=[common],
        help="what the dashboard buttons do: on, off, toggle, run, delete, repeat, copy",
    )
    ac.add_argument("--value", help="when to repeat, in plain words")
    ac.add_argument("verb", choices=actions.VERBS)
    ac.add_argument("target", help="ticket id")
    ac.add_argument("--by", help="who pressed the button (recorded on the ticket); the add-on act contract")
    ac.add_argument(
        "--proof-target", action="store_true", help="say what the person confirms (the dashboard asks first)"
    )
    args = ap.parse_args(argv)
    try:
        root = find_workspace(Path(args.dir))
        if root is None:
            raise Refused("No orch workspace here (no .orch/ folder). Run `orch init` first.")
        return _run(args, root)
    except Refused as e:
        print(
            json.dumps({"error": str(e)}) if args.json else f"Refused: {e}",
            file=None if args.json else sys.stderr,
        )
        return 2


def _run(args, root: Path) -> int:
    def out(data, text: str) -> None:
        print(json.dumps(data) if args.json else text)

    if args.cmd == "run":
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        print(f"orch automation for {root.name} started {datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}", flush=True)
        nonce = service.announce(root)  # background run: record pid + start time in .orch/run/automation/
        try:
            Scheduler(root).run_forever(once=args.once)
        except KeyboardInterrupt:
            pass
        finally:
            service.forget(root, nonce)
    elif args.cmd == "start":
        try:
            pid = service.start(root)
        except RuntimeError as e:
            raise Refused(str(e)) from None
        out({"running": True, "pid": pid}, f"Scheduler running (pid {pid}).")
    elif args.cmd == "stop":
        try:
            res = service.stop(root)
        except RuntimeError as e:
            res = str(e)
        if res in ("stopped", "not running"):
            out(
                {"stopped": res == "stopped"},
                "Scheduler stopped." if res == "stopped" else "Scheduler was not running.",
            )
        else:
            note = (
                "A file in .orch/run/automation/ names a process that is not this scheduler; nothing was stopped."
                if res == "not verified"
                else res
            )
            out({"stopped": False, "note": note}, note)
    elif args.cmd == "status":
        from . import listen

        pid = service.running_pid(root)
        ls = listen.read(root) if pid else {}
        listening = bool(pid and ls.get("listening"))
        heard = (
            "Listening for the phone and other workspaces."
            if listening
            else (ls.get("note") or NOT_LISTENING)
        )
        line = f"Automation is running (pid {pid}). {heard}" if pid else "Automation is not running."
        out({"running": bool(pid), "pid": pid, "listening": listening}, line)
        return 0 if pid else 1
    elif args.cmd == "needs":
        from . import needs

        rs = needs.rows(root)
        out(rs, "\n".join(f"{r['title']}: {r['text']}" for r in rs) or "Nothing needs you here.")
    elif args.cmd == "list":
        rows = describe(root)
        out(rows, "\n".join(list_line(x) for x in rows) or "Nothing scheduled.")
    elif args.cmd == "view":
        from .view import build

        print(json.dumps(build(root)))
    elif args.cmd == "act" and args.proof_target:
        try:
            print(json.dumps(actions.review(root, args.verb, args.target)))
        except actions.Bad as e:
            raise Refused(str(e)) from None
    elif args.cmd == "act":
        try:
            res = actions.act(root, args.verb, args.target, args.by, args.value)
        except actions.Bad as e:
            raise Refused(str(e)) from None
        out(res, res["text"])
    elif args.cmd == "script":
        return _script(args, root, out)
    elif args.cmd == "repeat":
        res = repeat(
            root,
            args.ticket,
            args.when,
            args.off,
            args.agent,
            args.tz,
            bool(args.each_run),
            script=args.script,
        )
        if res.get("until"):
            text = f"{args.ticket} wakes once at {res['until']}."
        elif res["recurring"]:
            text = f"{args.ticket} repeats: {cron_human(res['cron'], plain.zone(res['tz']), local=plain.zone(res['tz']))} ({res['tz']})."
            if res.get("script"):
                text += f" Each time it runs the script {res['script']}, no agent."
        else:
            text = f"{args.ticket} no longer repeats."
        running = bool(service.running_pid(root))
        res["running"] = running
        if not running and not args.off:
            text += "\nRepeating work isn't running here. Start it: orch start"
        out(res, text)
    return 0


def _script(args, root: Path, out) -> int:
    from .loop import ask_failure, script_of

    if args.script_cmd == "add":
        cmd = list(args.command)
        if "--" in cmd:  # options before -- (only --json) belong to orch; everything after it is the command
            cut = cmd.index("--")
            args.json = args.json or "--json" in cmd[:cut]
            cmd = cmd[cut + 1 :]
        try:
            scripts.add(root, args.name, cmd)
        except scripts.ScriptError as e:
            raise Refused(str(e)) from None
        ok = scripts.command(root, args.name) is not None
        text = f"Script {args.name} added on this computer. Use it: orch automation repeat <ticket> " + (
            f'"every 15 minutes" --script {args.name}'
        )
        if not ok:
            text += (
                f"\nIt runs only after a person allows it: orch automation script allow {args.name} "
                f"--key {scripts.key(root, args.name, cmd)}"
            )
        out({"script": args.name, "command": cmd, "allowed": ok}, text)
    elif args.script_cmd == "list":
        rows = []
        for n, c in sorted(scripts.load(root).items()):
            ok = scripts.approved(root, n, c)
            rows.append(
                {"script": n, "command": c, "allowed": ok, **({} if ok else {"key": scripts.key(root, n, c)})}
            )
        out(
            rows,
            "\n".join(
                f"{r['script']}  {scripts.shown(r['command'])}"
                + (
                    ""
                    if r["allowed"]
                    else f"\n  not allowed yet: orch automation script allow {r['script']} --key {r['key']}"
                )
                for r in rows
            )
            or "No scripts on this computer.",
        )
    elif args.script_cmd == "allow":
        try:
            scripts.allow(root, args.name, args.key)
        except scripts.ScriptError as e:
            raise Refused(str(e)) from None
        out({"script": args.name, "allowed": True}, f"Script {args.name} allowed on this computer.")
    elif args.script_cmd == "remove":
        try:
            gone = scripts.remove(root, args.name)
        except scripts.ScriptError as e:
            raise Refused(str(e)) from None
        if not gone:
            raise Refused(f"There is no script named {args.name} on this computer.")
        out(
            {"script": args.name, "removed": True},
            f"Script {args.name} removed. Repeats that name it stop with a question.",
        )
    elif args.script_cmd == "run":
        want = args.ticket.strip().upper()
        t = next(
            (
                x
                for x in orchcli.tickets(root)
                if x["id"] == args.ticket or str(x.get("key") or "").upper() == want
            ),
            None,
        )
        if t is None:
            raise Refused(f"There is no ticket {args.ticket}.")
        name = script_of(t)
        if not name:
            raise Refused(
                f"{args.ticket} runs no script. Set one: orch automation repeat {args.ticket} <when> --script <name>"
            )
        refused = orchcli.sync_refusal(root, t["id"])
        if refused:
            raise Refused(refused)
        code = scripts.run(
            root,
            t["id"],
            name,
            fmt(datetime.now(UTC)),
            lambda why: ask_failure(root, t["id"], f"The script did not work: {why}"),
        )
        if code == 75:
            out({"ticket": t["id"], "running": True}, "It is still running from before.")
            return 0
        out({"ticket": t["id"], "exit": code}, f"Script {name} ended with exit code {code}.")
        return 0 if code == 0 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
