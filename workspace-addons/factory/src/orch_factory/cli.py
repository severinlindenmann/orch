"""Factory CLI: one JSON result, or a plain refusal with exit 2."""

import argparse
import json
import os
import sys
from pathlib import Path

from . import commands
from .store import Refused, read_bytes
from .view import view


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message, "invalid")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        parser = Parser(prog="orch factory")
        parser.add_argument("--dir", default=os.environ.get("ORCH_ROOT", "."))
        common = Parser(add_help=False)
        common.add_argument("--json", action="store_true")
        sub = parser.add_subparsers(dest="cmd", required=True)
        p = sub.add_parser("idea", parents=[common])
        p.add_argument("title")
        p.add_argument("--file")
        for command in ("draft", "propose"):
            p = sub.add_parser(command, parents=[common])
            p.add_argument("order")
            p.add_argument("--file", required=True)
        p = sub.add_parser("show", parents=[common])
        p.add_argument("order")
        for command in ("list", "view", "needs"):
            sub.add_parser(command, parents=[common])
        args = parser.parse_args(argv)
        root = Path(args.dir).absolute()
        root = next((p for p in (root, *root.parents) if (p / ".orch").is_dir()), None)
        if root is None:
            raise Refused("No orch workspace here. Run orch init first.", "not_found")
        if args.cmd in ("idea", "draft", "propose"):
            data = (
                sys.stdin.buffer.read()
                if args.file == "-"
                else read_bytes(Path(args.file))
                if args.file
                else b""
            )
            target = args.title if args.cmd == "idea" else args.order
            result = getattr(commands, args.cmd)(root, target, data)
        elif args.cmd == "show":
            result = commands.show(root, args.order)
        elif args.cmd == "list":
            result = commands.listing(root)
        elif args.cmd == "view":
            result = view(root)
        else:
            result = []
        print(json.dumps(result))
        return 0
    except (Refused, OSError) as error:
        message = " ".join(str(error).split())
        print(f"Refused: {message}", file=sys.stderr)
        if "--json" in argv:
            print(json.dumps({"error": message, "code": getattr(error, "code", "not_available")}))
        return 2
