"""Reserved job commands; no workspace access."""

import argparse
from pathlib import Path

from orch.errors import Refused

SUBCOMMANDS = ("start", "step", "progress", "artifact", "metric", "table", "link", "log", "end", "run")


def add_parsers(sub, common) -> None:
    r = sub.add_parser("job", parents=[common], help=argparse.SUPPRESS).add_subparsers(dest="sub")
    for name in SUBCOMMANDS:
        r.add_parser(name, parents=[common], help=argparse.SUPPRESS).add_argument("rest", nargs="*")


def dispatch(args, root: Path) -> bool:
    if args.cmd != "job":
        return False
    raise Refused(f"`orch job {args.sub}` is not built yet.")
