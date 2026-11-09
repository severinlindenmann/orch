"""Reserved run commands; no workspace access."""

import argparse
from pathlib import Path

from orch.errors import Refused

SUBCOMMANDS = ("screen", "type")


def add_parsers(sub, common) -> None:
    """Run subcommands are installed by cli_run."""


def add_run_parsers(r, common) -> None:
    for name in SUBCOMMANDS:
        r.add_parser(name, parents=[common], help=argparse.SUPPRESS).add_argument("rest", nargs="*")


def dispatch(args, root: Path) -> bool:
    if args.cmd != "run" or args.sub not in SUBCOMMANDS:
        return False
    raise Refused(f"`orch run {args.sub}` is not built yet.")
