"""`orch run ...` (hidden until it is built) and the after-command hook."""

from __future__ import annotations

import argparse
from pathlib import Path

from orch.errors import Refused

SUBCOMMANDS = (
    "claim",
    "release",
    "status",
    "session",
    "argv",
    "start",
    "send",
    "attach",
    "stop",
    "event",
    "done",
)


def add_parsers(sub, common) -> None:
    r = sub.add_parser("run", help=argparse.SUPPRESS).add_subparsers(dest="sub")
    for name in SUBCOMMANDS:
        x = r.add_parser(name, parents=[common], help=argparse.SUPPRESS)
        x.add_argument("rest", nargs=argparse.REMAINDER)


def dispatch(args, root: Path) -> bool:
    if args.cmd != "run":
        return False
    raise Refused("orch run is not available yet.")


def after_command(args, root: Path, stdout_is_json: bool) -> None:
    """Runs after every command. Placeholder: W1 prints the footer here (to stderr, never stdout)."""
