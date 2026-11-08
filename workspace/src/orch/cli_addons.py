"""`orch addon add|remove|uninstall|list`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import addons


def _out(args, data, text: str) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def add_parsers(sub, common) -> None:
    a = sub.add_parser("addon", help="add-ons: add, remove, list").add_subparsers(dest="sub", required=True)
    x = a.add_parser("add", parents=[common], help="install an add-on and turn it on here")
    x.add_argument("name", metavar="NAME|./FOLDER", help="a built-in add-on name or a local folder")
    x.add_argument("--yes", action="store_true", help="do not ask")
    x.add_argument("--project-only", action="store_true", help=argparse.SUPPRESS)
    x = a.add_parser("remove", parents=[common], help="turn an add-on off in this workspace")
    x.add_argument("name")
    x.add_argument("--purge", action="store_true", help="also delete its data folder and settings")
    x = a.add_parser("uninstall", parents=[common], help="remove an add-on from this computer")
    x.add_argument("name")
    a.add_parser("list", parents=[common])


def dispatch(args, root: Path) -> bool:
    if args.cmd != "addon":
        return False
    sub = getattr(args, "sub", None)
    if sub == "list":
        rows = addons.listing(root)
        _out(
            args,
            rows,
            "\n".join(f"  {r['name']:<12}{'on' if r['active'] else 'off':<6}{r['description']}" for r in rows)
            or "No add-ons are installed. Turn one on with: orch addon add <name>",
        )
    elif sub == "add":
        addons.add(root, args.name, args.yes, args.project_only)
        if args.project_only:
            _out(args, {"ok": True}, f"{args.name} is turned on in this workspace.")
    elif sub == "remove":
        addons.remove(root, args.name, args.purge)
        _out(args, {"ok": True}, f"{args.name} is turned off in this workspace.")
    else:
        addons.uninstall(root, args.name)
        _out(args, {"ok": True}, f"{args.name} is removed from this computer.")
    return True
