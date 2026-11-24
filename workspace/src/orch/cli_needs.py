"""`orch needs` and `orch counts`. `orch agents` lives in cli_config.py."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import needs as needs_mod


def add_parsers(sub, common) -> None:
    x = sub.add_parser("needs", parents=[common], help="what waits for a person")
    # orch's own detached run: asks GitHub about pull requests left open (stuck.py), prints nothing
    x.add_argument("--look-at-pulls", action="store_true", help=argparse.SUPPRESS)
    # orch's own detached run: saves a fresh answer of an add-on that was late (needs.refresh), prints nothing
    x.add_argument("--refresh-addon", metavar="NAME", help=argparse.SUPPRESS)
    sub.add_parser(
        "counts", parents=[common], help="the numbers every page shows (needs you, working, stuck)"
    )


def _counts_text(c: dict) -> str:
    n, p = c["needs_you"], lambda k, one, many: f"{k} {one if k == 1 else many}"
    return "\n".join(
        [
            f"Needs you: {n['count']} ({p(n['questions'], 'question', 'questions')}, "
            f"{p(n['results'], 'result to check', 'results to check')}"
            + (
                f", {p(n['failed'], 'helper that could not start', 'helpers that could not start')}"
                if n.get("failed")
                else ""
            )
            + ")",
            f"Working: {c['working']}",
            f"Stuck: {c['stuck']}",
        ]
    )


def _line(r: dict) -> str:
    who = r["ticket"] or r["source"]
    extra = ""
    ans = r.get("answer")
    if ans and ans["options"]:
        extra = "  [" + " | ".join(ans.get("labels") or ans["options"]) + "]"
    elif r.get("cli"):
        extra = f"  ({r['cli']})"
    stale = "  (not up to date)" if r.get("stale") else ""
    return f"  {who:<10}  {r['title']}: {r['text']}{extra}{stale}"


def dispatch(args, root: Path) -> bool:
    if args.cmd == "counts":
        from orch import counts

        c = counts.now(root)
        print(json.dumps(c, indent=2, ensure_ascii=False) if args.json else _counts_text(c))
        return True
    if args.cmd != "needs":
        return False
    if args.look_at_pulls:
        from orch import history, stuck, tickets

        stuck.look(root, history.shown_json(root, tickets.list_all(root)))
        return True
    if args.refresh_addon:
        needs_mod.refresh(root, args.refresh_addon)
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
