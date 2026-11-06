"""`orch automation`: run, start, stop, status, list, repeat, view. Exit 0 ok, 2 refused (plain words), like the core."""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import actions, orchcli, plain, service
from .cron import fmt, next_after, valid
from .listen import NOT_LISTENING
from .loop import OPEN, Scheduler
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


def describe(root: Path) -> list[dict]:
    """Next wake-ups and repeats, soonest first."""
    state = load_state(root)
    rows = []
    for t in orchcli.tickets(root):
        if t["status"] not in OPEN:
            continue
        w = t.get("waiting_on") or {}
        if w.get("kind") == "time" and w.get("until"):
            rows.append({"ticket": t["id"], "title": t["title"], "kind": "wake", "at": w["until"]})
        s = (t.get("ext") or {}).get("automation") or {}
        if s.get("recurring") is True and s.get("cron"):
            if s.get("paused") is True:  # switched off: listed, no next time
                rows.append({"ticket": t["id"], "title": t["title"], "kind": "repeat", "cron": s["cron"], "at": None, "off": True})
                continue
            nxt = next_after(s["cron"], datetime.now(UTC), plain.zone(s.get("tz")))
            rows.append({"ticket": t["id"], "title": t["title"], "kind": "repeat", "cron": s["cron"],
                         "at": fmt(nxt) if nxt else state.get(t["id"], {}).get("next_run")})
    return sorted(rows, key=lambda r: r["at"] or "")


