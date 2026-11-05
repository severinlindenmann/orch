"""`orch needs` and `orch agents` (hidden until built)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import needs as needs_mod
from orch.errors import Refused


def add_parsers(sub, common) -> None:
    sub.add_parser("needs", parents=[common], help="what waits for a person")
    x = sub.add_parser("agents", parents=[common], help=argparse.SUPPRESS)
    x.add_argument("rest", nargs=argparse.REMAINDER)


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
    if args.cmd == "agents":
        raise Refused("orch agents is not available yet.")
    if args.cmd != "needs":
        return False
    rows = needs_mod.needs(root)
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    elif not rows:
        print("Nothing needs you.")
    else:
        print(f"Needs you ({len(rows)})")
        print("\n".join(_line(r) for r in rows))
    return True
