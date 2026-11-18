"""`orch session new|list|close`: sessions without a ticket (ORCH-364, sessions.py): empty helper, chat
helper, plain terminal, Manager."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from orch import nextstep, sessions, tickets


def add_parsers(sub, common) -> None:
    s = sub.add_parser("session", help="sessions without a ticket").add_subparsers(dest="sub", required=True)
    x = s.add_parser(
        "new", parents=[common], help="start a session without a ticket (or go to the one that is on)"
    )
    x.add_argument("kind", choices=sessions.KINDS)
    s.add_parser("list", parents=[common], help="the sessions without a ticket and whether they are open")
    x = s.add_parser(
        "close", parents=[common], help="end a session without a ticket (a helper's conversation is kept)"
    )
    x.add_argument("kind", choices=sessions.KINDS)


def _out(args, data, text: str) -> None:
    nextstep.remember(args, data)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def dispatch(args, root: Path) -> bool:
    if args.cmd != "session":
        return False
    by = tickets.acting_by(args)
    if args.sub == "new":
        d = sessions.new(root, args.kind, by)
        for note in d.get("notes") or []:
            print(note, file=sys.stderr)
        name = d.get("title", args.kind)
        _out(args, d, f"Started the {name}." if d.get("started") else f"The {name} is already open.")
    elif args.sub == "close":
        d = sessions.close(root, args.kind, by)
        name = d.get("title", args.kind)
        _out(args, d, f"Closed the {name}." if d.get("closed") else f"The {name} is not open.")
    else:
        rows = sessions.listing(root)
        text = (
            "\n".join(f"{r['title']}: {'open' if r['open'] else 'closed'}" for r in rows)
            or "No session without a ticket yet."
        )
        _out(args, {"sessions": rows}, text)
    return True
