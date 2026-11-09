"""Reserved conn commands; no workspace access."""

import argparse
from pathlib import Path

from orch.errors import Refused

SUBCOMMANDS = ("list", "show", "allow")


def add_parsers(sub, common) -> None:
    r = sub.add_parser("conn", parents=[common], help=argparse.SUPPRESS).add_subparsers(dest="sub")
    for name in SUBCOMMANDS:
        r.add_parser(name, parents=[common], help=argparse.SUPPRESS).add_argument("rest", nargs="*")


def dispatch(args, root: Path) -> bool:
    if args.cmd != "conn":
        return False
    raise Refused(f"`orch conn {args.sub}` is not built yet.")
