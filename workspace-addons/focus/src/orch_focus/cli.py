"""`orch focus`: open (Focus for one ticket, in the dashboard) and needs (rows for `orch needs`)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TID_RE = re.compile(r"t_[a-z0-9]{6,16}")
KEY_RE = re.compile(r"[A-Za-z0-9]{2,4}-[1-9][0-9]{0,8}")  # the shape of a core ticket key (DM1-12, any case)


def find_workspace(start: Path) -> Path | None:
    p = start.resolve()
    for d in (p, *p.parents):
        if (d / ".orch").is_dir():
            return d
    return None


def _ticket_id(root: Path, ref: str) -> tuple[str | None, str | None]:
    """(the ticket id, None) for a ticket id or key (DM1-12, any case) of this workspace; else (None, why).
    Only a well-formed reference with no ticket file is "no such ticket"; a file that is there but cannot be read
    is never called missing. The why names nothing but the checked reference (no path, no exception text)."""
    from orch import tickets
    from orch.errors import Refused

    ref = ref.strip()
    if TID_RE.fullmatch(ref):
        name = ref
    elif KEY_RE.fullmatch(ref):
        name = ref.upper()
    else:
        return None, "Give a ticket id like t_ab12cd or its key like DM1-12."
    missing = f"There is no ticket {name} in this workspace. Run `orch ticket list` to see your tickets."
    unread = (
        f"Ticket {name} could not be read, so Focus can't open it. Run `orch ticket show {name}` to see why."
    )
    try:
        tid = tickets.resolve(root, ref)  # a key the index doesn't know: Refused, it is not here
    except Refused:
        return None, missing
    except (OSError, ValueError, KeyError, TypeError):
        return None, unread
    try:
        tickets.ticket_path(root, tid).stat()
    except FileNotFoundError:
        return None, missing
    except (Refused, OSError, ValueError):
        return None, unread
    try:
        found = tickets.load(root, tid).get("id")
    except (Refused, OSError, ValueError, KeyError, AttributeError):
        return None, unread
    return (found, None) if found == tid and TID_RE.fullmatch(str(found)) else (None, unread)


def _dashboard_url(root: Path) -> tuple[str | None, str | None]:
    """The address of this workspace's dashboard (started when it is on but not running), or why there is none."""
    from orch import addons, services

    if "dashboard" not in addons.active_manifests(root):
        return None, "Focus shows in the dashboard, which is off here. Turn it on: orch addon add dashboard"
    key = str(root.resolve())

    def find():
        return next(
            (services.local_url(e.get("url")) for e in services.running()
             if e["workspace"] == key and e["addon"] == "dashboard" and services.local_url(e.get("url"))),
            None,
        )  # fmt: skip

    url = find()
    if url is None:
        row = next(iter(services.start(root, only={"dashboard"})), {})
        url = services.local_url(row.get("url")) or find()
        if url is None:
            return None, "The dashboard did not start" + (
                f": {row['error']}" if row.get("error") else ". Run orch start."
            )
    return url.rstrip("/"), None


def _open(args, root: Path) -> int:
    def refuse(text: str) -> int:
        print(
            json.dumps({"error": text}) if args.json else f"Refused: {text}",
            file=None if args.json else sys.stderr,
        )
        return 2

    tid, why = _ticket_id(root, args.ticket)
    if tid is None:
        return refuse(why)
    base, why = _dashboard_url(root)
    if base is None:
        return refuse(why)
    page = f"{base}/#addon/focus/t/{tid}"
    print(json.dumps({"url": page}) if args.json else page)
    if not args.no_open and not args.json:
        from orch import pagelaunch, term

        if term.is_terminal(sys.stdout):  # a person opens it: the one-time sign-in token rides along (H1)
            pagelaunch.open_browser(pagelaunch.launch_url(root, "dashboard", page))
    return 0


def _needs(args, root: Path) -> int:
    from .needs import rows

    rs = rows(root)
    print(
        json.dumps(rs)
        if args.json
        else "\n".join(f"{r['title']}: {r['text']}" for r in rs) or "Nothing needs you here."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="orch focus", description="Focus: the live page of every helper session."
    )
    ap.add_argument(
        "--dir", default=".", help="workspace folder (default: current, searched upwards for .orch/)"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    op = sub.add_parser("open", help="open Focus on one ticket's session (in the dashboard)")
    op.add_argument("ticket")
    op.add_argument("--no-open", action="store_true", help="only print the address")
    op.add_argument("--json", action="store_true")
    sub.add_parser("needs", help="rows for `orch needs`").add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = find_workspace(Path(args.dir))
    if root is None:
        print("No orch workspace here (no .orch/ folder). Run `orch init` first.", file=sys.stderr)
        return 2
    return _open(args, root) if args.cmd == "open" else _needs(args, root)
