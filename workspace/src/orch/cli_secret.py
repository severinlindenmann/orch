"""Reserved secret commands; no workspace access."""

import argparse
from pathlib import Path

from orch.errors import Refused

SUBCOMMANDS = ("env", "file", "exec", "list", "get")


def add_parsers(sub, common) -> None:
    r = sub.add_parser("secret", parents=[common], help=argparse.SUPPRESS).add_subparsers(dest="sub")
    for name in SUBCOMMANDS:
        r.add_parser(name, parents=[common], help=argparse.SUPPRESS).add_argument("rest", nargs="*")


def dispatch(args, root: Path) -> bool:
    if args.cmd != "secret":
        return False
    if not args.sub:
        raise Refused("`orch secret` is not built yet. Subcommands: " + ", ".join(SUBCOMMANDS) + ".")
    raise Refused(f"`orch secret {args.sub}` is not built yet.")
