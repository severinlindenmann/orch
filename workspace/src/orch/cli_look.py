"""`orch look list|show|set`: the workspace icon and colour (contracts/look.md). Agents may use all three."""

from __future__ import annotations

import json
from pathlib import Path

from orch import look, tickets
from orch.errors import Refused


def add_parsers(sub, common) -> None:
    s = sub.add_parser("look", help="the workspace icon and colour").add_subparsers(dest="sub", required=True)
    s.add_parser("list", parents=[common], help="the icons and colours to pick from")
    s.add_parser("show", parents=[common], help="what this workspace has, and who chose it")
    x = s.add_parser(
        "shared-pages",
        parents=[common],
        help="show or set: the workspace name and icon on shared file pages (publish)",
    )
    x.add_argument("value", nargs="?", choices=("on", "off"), help="on or off; leave out to show")
    x = s.add_parser("set", parents=[common], help="pick the icon and colour")
    x.add_argument(
        "--icon", metavar="ID|none", help="an icon id from 'orch look list'; none = the first letter"
    )
    x.add_argument(
        "--color", metavar="TOKEN|auto", help="a colour from 'orch look list'; auto = from the name"
    )


def _actor(args) -> str:
    """An agent in the environment counts as an agent whatever --by says."""
    who = tickets.current_actor(getattr(args, "by", None))
    return "agent:" + str(tickets.agent_tool()) if tickets.agent_tool() else who


def _out(args, data, text: str) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else text)


def _list_text() -> str:
    lines = []
    for c in look.DATA["categories"]:
        ids = [f"{i['id']} ({i['label']})" for i in look.DATA["icons"] if i["category"] == c["id"]]
        lines.append(f"{c['label']}: " + ", ".join(ids))
    lines.append("Colours: " + ", ".join(look.COLOR_IDS) + ", or auto (from the name)")
    return "\n".join(lines)


def _show_text(d: dict) -> str:
    who = {"agent": "an agent", "human": "a person"}.get(d["set_by"], "nobody")
    if d["set_by"] is None and d["icon"] is None and d["color"] is None:
        lines = ["Nobody has picked an icon or colour yet."]
    else:
        lines = [f"Icon: {d['icon'] or 'first letter'}   Colour: {d['color'] or 'auto'}   Chosen by {who}"]
    for name, s in d["services"].items():
        if "error" in s:
            lines.append(f"  {name}: {s['error']}")
        else:
            lines.append(
                f"  {name}: icon {s.get('icon') or 'none'}, colour {s.get('color') or 'auto'}"
                + (f" ({s['push']})" if s.get("push") == "not yet sent" else "")
            )
    return "\n".join(lines)


def dispatch(args, root: Path) -> bool:
    if args.cmd != "look":
        return False
    if args.sub == "list":
        _out(args, look.listing(), _list_text())
    elif args.sub == "show":
        d = look.show(root)
        _out(args, d, _show_text(d))
    elif args.sub == "shared-pages":
        if args.value is not None:
            look.set_shared_pages(root, args.value == "on", _actor(args))
        on = look.shared_pages(root)
        state = "on" if on else "off"
        _out(args, {"on": on}, f"Shared file pages show the workspace name and icon: {state}")
    else:
        if args.icon is None and args.color is None:
            raise Refused("Say what to change: --icon <id>|none or --color <token>|auto.")
        icon = look.UNSET if args.icon is None else (None if args.icon.lower() == "none" else args.icon)
        color = look.UNSET if args.color is None else (None if args.color.lower() == "auto" else args.color)
        d = look.set_look(root, icon, color, _actor(args))
        late = [s for s, ok in d["sent"].items() if not ok]
        text = f"Icon: {d['icon'] or 'first letter'}   Colour: {d['color'] or 'auto'}"
        if late:
            text += "\nSaved. " + ", ".join(late) + " gets it when it is back."
        _out(args, d, text)
    return True
