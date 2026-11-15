"""Serve, open, and manage the workspace's background Insights page."""

import argparse
import json
import signal
import sys
import webbrowser
from pathlib import Path

from . import service
from .server import DEFAULT_PORT, make_server


def find_workspace(start):
    path = start.resolve()
    return next((p for p in (path, *path.parents) if (p / ".orch").is_dir()), None)


def _serve(args, root):
    try:
        server = make_server(root, args.port)
    except OSError:
        if not args.auto_port:
            raise
        server = make_server(root, 0)
    if args.ready_file:
        service.write_ready(Path(args.ready_file), server.server_address[1])

    def term(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, term)
    print(f"Insights: {service.url(server.server_address[1])}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _manage(args, root):
    if args.cmd in ("start", "open"):
        current = service.start(root)
        url = service.url(current["port"])
        data = {"running": True, "pid": current["pid"], "url": url}
        message = url
        if args.cmd == "open" and not args.no_open:
            webbrowser.open(url)
    elif args.cmd == "stop":
        result = service.stop(root)
        data, message = {"stopped": result == "stopped", "note": result}, f"Insights: {result}."
    else:
        current = service.running(root)
        data = {"running": bool(current)}
        if current:
            data.update(pid=current["pid"], url=service.url(current["port"]))
        message = f"Insights: {data['url']}" if current else "Insights is not running."
    print(json.dumps(data) if args.json else message)
    return 1 if args.cmd == "status" and not data["running"] else 0


def _needs(args, root):
    from .needs import from_env

    try:
        rows = from_env(root)
    except Exception:  # noqa: BLE001 - a failing check-up read is "nothing to show", never an error
        rows = []
    print(
        json.dumps(rows)
        if args.json
        else "\n".join(f"{r['title']}: {r['text']}" for r in rows) or "Nothing needs you here."
    )
    return 0


def _checkup(args, root):
    """`orch insights checkup <verb>` and `orch insights propose`: the same code the dashboard calls (via this CLI)."""
    from . import checkup_core as cc

    try:
        if args.cmd == "propose":
            draft = json.loads(args.draft if args.draft is not None else sys.stdin.read(1_000_000))
            res = cc.propose(root, draft)
        else:
            verb = args.verb
            res = {
                "start": lambda: cc.start(root),
                "list": lambda: cc.listing(root),
                "show": lambda: cc.show(root, args.id),
                "test": lambda: cc.run_test(root, args.id),
                "accept": lambda: cc.accept(root, args.id),
                "rollback": lambda: cc.rollback(root, args.id),
                "reject": lambda: cc.reject(root, args.id),
                "weekly": lambda: cc.weekly(root, args.state == "on"),
            }[verb]()
    except ValueError:
        res = None
        error = cc.CheckupError("The proposal is not valid JSON.", "invalid")
    except cc.CheckupError as e:
        res, error = None, e
    if res is None:
        print(json.dumps({"error": str(error), "code": error.code}) if args.json else f"Refused: {error}")
        return 2
    print(
        json.dumps(res, ensure_ascii=False, separators=(",", ":")) if args.json else json.dumps(res, indent=2)
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="orch insights", description="What your helpers used.")
    parser.add_argument("--dir", default=".")
    commands = parser.add_subparsers(dest="cmd")
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--auto-port", action="store_true", help=argparse.SUPPRESS)
    serve.add_argument("--ready-file", help=argparse.SUPPRESS)
    check = commands.add_parser("checkup", help="the weekly check-up").add_subparsers(
        dest="verb", required=True
    )
    for verb in ("start", "list"):
        check.add_parser(verb).add_argument("--json", action="store_true")
    for verb in ("show", "test", "accept", "rollback", "reject"):
        c = check.add_parser(verb)
        c.add_argument("id")
        c.add_argument("--json", action="store_true")
    w = check.add_parser("weekly")
    w.add_argument("state", choices=("on", "off"))
    w.add_argument("--json", action="store_true")
    pr = commands.add_parser("propose", help="a check-up run sends one proposal (JSON)")
    pr.add_argument("--draft")
    pr.add_argument("--json", action="store_true")
    needs = commands.add_parser("needs", help="rows for `orch needs`")
    needs.add_argument("--json", action="store_true")
    for name in ("start", "stop", "status", "open"):
        command = commands.add_parser(name)
        command.add_argument("--json", action="store_true")
        if name == "open":
            command.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)
    root = find_workspace(Path(args.dir))
    if root is None:
        print("No orch workspace here (no .orch/ folder). Run `orch init` first.", file=sys.stderr)
        return 2
    if args.cmd is None:
        args = parser.parse_args(["--dir", str(root), "serve"])
    if args.cmd in ("checkup", "propose"):
        return _checkup(args, root)
    if args.cmd == "needs":
        return _needs(args, root)
    try:
        return _serve(args, root) if args.cmd == "serve" else _manage(args, root)
    except (RuntimeError, OSError) as error:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(error)}))
        else:
            print(str(error), file=sys.stderr)
        return 2
