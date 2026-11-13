"""`orch addon add|remove|uninstall|list`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import addons, history, humanproof
from orch.errors import Refused


def _out(args, data, text: str) -> None:
    if args.json:
        data = history.shown_json(history.args_root(args), data)
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
        have = [r for r in rows if r["installed"]]
        avail = [r for r in rows if not r["installed"]]
        text = "\n".join(
            f"  {r['name']:<12}{'on' if r['active'] else 'off':<6}{r['description']}" for r in have
        )
        text = text or "No add-ons are installed. Turn one on with: orch addon add <name>"
        if avail:
            text += "\n\nAvailable (not installed yet; add one with: orch addon add <name>)\n" + "\n".join(
                f"  {r['name']:<12}{r['description']}" for r in avail
            )
        _out(args, rows, text)
    elif sub == "add":
        if not args.project_only and (addons._is_path(args.name) or args.name not in addons.CORE_ADDONS):
            addons.tool_env_change_ok()  # first, before any snapshot or hand-off: a click cannot fix this
        if addons._is_path(args.name) and not addons._local_add_ok():
            # code from a folder runs inside orch itself: only a person's click (proof) may allow it (H1)
            # Snapshot the folder NOW (request time): the card shows the path and a short content hash, the
            # proof's target is the full hash. The proven add installs from the snapshot with that hash and is
            # refused when the folder changed since (a content swap before the click).
            info = addons.prepare_local_add(root, Path(args.name))
            # the queued command carries the ABSOLUTE path the card shows (it runs later with cwd = the
            # workspace root, where a relative `./x` would mean another folder)
            queued = [
                info["path"] if w == args.name else w
                for w in humanproof._clean_argv(humanproof.CURRENT_ARGV) or []
            ]
            who = humanproof.person_by(
                root,
                args,
                "addon.add_local",
                info["hash"],
                argv=queued,
                parts={"path": humanproof.tail(info["path"]), "short": humanproof.part(info["short"])},
                exact=info["path"],
            )
            if not who.startswith("human:"):
                raise Refused(humanproof.AGENT_REFUSED)
            with addons.trusted_local_add(info["hash"]):
                addons.add(root, args.name, args.yes, args.project_only)
        else:
            addons.add(root, args.name, args.yes, args.project_only)
        if args.project_only:
            _out(args, {"ok": True}, f"{args.name} is turned on in this workspace.")
    elif sub == "remove":
        addons.remove(root, args.name, args.purge)
        _out(args, {"ok": True}, f"{args.name} is turned off in this workspace.")
    else:
        addons.tool_env_change_ok()
        addons.uninstall(root, args.name)
        _out(args, {"ok": True}, f"{args.name} is removed from this computer.")
    return True
