"""`orch config` (hidden until it is built)."""

from __future__ import annotations

import argparse
from pathlib import Path

from orch.errors import Refused


def add_parsers(sub, common) -> None:
    x = sub.add_parser("config", parents=[common], help=argparse.SUPPRESS)
    x.add_argument("rest", nargs=argparse.REMAINDER)


def dispatch(args, root: Path) -> bool:
    if args.cmd != "config":
        return False
    raise Refused("orch config is not available yet.")
