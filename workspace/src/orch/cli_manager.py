"""`orch manager start|stop|status`: the workspace's always-on Manager session (ORCH-147, manager.py)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from orch import manager, nextstep, tickets


def add_parsers(sub, common) -> None:
    s = sub.add_parser("manager", help="the always-on Manager session").add_subparsers(
        dest="sub", required=True
    )
    x = s.add_parser("start", parents=[common], help="start the Manager (made the first time); it stays on")
    x.add_argument("--fresh", action="store_true", help="end its conversation and start an empty one")
    s.add_parser("stop", parents=[common], help="end the Manager's session (its conversation is kept)")
    s.add_parser("status", parents=[common], help="is the Manager on, and how to join it from a terminal")


def _out(args, data, text: str) -> None:
    nextstep.remember(args, data)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def dispatch(args, root: Path) -> bool:
    if args.cmd != "manager":
        return False
    if args.sub == "start":
        d = manager.start(root, tickets.acting_by(args), fresh=args.fresh)
        for note in d.get("notes") or []:
            print(note, file=sys.stderr)
        how = (
            "Started the Manager fresh."
            if d["fresh"]
            else "Started the Manager."
            if d["started"]
            else "The Manager is already on."
        )
        _out(args, d, f"{how} Join it in a terminal: {d['attach']}")
    elif args.sub == "stop":
        d = manager.stop(root)
        _out(
            args,
            d,
            "Stopped the Manager. Its conversation is kept." if d["stopped"] else "The Manager is not on.",
        )
    else:
        d = manager.status(root)
        text = (
            "No Manager yet. Start it: orch manager start"
            if d["ticket"] is None
            else f"The Manager is on. Join it in a terminal: {d['attach']}"
            if d["running"]
            else "The Manager is off. Start it: orch manager start"
        )
        _out(args, d, text)
    return True
