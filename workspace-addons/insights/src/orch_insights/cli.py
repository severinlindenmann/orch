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


def main(argv=None):
    parser = argparse.ArgumentParser(prog="orch insights", description="What your helpers used.")
    parser.add_argument("--dir", default=".")
    commands = parser.add_subparsers(dest="cmd")
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--auto-port", action="store_true", help=argparse.SUPPRESS)
    serve.add_argument("--ready-file", help=argparse.SUPPRESS)
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
    try:
        return _serve(args, root) if args.cmd == "serve" else _manage(args, root)
    except (RuntimeError, OSError) as error:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(error)}))
        else:
            print(str(error), file=sys.stderr)
        return 2
