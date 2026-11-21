"""Factory CLI: one JSON result, or a plain refusal with exit 2."""

import argparse
import json
import os
import signal
import sys
from pathlib import Path

from . import ask, autopilot, commands, flow, server, service, watch
from .store import Refused, field_list, read_bytes, schema_of
from .view import view as render_view

HELP = {
    "propose": "propose the whole run of an order (the person presses Start)",
    "autopilot": "propose autopilot for an order",
    "change": "propose a change to a started order",
    "stop": "with an order and --file: its stop review; with no order: stop the Factory watcher",
    "start": "start the Factory watcher (takes no order: a person starts an order on its page)",
    "status": "whether the Factory watcher runs (takes no order: use show <order>)",
    "next": "what the manager of an order does next",
    "ship": "ship an order once the person said Ship it",
    "list": "every order",
    "view": "the dashboard view of all orders (takes no order: use show <order>)",
    "needs": "the stage reviews that wait for your Looks good, with the commands that answer them",
    "reconcile": "check every order's record against its tickets",
}
NO_ORDER = {
    "start": "orch factory start takes no order: it starts the Factory watcher. "
    "A person starts an order on its page in Factory.",
    "status": "orch factory status takes no order: it says whether the Factory watcher runs. "
    "For one order use orch factory show <order>.",
    "view": "orch factory view takes no order. For one order use orch factory show <order>.",
}


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