def repeat(root: Path, tid: str, phrase: str | None, off: bool, agent: str | None = None, tz: str | None = None,
           each_run: bool = False) -> dict:
    t = next((x for x in orchcli.tickets(root) if x["id"] == tid), None)
    if t is None:
        raise Refused(f"There is no ticket {tid}.")
    if off:
        if not orchcli.set_ext(root, t, remove=("each_run",), recurring=False):
            raise Refused("The ticket changed or the change was not accepted. Try again.")
        return {"ticket": tid, "recurring": False}
    if not phrase:
        raise Refused(f"Say when. For example: {plain.EXAMPLES}.")
    zone_name = tz or plain.workspace_tz(root) or plain.local_tz_name()
    try:
        plan = plain.Plan(cron=phrase) if valid(phrase) else plain.parse(phrase, zone_name)
    except plain.Plain as e:
        raise Refused(str(e)) from None
    if plan.until:  # a one-off is a core wait
        if each_run:
            raise Refused("Each run as its own ticket is only for repeats.")
        if orchcli.call(root, "wait", tid, "--until", plan.until) is None:
            raise Refused("The wait was not accepted. Try again.")
        return {"ticket": tid, "recurring": False, "until": plan.until}
    if plain.zone(zone_name) is None:
        raise Refused(f"'{zone_name}' is not a time zone. Use a name like Europe/Zurich.")
    changes = {"recurring": True, "cron": plan.cron, "tz": zone_name}
    if each_run and not plain.daily_or_slower(plan.cron):
        raise Refused("Each run as its own ticket needs a repeat daily or slower, like \"daily 07:30\".")
    if agent:
        if not orchcli.AGENT_RE.match(agent):
            raise Refused("The agent name may only have a-z, 0-9 and -. It names an agent (orch agents).")
        changes["agent"] = agent
    if each_run:
        changes["each_run"] = "sub-ticket"
    if not orchcli.set_ext(root, t, remove=() if each_run else ("each_run",), **changes):
        raise Refused("The ticket changed or the change was not accepted. Try again.")
    return {"ticket": tid, **changes}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="orch automation", description="Starts agent runs: at a time, on a repeat, from the relay inbox.")
    ap.add_argument("--dir", default=os.environ.get("ORCH_ROOT", "."), help="workspace folder (default: ORCH_ROOT or current)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    r = sub.add_parser("run", parents=[common], help="run in the foreground")
    r.add_argument("--once", action="store_true", help="one pass, wait for the agents, then stop")
    sub.add_parser("start", parents=[common], help="run in the background")
    sub.add_parser("stop", parents=[common], help="stop the background run")
    sub.add_parser("status", parents=[common], help="is it running?")
    sub.add_parser("list", parents=[common], help="next wake-ups and repeats")
    sub.add_parser("migrate", parents=[common], help="take over what the old scheduler left (safe to repeat)")
    sub.add_parser("needs", parents=[common], help="rows for `orch needs`")
    sub.add_parser("view", parents=[common], help="dashboard tab data")
    rp = sub.add_parser("repeat", parents=[common], help="repeat a ticket, or wake it once; say when in plain words")
    rp.add_argument("ticket")
    rp.add_argument("when", nargs="?", help=f"for example: {plain.EXAMPLES}")
    rp.add_argument("--agent", help="name of the agent for this repeat")
    rp.add_argument("--tz", help="time zone of the times (default: this computer's, e.g. Europe/Zurich)")
    rp.add_argument("--each-run", choices=("sub-ticket",), help="give every run its own sub-ticket (daily or slower)")
    rp.add_argument("--off", action="store_true")
    ac = sub.add_parser("act", parents=[common], help="what the dashboard buttons do: on, off, toggle, run, delete")
    ac.add_argument("verb", choices=actions.VERBS)
    ac.add_argument("target", help="ticket id")
    args = ap.parse_args(argv)
    try:
        root = find_workspace(Path(args.dir))
        if root is None:
            raise Refused("No orch workspace here (no .orch/ folder). Run `orch init` first.")
        return _run(args, root)
    except Refused as e:
        print(json.dumps({"error": str(e)}) if args.json else f"Refused: {e}", file=None if args.json else sys.stderr)
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
            out({"stopped": res == "stopped"}, "Scheduler stopped." if res == "stopped" else "Scheduler was not running.")
        else:
            note = ("A file in .orch/run/automation/ names a process that is not this scheduler; nothing was stopped."
                    if res == "not verified" else res)
            out({"stopped": False, "note": note}, note)
    elif args.cmd == "status":
        from . import listen

        pid = service.running_pid(root)
        ls = listen.read(root) if pid else {}
        listening = bool(pid and ls.get("listening"))
        heard = "Listening for the phone and other workspaces." if listening else (ls.get("note") or NOT_LISTENING)
        line = f"Scheduler running (pid {pid}). {heard}" if pid else "Scheduler is not running."
        out({"running": bool(pid), "pid": pid, "listening": listening}, line)
        return 0 if pid else 1
    elif args.cmd == "migrate":
        from . import migrate

        res = migrate.run(root)
        out(res, f"Moved {res['tickets']} ticket(s), {res['files']} file(s)." + (" Settings moved." if res["config"] else "")
            + (f" {res['note']}" if res.get("note") else ""))
    elif args.cmd == "needs":
        from . import needs

        rs = needs.rows(root)
        out(rs, "\n".join(f"{r['title']}: {r['text']}" for r in rs) or "Nothing needs you here.")
    elif args.cmd == "list":
        rows = describe(root)
        out(rows, "\n".join(f"{x['ticket']}  {x['kind']} {x.get('cron', '')} {x['at'] or 'off'}  {x['title']}" for x in rows) or "Nothing scheduled.")
    elif args.cmd == "view":
        from .view import build
        print(json.dumps(build(root)))
    elif args.cmd == "act":
        try:
            res = actions.act(root, args.verb, args.target)
        except actions.Bad as e:
            raise Refused(str(e)) from None
        out(res, res["text"])
    elif args.cmd == "repeat":
        res = repeat(root, args.ticket, args.when, args.off, args.agent, args.tz, bool(args.each_run))
        if res.get("until"):
            text = f"{args.ticket} wakes once at {res['until']}."
        elif res["recurring"]:
            text = f"{args.ticket} repeats: {cron_human(res['cron'], plain.zone(res['tz']))} ({res['tz']})."
        else:
            text = f"{args.ticket} no longer repeats."
        running = bool(service.running_pid(root))
        res["running"] = running
        if not running and not args.off:
            text += "\nRepeating work isn't running here. Start it: orch start"
        out(res, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
