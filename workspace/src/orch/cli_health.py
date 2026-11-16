"""`orch logins`: does every tool login, connection and key a helper needs here still work (health.py)?

Runs every check now, keeps the result for the dashboard and the phone, and prints one plain sentence per
thing. Only states, end times and ticket names are printed; never anything a tool said (R5.2).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import health, history, net, nextstep

NONE_SET = "Nothing here tells orch whether its login works."


def _out(args, data, text: str) -> None:
    if args.json:
        data = history.shown_json(history.args_root(args), data)
    nextstep.remember(args, data)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def add_parsers(sub, common) -> None:
    # hidden from help until the owner has chosen the words (ORCH-43); the dashboard and phone use it
    sub.add_parser("logins", parents=[common], help=argparse.SUPPRESS)


def line(r: dict) -> str:
    """One plain sentence per row of health.overview."""
    label = r["label"]
    when = net.when(r["ends_at"]) if r["ends_at"] else ""
    n = len(r["stops"])
    on = "; ".join(f"{t['key']} {t['title']}".strip() for t in r["stops"])
    work = f"{n} ticket{'' if n == 1 else 's'}: {on}"
    if r["state"] == "renew":
        text = f"The {label} login ran out {when}." if when else f"The {label} login no longer works."
        text += f" The helper cannot go on with {work}." if n else ""
        return text + (" No new work starts until it is renewed." if r["chosen"] else " Renew it.")
    if r["state"] == "soon":
        return f"The {label} login runs out {when}." + (f" The helper then stops on {work}." if n else "")
    if r["state"] == "works":
        return f"The {label} login works until {when}." if when else f"The {label} login works."
    return f"{label} did not answer, so orch cannot tell whether its login works."


def dispatch(args, root: Path) -> bool:
    if args.cmd != "logins":
        return False
    doc = health.check(root)
    _out(args, doc, "\n".join(line(r) for r in doc["items"]) or NONE_SET)
    return True
