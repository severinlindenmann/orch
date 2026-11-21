"""`orch session new|list|stop|end`: sessions without a ticket (ORCH-364, sessions.py): empty helper, chat
helper, plain terminal, Manager. Stop ends the current step (the session stays); end ends the session, which
stays in History (ORCH-817). `close` is the older name of `end`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orch import nextstep, ownerpick, sessionmode, sessions, tickets
from orch.errors import Refused


def add_parsers(sub, common) -> None:
    s = sub.add_parser("session", help="sessions without a ticket").add_subparsers(dest="sub", required=True)
    x = s.add_parser(
        "new", parents=[common], help="start a session without a ticket (or go to the one that is on)"
    )
    x.add_argument("kind", choices=sessions.KINDS)
    x.add_argument(
        "--permission-mode",
        choices=sessionmode.MODES,
        help="start in this permission mode (ask = Default, edits = Accept edits, auto, full = Bypass "
        "permissions), remembered for this kind; a session that is on goes on in it. Raising it needs the "
        "signed-in person on the dashboard",
    )
    x.add_argument(
        "--model", choices=("haiku", "sonnet", "opus", "fable"), help="the model the Empty helper starts on"
    )
    s.add_parser("list", parents=[common], help="the sessions without a ticket and whether they are open")
    x = s.add_parser(
        "stop", parents=[common], help="stop the current step of a session without a ticket (it stays open)"
    )
    x.add_argument("kind", choices=sessions.KINDS)
    for name in ("end", "close"):  # close: the older name of end
        x = s.add_parser(
            name,
            parents=[common],
            help="end a session without a ticket (a helper's conversation is kept in History)"
            if name == "end"
            else argparse.SUPPRESS,
        )
        x.add_argument("kind", choices=sessions.KINDS)


def _out(args, data, text: str) -> None:
    nextstep.remember(args, data)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def _mode_words(row: dict) -> str:
    pm = row.get("permissions") or {}
    words = pm.get("running_label") or pm.get("label")
    return f" ({words})" if words else ""


def dispatch(args, root: Path) -> bool:
    if args.cmd != "session":
        return False
    by = tickets.acting_by(args)
    if args.sub == "new":
        mode = args.permission_mode
        # ORCH-818: only the dashboard's signed-in page hands this call a person grant. Used up first, needed
        # or not, so it never reaches the helper this call starts.
        person = ownerpick.person_granted(root, by)
        d = sessions.new(root, args.kind, by, model=getattr(args, "model", None), mode=mode, person=person)
        for note in d.get("notes") or []:
            print(note, file=sys.stderr)
        name = d.get("title", args.kind)
        _out(args, d, f"Started the {name}." if d.get("started") else f"The {name} is already open.")
    elif args.sub in ("end", "close"):
        d = sessions.close(root, args.kind, by)
        name = d.get("title", args.kind)
        kept = (
            ""
            if args.kind == "terminal"
            else f" Its conversation is in History: orch session new {args.kind} continues it."
        )
        _out(args, d, f"Ended the {name}.{kept}" if d.get("closed") else f"The {name} is not open.")
    elif args.sub == "stop":
        d = sessions.interrupt(root, args.kind)
        name = d.get("title", args.kind)
        if not d.get("interrupted"):
            raise Refused(f"The {name} is not open, so there is no step to stop.")
        _out(args, d, f"Stopped the current step of the {name}. It stays open; send it a message to go on.")
    else:
        rows = sessions.listing(root)
        text = (
            "\n".join(f"{r['title']}: {'open' if r['open'] else 'closed'}{_mode_words(r)}" for r in rows)
            or "No session without a ticket yet."
        )
        _out(args, {"sessions": rows}, text)
    return True
