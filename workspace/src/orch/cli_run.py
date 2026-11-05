"""`orch run ...` (hidden from help until the whole set is built) and the after-command hook."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from orch import adapters, runs, tickets
from orch.errors import Refused

SUBCOMMANDS = (
    "claim",
    "release",
    "status",
    "session",
    "argv",
    "start",
    "send",
    "attach",
    "stop",
    "event",
    "done",
)
NOT_YET = ("send", "attach", "stop", "event", "done")


def add_parsers(sub, common) -> None:
    r = sub.add_parser("run", help=argparse.SUPPRESS).add_subparsers(dest="sub")
    for name in SUBCOMMANDS:
        x = r.add_parser(name, parents=[common], help=argparse.SUPPRESS)
        if name in NOT_YET:
            x.add_argument("rest", nargs=argparse.REMAINDER)
            continue
        x.add_argument("ticket")
        if name in ("claim", "start", "argv"):
            x.add_argument("--mode", choices=("oneshot", "live"), default="oneshot")
        if name in ("claim", "session", "argv"):
            x.add_argument("--agent", help="which agent (default: the one chosen for this folder)")
        if name == "claim":
            x.add_argument("--session", help="the agent's session id, if known")
            x.add_argument("--pid", type=int, help="process of the agent")
            x.add_argument("--take-over", action="store_true")
            x.add_argument("--text", help="what to queue when the ticket is busy")
        if name == "release":
            x.add_argument("--run", help="only if this run holds the claim")
        if name in ("start", "argv"):
            x.add_argument("--fresh", action="store_true", help="do not continue the earlier conversation")
            x.add_argument(
                "--allow", action="append", default=[], metavar="TOOL", help="allow a tool for this run"
            )
        if name == "start":
            x.add_argument("--take-over", action="store_true", help="take over a claim nobody has written to")
            x.add_argument("--text", help="what to queue when the ticket is busy")
        if name == "argv":
            x.add_argument("--prompt-file", help="use this text as the prompt instead of the ticket summary")
    w = r.add_parser("_wrap", help=argparse.SUPPRESS)
    w.add_argument("rest", nargs=argparse.REMAINDER)


def _out(args, data, text: str) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def _wrap_cmd(root: Path, rest: list[str]) -> None:
    if "--" not in rest:
        raise Refused("orch run _wrap is internal.")
    i = rest.index("--")
    p = argparse.ArgumentParser(prog="orch run _wrap")
    p.add_argument("run")
    p.add_argument("--ticket", required=True)
    p.add_argument("--agent", required=True)
    p.add_argument("--fresh", action="store_true")
    p.add_argument("--resumed", action="store_true")
    p.add_argument("--allow", action="append", default=[])
    p.add_argument("--stdin-file")
    p.add_argument("--new-session")
    p.add_argument("--items", default="")
    a = p.parse_args(rest[:i])
    stdin = None
    rec = runs.read(root, a.ticket)
    if not rec or rec["run"] != a.run:
        raise Refused("orch run _wrap is internal.")
    if a.stdin_file:
        f = Path(a.stdin_file)
        if f.resolve() != (runs.run_dir(root) / f"prompt-{a.run}.txt").resolve():
            raise Refused("orch run _wrap is internal.")  # never read or delete any other file
        stdin = f.read_text(encoding="utf-8")
        f.unlink(missing_ok=True)
    code = runs.wrap(
        root,
        a.run,
        a.ticket,
        a.agent,
        rest[i + 1 :],
        fresh=a.fresh,
        resumed=a.resumed,
        allow=a.allow,
        stdin=stdin,
        new_session=a.new_session,
        item_ids=[x for x in a.items.split(",") if x],
    )
    sys.exit(code)


def _chosen_or_generic(root: Path) -> str:
    try:
        return adapters.chosen(root)
    except Refused:
        return "generic"  # a hand-started agent we know nothing about


def _holder_line(rec: dict, tid: str) -> str:
    who = adapters.load(rec["agent"])["label"] if rec["agent"] in adapters.builtin_names() else rec["agent"]
    since = rec.get("started_at", "")[11:16]
    return f"{tid} is being worked on by {rec['by']} ({who}) since {since}."


def _status(args, root: Path) -> None:
    tid = args.ticket
    tickets.load(root, tid)
    rec = runs.read(root, tid)
    waiting = len(runs.undelivered(root, tid))
    if not rec:
        data = {"ticket": tid, "running": False, "pending": waiting}
        _out(
            args,
            data,
            "Queued. Nothing will start it: no background add-on is running here. "
            f"Start it: orch run start {tid}",
        )
        return
    st = runs.state(rec)
    data = {"ticket": tid, "running": st == "alive", "state": st, "pending": waiting, "claim": rec}
    if st == "dead":
        text = f"The earlier run on {tid} ended without finishing. Start it again: orch run start {tid}"
    elif st == "maybe-stale":
        text = (
            f"{_holder_line(rec, tid)} Nobody has written to the ticket for a while, so it may be stuck. "
            f"Take it over: orch run start {tid} --take-over"
        )
    else:
        text = _holder_line(rec, tid) + (f" {waiting} more waiting." if waiting else "")
    _out(args, data, text)


def dispatch(args, root: Path) -> bool:
    if args.cmd != "run":
        return False
    sub = args.sub
    if sub == "_wrap":
        _wrap_cmd(root, args.rest)
        return True
    if sub in NOT_YET or sub is None:
        raise Refused("orch run is not available yet.")
    by = args.by or tickets.current_actor()
    if not 1 <= len(by) <= 64 or any(ord(c) < 32 for c in by):
        raise Refused("--by must be 1 to 64 characters, e.g. agent:helper.")
    tid = args.ticket
    if sub == "claim":
        name = args.agent or adapters.detect_env(os.environ) or _chosen_or_generic(root)
        try:
            rec = runs.claim(
                root, tid, by, name, args.mode, pid=args.pid, take_over=args.take_over, busy_text=args.text
            )
        except runs.Busy as e:
            e.extra["claimed"] = False
            raise
        if args.session:
            tickets.record_session(root, tid, name, args.session, runs.host())
        _out(args, {"claimed": True, "run": rec["run"]}, f"Claimed {tid} (run {rec['run']}).")
    elif sub == "release":
        run_id = args.run or os.environ.get("ORCH_RUN")
        rec = runs.read(root, tid)
        if rec and not run_id and isinstance(rec.get("pid"), int) and runs.state(rec) == "alive":
            raise Refused(
                f"An agent process is working on {tid}. Only that run can release it (--run {rec['run']})."
            )
        res = runs.release(root, tid, run_id)
        _out(args, res, "Released." if res["released"] else "Nothing to release.")
    elif sub == "status":
        _status(args, root)
    elif sub == "session":
        name = args.agent or adapters.chosen(root)
        sid = tickets.sessions_for(tickets.load(root, tid), name, runs.host())
        _out(args, {"agent": name, "session": sid}, sid or "")
    elif sub == "argv":
        prompt = Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else None
        if args.mode != "oneshot":
            raise Refused("Only --mode oneshot is available here.")
        p = runs.plan(
            root, tid, fresh=args.fresh, mode=args.mode, allow=args.allow, prompt=prompt, agent=args.agent
        )
        p = {k: v for k, v in p.items() if k not in ("stdin", "item_ids")}
        _out(args, p, "\n".join(p["argv"]))
    elif sub == "start":
        r = runs.start(
            root,
            tid,
            by,
            fresh=args.fresh,
            take_over=args.take_over,
            allow=args.allow,
            mode=args.mode,
            text=args.text,
        )
        for note in r["notes"]:
            print(note, file=sys.stderr)
        how = "Continued the earlier conversation" if r["resumed"] else "Started fresh from the ticket"
        _out(args, r, f"{how} ({r['agent']}). Run {r['run']}. Log: {r['log']}")
    return True


def after_command(args, root: Path, stdout_is_json: bool) -> None:
    """Runs after every command inside an agent run: the footer, on stderr only (stdout stays as it was)."""
    if getattr(args, "cmd", None) == "run":
        return
    try:
        line = runs.footer(root, getattr(args, "by", None), getattr(args, "id", None))
    except Exception:  # a footer must never break the command it follows
        return
    if line:
        print(line, file=sys.stderr)
