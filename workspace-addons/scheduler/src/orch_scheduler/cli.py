"""`orch scheduler`: run, start, stop, status, list, repeat, view. Exit 0 ok, 2 refused (plain words), like the core."""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import orchcli, service
from .cron import fmt, next_after, valid
from .loop import OPEN, Scheduler
from .runner import load_state


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
        s = (t.get("ext") or {}).get("scheduler") or {}
        if s.get("recurring") is True and s.get("cron"):
            nxt = next_after(s["cron"], datetime.now(UTC))
            rows.append({"ticket": t["id"], "title": t["title"], "kind": "repeat", "cron": s["cron"],
                         "at": fmt(nxt) if nxt else state.get(t["id"], {}).get("next_run")})
    return sorted(rows, key=lambda r: r["at"] or "")


def repeat(root: Path, tid: str, cron: str | None, off: bool, agent: str | None = None) -> dict:
    t = next((x for x in orchcli.tickets(root) if x["id"] == tid), None)
    if t is None:
        raise Refused(f"There is no ticket {tid}.")
    if off:
        changes = {"recurring": False}
    else:
        if not cron or not valid(cron):
            raise Refused("Give five cron fields, e.g. \"0 7 * * 1\" (minute hour day month weekday, UTC).")
        changes = {"recurring": True, "cron": cron}
        if agent:
            if not re.fullmatch(r"[a-z0-9-]{1,32}", agent):
                raise Refused("The agent name may only have a-z, 0-9 and -. It names an agent.")
            changes["agent"] = agent
    if not orchcli.set_ext(root, t, **changes):
        raise Refused("The ticket changed or the change was not accepted. Try again.")
    return {"ticket": tid, **changes}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="orch scheduler", description="Starts agent runs: at a time, on a repeat, from the relay inbox.")
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
    sub.add_parser("view", parents=[common], help="dashboard tab data")
    rp = sub.add_parser("repeat", parents=[common], help="repeat a ticket by cron (UTC), or --off")
    rp.add_argument("ticket")
    rp.add_argument("cron_pos", nargs="?", metavar="cron")
    rp.add_argument("--cron")
    rp.add_argument("--agent", help="name of the agent for this repeat")
    rp.add_argument("--off", action="store_true")
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
        print(f"orch scheduler for {root.name} started {datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}", flush=True)
        nonce = service.announce(root)  # background run: record pid + start time in .orch/run/scheduler/
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
            note = ("A file in .orch/run/scheduler/ names a process that is not this scheduler; nothing was stopped."
                    if res == "not verified" else res)
            out({"stopped": False, "note": note}, note)
    elif args.cmd == "status":
        pid = service.running_pid(root)
        out({"running": bool(pid), "pid": pid}, f"Scheduler running (pid {pid})." if pid else "Scheduler is not running.")
        return 0 if pid else 1
    elif args.cmd == "list":
        rows = describe(root)
        out(rows, "\n".join(f"{x['ticket']}  {x['kind']} {x.get('cron', '')} {x['at']}  {x['title']}" for x in rows) or "Nothing scheduled.")
    elif args.cmd == "view":
        from .view import build
        print(json.dumps(build(root)))
    elif args.cmd == "repeat":
        res = repeat(root, args.ticket, args.cron or args.cron_pos, args.off, args.agent)
        out(res, f"{args.ticket} repeats ({res['cron']} UTC)." if res["recurring"] else f"{args.ticket} no longer repeats.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
