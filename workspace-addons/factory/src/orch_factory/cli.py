"""Factory CLI: one JSON result, or a plain refusal with exit 2."""

import argparse
import json
import os
import signal
import sys
from pathlib import Path

from . import autopilot, commands, flow, server, service, watch
from .store import Refused, field_list, read_bytes, schema_of
from .view import view as render_view


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message, "invalid")


def _url(root):
    url = service.page_url(root)
    return {"url": url} if url else {}


def background(args, root):
    """start | stop | status of the watcher; watch = the loop itself (or one pass with --once)."""
    if args.cmd == "watch":
        if args.once:
            print(json.dumps({"woken": watch.once(root)}))
            return 0
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        print(f"orch factory watcher for {root.name} started", flush=True)
        page = None
        try:
            page = server.make_server(root)
            server.serve_in_thread(page)
        except OSError as error:  # no page, but the watcher still does its work
            print(f"page server not started: {error}", file=sys.stderr, flush=True)
        try:
            nonce = service.announce(root, page.server_address[1] if page else None)
        except RuntimeError as error:
            if page:
                page.server_close()
            raise Refused(str(error), "not_available") from None
        try:
            watch.loop(root)
        except KeyboardInterrupt:
            pass
        finally:
            service.forget(root, nonce)
        return 0
    try:
        if args.cmd == "start":
            pid = service.start(root)
            print(json.dumps({"running": True, "pid": pid, **_url(root)}))
        elif args.cmd == "stop":
            res = service.stop(root)
            out = {"stopped": res == "stopped"}
            if res == "not verified":
                out["note"] = (
                    "A file in .orch/run/factory/ names a process that is not the Factory watcher; "
                    "nothing was stopped."
                )
            print(json.dumps(out))
        else:
            pid = service.running_pid(root)
            print(json.dumps({"running": bool(pid), **({"pid": pid, **_url(root)} if pid else {})}))
            return 0 if pid else 1
    except RuntimeError as error:
        raise Refused(str(error), "not_available") from None
    return 0


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
        kinds = {"propose": "proposal", "autopilot": "autopilot", "change": "change", "stop": "stop"}

        def epilog(command):
            return f"{field_list(kinds[command])} Full contract: orch factory schema {kinds[command]}"

        def contract(command):
            return {"epilog": epilog(command), "formatter_class": argparse.RawDescriptionHelpFormatter}

        p = sub.add_parser("draft", parents=[common])
        p.add_argument("order")
        p.add_argument("--file", required=True)
        for command in ("propose", "autopilot", "change"):
            p = sub.add_parser(command, parents=[common], **contract(command))
            p.add_argument("order")
            p.add_argument("--file", required=True)
        p = sub.add_parser("schema", parents=[common])
        p.add_argument("what", nargs="?", default="proposal")
        # an order's stop stage, or (no order) the watcher
        p = sub.add_parser("stop", parents=[common], **contract("stop"))
        p.add_argument("order", nargs="?")
        p.add_argument("--file")
        sub.add_parser("start", parents=[common])
        sub.add_parser("status", parents=[common])
        p = sub.add_parser("watch", parents=[common])
        p.add_argument("--once", action="store_true")
        p = sub.add_parser("show", parents=[common])
        p.add_argument("order")
        for command in ("next", "ship"):
            p = sub.add_parser(command, parents=[common])
            p.add_argument("order")
        p = sub.add_parser("crew", parents=[common])
        crew = p.add_subparsers(dest="crew_cmd", required=True)
        for command in ("add", "start"):
            p = crew.add_parser(command, parents=[common])
            p.add_argument("order")
            p.add_argument("task")
        p = sub.add_parser("tiny", parents=[common])
        p.add_argument("order")
        p.add_argument("--minutes", type=int, required=True)
        p.add_argument("--what", required=True)
        p = sub.add_parser("decide", parents=[common])
        p.add_argument("order")
        p.add_argument("question")
        p.add_argument("--answer", required=True)
        p.add_argument("--why", required=True)
        for command in ("list", "view", "needs", "reconcile"):
            sub.add_parser(command, parents=[common])
        args = parser.parse_args(argv)
        if args.cmd == "schema":
            print(json.dumps(schema_of(args.what)))
            return 0
        root = Path(args.dir).absolute()
        root = next((p for p in (root, *root.parents) if (p / ".orch").is_dir()), None)
        if root is None:
            raise Refused("No orch workspace here. Run orch init first.", "not_found")
        if args.cmd == "stop":
            if args.order is None:  # no order: stop the watcher
                return background(args, root)
            if not args.file:  # an order: its stop stage, which needs the file
                raise Refused("A stop needs --file.", "invalid")
        elif args.cmd in ("start", "status", "watch"):
            return background(args, root)
        if args.cmd in ("idea", "draft", "propose", "autopilot", "change", "stop"):
            data = (
                sys.stdin.buffer.read()
                if args.file == "-"
                else read_bytes(Path(args.file))
                if args.file
                else b""
            )
            target = args.title if args.cmd == "idea" else args.order
            fn = {
                "idea": commands.idea,
                "draft": commands.draft,
                "propose": commands.propose,
                "autopilot": autopilot.propose,
                "change": flow.change,
                "stop": flow.stop,
            }[args.cmd]
            result = fn(root, target, data)
        elif args.cmd in ("next", "ship"):
            result = {"next": flow.next_step, "ship": flow.ship}[args.cmd](root, args.order)
        elif args.cmd == "crew":
            result = {"add": flow.crew_add, "start": flow.crew_start}[args.crew_cmd](
                root, args.order, args.task
            )
        elif args.cmd == "tiny":
            result = flow.tiny(root, args.order, args.minutes, args.what)
        elif args.cmd == "decide":
            result = autopilot.decide(root, args.order, args.question, args.answer, args.why)
        elif args.cmd == "reconcile":
            result = flow.reconcile(root)
        elif args.cmd == "show":
            result = commands.show(root, args.order)
        elif args.cmd == "list":
            result = commands.listing(root)
        elif args.cmd == "view":
            result = render_view(root)
        else:  # needs: Factory's questions are shown by the dashboard view; nothing extra to list
            result = []
        print(json.dumps(result))
        return 0
    except (Refused, OSError) as error:
        message = " ".join(str(error).split())
        print(f"Refused: {message}", file=sys.stderr)
        if "--json" in argv:
            print(json.dumps({"error": message, "code": getattr(error, "code", "not_available")}))
        return 2
