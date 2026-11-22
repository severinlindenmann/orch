"""`orch focus`: open (Focus for one ticket, in the dashboard) and needs (rows for `orch needs`)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TID_RE = re.compile(r"t_[a-z0-9]{6,16}")


def find_workspace(start: Path) -> Path | None:
    p = start.resolve()
    for d in (p, *p.parents):
        if (d / ".orch").is_dir():
            return d
    return None


def _ticket_id(root: Path, ref: str) -> str | None:
    """A ticket id, or the id of a ticket key (DM1-12, any case); None when there is no such ticket."""
    from orch import tickets
    from orch.errors import Refused

    try:
        return tickets.load(root, tickets.resolve(root, ref.strip()))["id"]
    except (Refused, OSError, ValueError, KeyError):
        return None


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

    tid = _ticket_id(root, args.ticket)
    if tid is None or not TID_RE.fullmatch(tid):
        return refuse("Give a ticket id like t_ab12cd or its key like DM1-12.")
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
