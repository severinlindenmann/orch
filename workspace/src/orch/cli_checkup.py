# ruff: noqa: E501
"""`orch checkup start | list | show | test | accept | rollback | reject | weekly` (contracts/proposal.md, #375).

The check-up's own commands for a person (the dashboard's Insights page calls them). accept, rollback and reject are
a person's own decision: an agent is refused (`needs_person`), and so is a call without a valid proof
(`--proof-stdin`). Every command answers with `--json`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import checkup, tickets
from orch.errors import Refused

SUBCOMMANDS = ("start", "list", "show", "test", "accept", "rollback", "reject", "weekly")


def add_parsers(sub, common) -> None:
    c = sub.add_parser("checkup", help=argparse.SUPPRESS).add_subparsers(dest="sub", required=True)
    for name in ("start", "list"):
        c.add_parser(name, parents=[common], help=argparse.SUPPRESS)
    for name in ("show", "test", "accept", "rollback", "reject"):
        c.add_parser(name, parents=[common], help=argparse.SUPPRESS).add_argument("id")
    w = c.add_parser("weekly", parents=[common], help=argparse.SUPPRESS)
    w.add_argument("state", choices=("on", "off"))


def _say(args, res: dict, text: str) -> None:
    print(json.dumps(res, ensure_ascii=False, separators=(",", ":")) if args.json else text)


def _list_text(res: dict) -> str:
    rows = [f"{p['id']}  {p['status']:<9} {p['title']}" for p in res["proposals"]]
    head = "Check-up is running." if res["running"] else f"Weekly check-up: {res['weekly']}."
    return "\n".join([head, *rows]) if rows else head + "\nNo suggestions."


def dispatch(args, root: Path) -> bool:
    if args.cmd != "checkup":
        return False
    sub = args.sub
    try:
        if sub == "start":
            res = checkup.start(root, tickets.current_actor(getattr(args, "by", None)))
            _say(args, res, f"Check-up {res['result']}: {res['ticket']}")
        elif sub == "list":
            res = checkup.listing(root)
            _say(args, res, _list_text(res))
        elif sub == "show":
            res = checkup.show(root, args.id)
            _say(args, res, f"{res['title']}\n{res['plain']}")
        elif sub == "test":
            res = checkup.run_test(root, args.id)
            _say(args, res, f"{res['id']}: {res['tests']['state']}")
        elif sub in ("accept", "rollback", "reject"):
            res = getattr(checkup, sub)(root, args, args.id)
            _say(args, res, f"{res['id']}: {res['status']}")
        else:
            res = checkup.weekly(root, args, args.state == "on")
            _say(args, res, f"Weekly check-up: {res['weekly']}")
    except checkup.CheckupError:
        raise
    except Refused:
        raise
    return True
