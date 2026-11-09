"""Reserved record commands; no workspace access."""

import argparse
from pathlib import Path

from orch.errors import Refused

SUBCOMMANDS = ("tail", "query", "counts", "delete-detail")


def add_parsers(sub, common) -> None:
    r = sub.add_parser("record", parents=[common], help=argparse.SUPPRESS).add_subparsers(dest="sub")
    for name in SUBCOMMANDS:
        r.add_parser(name, parents=[common], help=argparse.SUPPRESS).add_argument("rest", nargs="*")


def dispatch(args, root: Path) -> bool:
    if args.cmd != "record":
        return False
    raise Refused(f"`orch record {args.sub}` is not built yet.")
