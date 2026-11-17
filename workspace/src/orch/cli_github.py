"""`orch github`: the GitHub add-on's hourly write limit for helpers and scripts (no AI call).

    orch github wait <merge|pr|comment|other> [--for "<repo#n>"] [--max-wait <minutes>]
        waits until one write of that kind fits this computer's limit and counts it (a merge with --for only
        waits for room: `orch ref wait --merge` counts it when it really merges); exit 0 = write now,
        exit 2 = no room in time (do not write)
    orch github writes      the writes of the last hour per kind, the limit and when the next one fits
    orch github expert [--dry-run] [--known <problem>=<ticket>]
        the Development expert's read-only pass over CI, pull requests and tickets (devexpert.py); off until
        `orch config set github.dev_expert <role ticket>` and `github.dev_expert_repo <owner/name>`

The limits are settings: `orch config set github.merge_per_hour 12` (also pr_, comment_, other_per_hour).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import ghlimit
from orch.errors import Refused


def add_parsers(sub, common) -> None:
    g = sub.add_parser("github", parents=[common], help=argparse.SUPPRESS).add_subparsers(
        dest="sub", required=True
    )
    w = g.add_parser("wait", parents=[common], help="wait for room for one GitHub write, then count it")
    w.add_argument("kind", choices=ghlimit.KINDS)
    w.add_argument("--for", dest="what", default="", help="what is written (a repo#number), for the log")
    w.add_argument(
        "--max-wait",
        dest="max_wait",
        type=int,
        default=ghlimit.WAIT_SECS // 60,
        help="minutes to wait for room (default 60)",
    )
    g.add_parser("writes", parents=[common], help="GitHub writes of the last hour and the limits")
    e = g.add_parser(
        "expert", parents=[common], help="the Development expert's pass over CI and pull requests"
    )
    e.add_argument("--dry-run", action="store_true", help="only say what it would do")
    e.add_argument(
        "--known",
        action="append",
        metavar="PROBLEM=TICKET",
        help="a red problem that already has its ticket, e.g. nightly-ci=ORCH-32 (no second ticket)",
    )


def _when(secs) -> str:
    if secs is None:
        return "none this hour"
    return f"{secs // 60} min ago" if secs >= 60 else f"{secs} s ago"


def dispatch(args, root: Path | None) -> bool:
    if getattr(args, "cmd", None) != "github":
        return False
    if args.sub == "expert":
        from orch import devexpert

        res = devexpert.run(root, dry_run=args.dry_run, known=devexpert.parse_known(args.known))
        print(json.dumps(res, indent=2, default=str) if args.json else devexpert.text(res, args.dry_run))
        return True
    if args.sub == "wait":
        if args.max_wait < 0:
            raise Refused("--max-wait is a number of minutes, 0 or more.")
        # a merge of a named pull request is counted by `orch ref wait --merge` when it merges: here only wait
        # for room, so waiting helpers and repeated runs never use up the hour
        peek = args.kind == "merge" and bool(args.what)
        secs = args.max_wait * 60
        got = (
            ghlimit.wait_room(args.kind, wait=secs) if peek else ghlimit.take(args.kind, args.what, wait=secs)
        )
        if not got:
            raise Refused(
                f"No room for one of the {ghlimit.WHAT[args.kind]} within {args.max_wait} minutes "
                "(see orch github writes). Do not write to GitHub now; try again later."
            )
        data = {"kind": args.kind, "taken": not peek}
        text = f"Room for one of the {ghlimit.WHAT[args.kind]}: " + (
            "merge it now (orch ref wait --merge counts it when it merges)." if peek else "write it now."
        )
    else:
        rows = ghlimit.status()
        data = {"writes": rows}
        text = "\n".join(
            f"{r['kind']}: {r['used']} of {r['per_hour']} this hour, last {_when(r['last_secs_ago'])}"
            + (f", next fits in {r['next_in_secs']} s" if r["next_in_secs"] > 0 else ", room now")
            for r in rows
        )
    print(json.dumps(data, indent=2) if args.json else text)
    return True
