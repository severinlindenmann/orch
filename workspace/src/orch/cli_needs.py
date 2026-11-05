"""`orch needs` and `orch agents` (hidden until built)."""

from __future__ import annotations

import argparse
from pathlib import Path

from orch.errors import Refused


def add_parsers(sub, common) -> None:
    x = sub.add_parser("needs", parents=[common], help=argparse.SUPPRESS)
    x.add_argument("rest", nargs=argparse.REMAINDER)
    x = sub.add_parser("agents", parents=[common], help=argparse.SUPPRESS)
    x.add_argument("rest", nargs=argparse.REMAINDER)


def dispatch(args, root: Path) -> bool:
    if args.cmd not in ("needs", "agents"):
        return False
    raise Refused(f"orch {args.cmd} is not available yet.")