def _value(v):
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def plain(cmd, result):
    """Plain lines for a person (list, show, next); --json prints the same data as JSON."""
    if cmd == "list":
        if not result:
            return "No orders yet."
        lines = []
        for o in result:
            line = f"{o['order']}  {o.get('stage') or '-'}  {o.get('title') or ''}"
            if o.get("broken"):
                line += f"  (problem: {o['broken']})"
            elif o.get("questions"):
                line += f"  ({len(o['questions'])} open question(s))"
            lines.append(line)
        return "\n".join(lines)
    if cmd == "show":
        lines = [f"{k}: {_value(v)}" for k, v in result.items() if k != "questions"]
        for q in result.get("questions") or []:
            lines.append(f"question: {_value(q)}")
        return "\n".join(lines)
    return "\n".join(f"{k}: {_value(v)}" for k, v in result.items())


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        parser = Parser(prog="orch factory")
        parser.add_argument("--dir", default=os.environ.get("ORCH_ROOT", "."))
        common = Parser(add_help=False)
        common.add_argument("--json", action="store_true")
        sub = parser.add_subparsers(dest="cmd", required=True)
        p = sub.add_parser(
            "idea", parents=[common], help="file a new idea as an order (or --ticket: turn a ticket into one)"
        )
        p.add_argument("title", nargs="?")
        p.add_argument("--file")
        p.add_argument("--ticket", help="turn this existing ticket (e.g. one made from Chat) into the order")
        p.add_argument("--from", dest="source", help="the ticket this idea came from: both are linked")
        # what the Factory page's idea box does through the dashboard (the add-on act contract)
        p = sub.add_parser(
            "act",
            parents=[common],
            help="what a person's click on the Factory page does (the dashboard runs it)",
        )
        p.add_argument("verb", choices=("idea", "ask", "start"))
        p.add_argument("target")
        p.add_argument("--by")
        kinds = {"propose": "proposal", "autopilot": "autopilot", "change": "change", "stop": "stop"}

        def epilog(command):
            return f"{field_list(kinds[command])} Full contract: orch factory schema {kinds[command]}"

        def contract(command):
            return {"epilog": epilog(command), "formatter_class": argparse.RawDescriptionHelpFormatter}

        p = sub.add_parser(
            "ask", parents=[common], help="ask another workspace for its view at a stop of an order"
        )  # #816 A: ask another workspace for its view at a stop
        p.add_argument("order")
        p.add_argument("stop", type=int)
        p.add_argument("ws")
        p.add_argument("--item", type=int, action="append", default=[])
        p.add_argument("--no-pictures", action="store_true")
        p.add_argument("--by")
        p = sub.add_parser("draft", parents=[common], help="save a new draft of an order")
        p.add_argument("order")
        p.add_argument("--file", required=True)
        for command in ("propose", "autopilot", "change"):
            p = sub.add_parser(command, parents=[common], help=HELP[command], **contract(command))
            p.add_argument("order")
            p.add_argument("--file", required=True)
        p = sub.add_parser("schema", parents=[common], help="print the contract of a file Factory takes")
        p.add_argument("what", nargs="?", default="proposal")
        # an order's stop stage, or (no order) the watcher
        p = sub.add_parser("stop", parents=[common], help=HELP["stop"], **contract("stop"))
        p.add_argument("order", nargs="?")
        p.add_argument("--file")
        for command in ("start", "status"):
            p = sub.add_parser(command, parents=[common], help=HELP[command], description=HELP[command])
            p.add_argument("order", nargs="?", help=argparse.SUPPRESS)  # refused below in plain words
        p = sub.add_parser("watch", parents=[common], help="the watcher loop itself (--once: one pass)")
        p.add_argument("--once", action="store_true")
        p = sub.add_parser("show", parents=[common], help="an order's stage and open questions")
        p.add_argument("order")
        for command in ("next", "ship"):
            p = sub.add_parser(command, parents=[common], help=HELP[command])
            p.add_argument("order")
        p = sub.add_parser(
            "crew", parents=[common], help="add or start the crew ticket of one task of an order"
        )
        crew = p.add_subparsers(dest="crew_cmd", required=True)
        for command in ("add", "start"):
            p = crew.add_parser(command, parents=[common])
            p.add_argument("order")
            p.add_argument("task")
        p = sub.add_parser("tiny", parents=[common], help="record a tiny change made during a run")
        p.add_argument("order")
        p.add_argument("--minutes", type=int, required=True)
        p.add_argument("--what", required=True)
        p = sub.add_parser("decide", parents=[common], help="autopilot: decide a routine stop of an order")
        p.add_argument("order")
        p.add_argument("question")
        p.add_argument("--answer", required=True)
        p.add_argument("--why", required=True)
        for command in ("list", "view", "needs", "reconcile"):
            p = sub.add_parser(command, parents=[common], help=HELP[command], description=HELP[command])
            p.add_argument("order", nargs="?", help=argparse.SUPPRESS)  # refused below in plain words
        args = parser.parse_args(argv)
        if args.cmd in ("start", "status", "list", "view", "needs", "reconcile") and args.order is not None:
            raise Refused(NO_ORDER.get(args.cmd, f"orch factory {args.cmd} takes no order."), "invalid")
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
            if args.cmd == "idea":
                if bool(args.title) == bool(args.ticket):
                    raise Refused(
                        "Give a title for a new idea, or --ticket <id> to turn a ticket into one.", "invalid"
                    )
                result = commands.idea(root, args.title, data, args.ticket, args.source)
            else:
                result = fn(root, target, data)
        elif args.cmd == "act":
            fn = {"ask": ask.act, "start": commands.start_act, "idea": commands.idea_act}[args.verb]
            result = fn(root, args.target, args.by)
        elif args.cmd == "ask":
            result = ask.ask(root, args.order, args.stop, args.ws, args.item, args.by, not args.no_pictures)
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
        else:  # needs: the stage reviews waiting for your Looks good (Factory's questions are core questions)
            from . import pageapi

            result = pageapi.needs(root)
        if args.cmd in ("list", "show", "next") and not args.json:
            print(plain(args.cmd, result))
            return 0
        print(json.dumps(result))
        return 0
    except (Refused, OSError) as error:
        message = " ".join(str(error).split())
        print(f"Refused: {message}", file=sys.stderr)
        if "--json" in argv:
            print(json.dumps({"error": message, "code": getattr(error, "code", "not_available")}))
        return 2
