"""`orch logins`: does every tool login, connection and key a helper needs here still work (health.py)?

Runs every check now, keeps the result for the dashboard and the phone, and prints one plain sentence per
thing. Only states, end times and ticket names are printed; never anything a tool said (R5.2).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orch import health, history, net, nextstep, renew, tickets
from orch.errors import Refused

NONE_SET = "Nothing here tells orch whether it works."


def _out(args, data, text: str) -> None:
    if args.json:
        data = history.shown_json(history.args_root(args), data)
    nextstep.remember(args, data)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def add_parsers(sub, common) -> None:
    # hidden from help until the owner has chosen the words (ORCH-43); the dashboard and phone use it
    p = sub.add_parser("logins", parents=[common], help=argparse.SUPPRESS)
    acts = p.add_subparsers(dest="logins_action")
    r = acts.add_parser("renew", parents=[common], help=argparse.SUPPRESS)  # ORCH-46: the tool's own sign-in
    r.add_argument("name")
    how = r.add_mutually_exclusive_group()
    how.add_argument("--code", metavar="-", help=argparse.SUPPRESS)  # '-' = the code on stdin (never argv)
    how.add_argument("--status", action="store_true", help=argparse.SUPPRESS)
    how.add_argument("--cancel", action="store_true", help=argparse.SUPPRESS)
    how.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)  # the background worker
    k = acts.add_parser("replace", parents=[common], help=argparse.SUPPRESS)  # a key: new value on stdin
    k.add_argument("name")


def line(r: dict) -> str:
    """One plain sentence per row of health.overview."""
    label = r["label"]
    kind = r.get("kind") or "login"  # older saved results have no kind: they were all logins
    when = net.when(r["ends_at"]) if r["ends_at"] else ""
    n = len(r["stops"])
    on = "; ".join(f"{t['key']} {t['title']}".strip() for t in r["stops"])
    work = f"{n} ticket{'' if n == 1 else 's'}: {on}"
    if r["state"] == "renew":
        text = f"The {label} {kind} ran out {when}." if when else f"The {label} {kind} no longer works."
        text += f" The helper cannot go on with {work}." if n else ""
        return text + (" No new work starts until it is renewed." if r["chosen"] else " Renew it.")
    if r["state"] == "soon":
        return f"The {label} {kind} runs out {when}." + (f" The helper then stops on {work}." if n else "")
    if r["state"] == "works":
        return f"The {label} {kind} works until {when}." if when else f"The {label} {kind} works."
    return f"{label} did not answer, so orch cannot tell whether its {kind} works."


RENEW_SAYS = {
    "none": "No sign-in was started for this login.",
    "starting": "The sign-in is starting.",
    "link": "Open this link and sign in: {link}\n"
    "If the page shows a code, paste it with: orch logins renew {name} --code -",
    "checking": "orch is checking the login.",
    "done": "The login is renewed.",
    "failed": "The sign-in did not finish. Press Renew to try again.",
    "stopped": "The sign-in was closed.",
}


AGAIN = "The tool did not take that code. Copy the whole code from the sign-in page and paste it again."


def renew_line(st: dict) -> str:
    if st.get("state") == "link" and st.get("again"):
        return AGAIN + f"\nPaste it with: orch logins renew {st.get('name') or ''} --code -"
    text = RENEW_SAYS.get(st.get("state"), RENEW_SAYS["failed"]).format(
        link=st.get("link") or "", name=st.get("name") or ""
    )
    if st.get("state") == "done" and st.get("went_on"):
        text += " Helpers go on with " + ", ".join(st["went_on"]) + "."
    return text


def _stdin_line() -> str:
    return sys.stdin.read(4096).strip()


def _hidden(prompt: str) -> str:
    """A person at a terminal: the value is typed hidden, never shown or kept in the shell history."""
    import getpass

    return getpass.getpass(prompt, stream=sys.stderr)


def dispatch(args, root: Path) -> bool:
    if args.cmd != "logins":
        return False
    action = getattr(args, "logins_action", None)
    if action == "renew":
        if args.worker:
            raise SystemExit(renew.work(root, args.name))
        by = tickets.acting_by(
            args
        )  # renew.person_only: a dashboard grant or a person at a terminal, else refused
        if args.code is not None:
            how = renew.person_only(root, by)  # before anything is read
            if args.code != "-":
                raise Refused(
                    "Paste the code when asked, not on the command line: orch logins renew <name> --code -"
                )
            text = _hidden("Code from the sign-in page: ") if how == "terminal" else _stdin_line()
            st = renew.code(root, args.name, text, by=by)
        elif args.status:
            st = renew.status(root, args.name, by=by)
        elif args.cancel:
            st = renew.cancel(root, args.name, by=by)
        else:
            st = renew.start(root, args.name, by=by)
        _out(args, st, renew_line(st))
        return True
    if action == "replace":
        by = tickets.acting_by(args)
        how = renew.person_only(root, by)  # before the value is read
        value = _hidden("New key (hidden while you type): ") if how == "terminal" else sys.stdin.read(65537)
        res = renew.replace_key(root, args.name, value, by=by)
        ok = res["state"] in ("works", "soon")
        text = "The new key is in and works." if ok else "The new key is in, but the check still fails."
        if res.get("went_on"):
            text += " Helpers go on with " + ", ".join(res["went_on"]) + "."
        _out(args, res, text)
        return True
    doc = health.check(root)
    _out(args, doc, "\n".join(line(r) for r in doc["items"]) or NONE_SET)
    return True
