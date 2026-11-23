"""`orch workspace move-here`: keep a moved workspace's saved keys and settings (ORCH-853). Person only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orch import history, nextstep


def add_parsers(sub, common) -> None:
    # hidden from help like `orch copy`: a rare step a person takes after a move; every refusal names it
    w = sub.add_parser("workspace", help=argparse.SUPPRESS)
    wsub = w.add_subparsers(dest="workspace_cmd", metavar="<command>", required=True)
    wsub.add_parser(
        "move-here",
        parents=[common],
        help="after you moved this folder: keep its saved keys and settings here (asks you first)",
    )
    # orch Companion (the Mac menu bar app) asks here; JSON only, see companion_ws (ORCH-1722)
    c = wsub.add_parser("companion", parents=[common], help=argparse.SUPPRESS)
    # plain strings checked in _companion: a wrong word gets one JSON answer, not argparse's usage text
    c.add_argument("action", nargs="?", default="", help="list, start, switch or at-login")
    c.add_argument("id", nargs="?", help="the workspace id from the list (start, switch)")
    c.add_argument("state", nargs="?", help="switch: on or off")


def _text(res: dict) -> str:
    if not res["moved"]:
        return "Nothing to move: the saved keys already belong to this folder."
    text = f"Moved the saved keys and settings from {res['old']} to {res['new']}."
    if res.get("not_moved"):
        text += (
            " orch could not update its list of running background services; those started in the old folder"
            " start again the next time you open orch here."
        )
    return text


def dispatch(args, root: Path) -> bool:
    if args.cmd != "workspace":
        return False
    if args.workspace_cmd == "companion":
        print(json.dumps(_companion(args), ensure_ascii=False))
        return True
    from orch import workspace_move

    if args.workspace_cmd == "move-here":
        res = workspace_move.move_here(root, by=getattr(args, "by", None))
        data = {"ok": True, **res}
        if args.json:
            data = history.shown_json(history.args_root(args), data)
        nextstep.remember(args, data)
        print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else _text(res))
    return True


def _companion(args) -> dict:
    """Always one JSON object, also for a mistake or a failure: orch Companion shows only orch's own words."""
    from orch import companion_ws as cw

    try:
        return _companion_do(args, cw)
    except Exception:  # never a traceback or an add-on's text: a fixed line that says where to look
        return cw._err("failed")


def _companion_do(args, cw) -> dict:
    if args.action not in ("list", "start", "switch", "at-login"):
        return {"v": cw.V, "ok": False, "error": "usage", "message": "Say list, start, switch or at-login."}
    if args.action == "list":
        return cw.listing()
    if args.action == "at-login":
        return cw.at_login()
    if not args.id:
        return cw._err("unknown_workspace")
    if args.action == "start":
        return cw.start(args.id)
    if args.state not in ("on", "off"):
        return {"v": cw.V, "ok": False, "error": "usage", "message": "Say on or off."}
    return cw.switch(args.id, args.state == "on")
