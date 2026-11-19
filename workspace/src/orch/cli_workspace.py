"""`orch workspace move-here`: keep a moved workspace's saved keys and settings (ORCH-853). Person only."""

from __future__ import annotations

import json
from pathlib import Path

from orch import history, nextstep


def add_parsers(sub, common) -> None:
    w = sub.add_parser("workspace", help="this workspace folder")
    wsub = w.add_subparsers(dest="workspace_cmd", metavar="<command>", required=True)
    wsub.add_parser(
        "move-here",
        parents=[common],
        help="after you moved this folder: keep its saved keys and settings here (asks you first)",
    )


def _text(res: dict) -> str:
    if not res["moved"]:
        return "Nothing to move: the saved keys already belong to this folder."
    return f"Moved the saved keys and settings from {res['old']} to {res['new']}."


def dispatch(args, root: Path) -> bool:
    if args.cmd != "workspace":
        return False
    from orch import workspace_move

    if args.workspace_cmd == "move-here":
        res = workspace_move.move_here(root, by=getattr(args, "by", None))
        data = {"ok": True, **res}
        if args.json:
            data = history.shown_json(history.args_root(args), data)
        nextstep.remember(args, data)
        print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else _text(res))
    return True
