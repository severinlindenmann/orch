"""`orch addon add|remove|uninstall|list`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import addonjob, addons, history, nextstep
from orch.errors import Refused


def _out(args, data, text: str) -> None:
    if args.json:
        data = history.shown_json(history.args_root(args), data)
    nextstep.remember(args, data)
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def add_parsers(sub, common) -> None:
    a = sub.add_parser("addon", help="add-ons: add, remove, list").add_subparsers(dest="sub", required=True)
    x = a.add_parser("add", parents=[common], help="install add-ons and turn them on here")
    x.add_argument(
        "names",
        nargs="+",
        metavar="NAME|./FOLDER",
        help="built-in add-on names (several at once: one install), or one local folder",
    )
    x.add_argument("--yes", action="store_true", help="do not ask")
    x.add_argument("--job", action="store_true", help=argparse.SUPPRESS)  # progress for the dashboard
    x.add_argument("--project-only", action="store_true", help=argparse.SUPPRESS)
    x = a.add_parser("remove", parents=[common], help="turn an add-on off in this workspace")
    x.add_argument("name")
    x.add_argument("--purge", action="store_true", help="also delete its data folder and settings")
    x = a.add_parser("uninstall", parents=[common], help="uninstall an add-on")
    x.add_argument("name")
    a.add_parser("list", parents=[common], help="the add-ons and whether each is on here")


def _add_one(args, root: Path, name: str) -> None:
    if not args.project_only and (addons._is_path(name) or name not in addons.CORE_ADDONS):
        addons.tool_env_change_ok()  # first, before any snapshot or hand-off: a click cannot fix this
    if addons._is_path(name) and not addons._local_add_ok():
        # code from a folder runs inside orch itself
        # Snapshot the folder NOW (request time): the card shows the path and a short content hash, the
        # proof's target is the full hash. The proven add installs from the snapshot with that hash and is
        # refused when the folder changed since (a content swap before the click).
        info = addons.prepare_local_add(root, Path(name))
        with addons.trusted_local_add(info["hash"]):
            addons.add(root, name, args.yes, args.project_only)
    else:
        addons.add(root, name, args.yes, args.project_only)


def _add_many(args, root: Path, names: list[str]) -> None:
    """Several built-in add-ons: ONE reinstall and ONE restart; what this run turned on is turned off again
    when it fails."""
    if args.project_only or any(addons._is_path(n) for n in names):
        raise Refused("Add an add-on from a folder on its own.")
    with addons.batch_install(root, names):
        for n in names:
            addons.add(root, n, args.yes)


def _add(args, root: Path) -> None:
    names = list(dict.fromkeys(args.names))
    if args.job:
        addonjob.attach(root, names)
    try:
        if len(names) == 1:
            _add_one(args, root, names[0])
        else:
            _add_many(args, root, names)
    except BaseException as e:
        if args.job:
            addonjob.fail(e)
        raise
    else:
        if args.job:
            addonjob.finish()
    finally:
        if args.job:
            addonjob.detach()
    if args.project_only:
        _out(args, {"ok": True}, f"{names[0]} is turned on in this workspace.")
    if not args.json:
        from orch import harness

        if (w := harness.git_visible_warning(root)) is not None:
            print(w)


def dispatch(args, root: Path) -> bool:
    if args.cmd != "addon":
        return False
    sub = getattr(args, "sub", None)
    if sub == "list":
        rows = addons.listing(root)
        have = [r for r in rows if r["installed"]]
        avail = [r for r in rows if not r["installed"]]
        w = addons.name_width(r["name"] for r in rows)
        text = "\n".join(
            f"  {r['name']:<{w}}{'on' if r['active'] else 'off':<6}{r['description']}" for r in have
        )
        text = text or "No add-ons are installed. Turn one on with: orch addon add <name>"
        if avail:
            text += "\n\nAvailable (not installed yet; add one with: orch addon add <name>)\n" + "\n".join(
                f"  {r['name']:<{w}}{r['description']}" for r in avail
            )
        _out(args, rows, text)
    elif sub == "add":
        _add(args, root)
    elif sub == "remove":
        if args.name not in addons.listed(root) and addons.installed_here(args.name):
            # off here but still installed on this computer (e.g. an add-on orch no longer ships): the person
            # wants it gone, so uninstall it instead of refusing (ORCH-1369)
            addons.tool_env_change_ok()
            addons.uninstall(root, args.name)
            _out(args, {"ok": True, "uninstalled": True}, f"{args.name} is uninstalled.")
            return True
        addons.remove(root, args.name, args.purge)
        _out(args, {"ok": True}, f"{args.name} is turned off in this workspace.")
    else:
        addons.tool_env_change_ok()
        addons.uninstall(root, args.name)
        _out(args, {"ok": True}, f"{args.name} is uninstalled.")
    return True
