"""`orch needs`. `orch agents` lives in cli_config.py."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import needs as needs_mod


def add_parsers(sub, common) -> None:
    x = sub.add_parser("needs", parents=[common], help="what waits for a person")
    # orch's own detached run: asks GitHub about pull requests left open (stuck.py), prints nothing
    x.add_argument("--look-at-pulls", action="store_true", help=argparse.SUPPRESS)


def _line(r: dict) -> str:
    who = r["ticket"] or r["source"]
    extra = ""
    ans = r.get("answer")
    if ans and ans["options"]:
        extra = "  [" + " | ".join(ans["options"]) + "]"
    elif r.get("cli"):
        extra = f"  ({r['cli']})"
    stale = "  (not up to date)" if r.get("stale") else ""
    return f"  {who:<10}  {r['title']}: {r['text']}{extra}{stale}"


def dispatch(args, root: Path) -> bool:
    if args.cmd != "needs":
        return False
    if args.look_at_pulls:
        from orch import history, stuck, tickets

        stuck.look(root, history.shown_json(root, tickets.list_all(root)))
        return True
    rows = needs_mod.needs(root)
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    elif not rows:
        print("Nothing needs you.")
    else:
        print(f"Needs you ({len(rows)})")
        print("\n".join(_line(r) for r in rows))
    return True
