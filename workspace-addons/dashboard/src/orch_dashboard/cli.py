"""`orch dashboard` / `orch-dashboard`: serve, snapshot."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import service
from .data import find_workspace
from .server import DEFAULT_PORT, make_server
from .snapshot import publish_snapshot, write_snapshot


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="orch dashboard", description="Read-only dashboard of the workspace tickets.")
    ap.add_argument("--dir", default=".", help="workspace folder (default: current, searched upwards for .orch/)")
    sub = ap.add_subparsers(dest="cmd")
    sv = sub.add_parser("serve", help="serve on 127.0.0.1 (default command)")
    sv.add_argument("--port", type=int, default=DEFAULT_PORT)
    sv.add_argument("--auto-port", action="store_true", help=argparse.SUPPRESS)  # 8420, else any free port
    sv.add_argument("--ready-file", help=argparse.SUPPRESS)  # background run: bound port written here after bind
    for name, text in (("start", "serve in the background"), ("stop", "stop the background dashboard"),
                       ("status", "is it running, and where?")):
        sub.add_parser(name, help=text).add_argument("--json", action="store_true")
    sn = sub.add_parser("snapshot", help="write a static read-only HTML snapshot")
    sn.add_argument("--out", default="dashboard-snapshot.html")
    sn.add_argument("--with-addons", action="store_true", help="include add-on tabs and ticket rows (left out by default)")
    sn.add_argument("--publish", action="store_true", help="publish it as a private publish app")
    args = ap.parse_args(argv)
    root = find_workspace(Path(args.dir))
    if root is None:
        print("No orch workspace here (no .orch/ folder). Run `orch init` first.", file=sys.stderr)
        return 2
    if args.cmd in ("start", "stop", "status"):
        return _service(args, root)
    if args.cmd == "snapshot":
        if args.publish:
            return publish_snapshot(root, with_addons=args.with_addons)
        print(write_snapshot(root, Path(args.out), args.with_addons))
        return 0
    port = getattr(args, "port", DEFAULT_PORT)
    try:
        srv = make_server(root, port)
    except OSError:
        if not getattr(args, "auto_port", False):
            raise
        srv = make_server(root, 0)  # another workspace has 8420
    if getattr(args, "ready_file", None):
        service.write_ready(Path(args.ready_file), srv.server_address[1])
    print(f"orch dashboard for {root.name}: http://127.0.0.1:{srv.server_address[1]}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def _service(args, root: Path) -> int:
    def out(data: dict, text: str) -> None:
        print(json.dumps(data) if args.json else text)

    if args.cmd == "start":
        try:
            cur = service.start(root)
        except RuntimeError as e:
            print(json.dumps({"error": str(e)}) if args.json else f"Refused: {e}", file=None if args.json else sys.stderr)
            return 2
        u = service.url(cur["port"])
        out({"running": True, "pid": cur["pid"], "url": u}, f"Dashboard for {root.name}: {u}  (stop: orch dashboard stop)")
    elif args.cmd == "stop":
        stopped = service.stop(root)
        out({"stopped": stopped}, "Dashboard stopped." if stopped else "The dashboard was not running.")
    else:
        cur = service.running(root)
        data = {"running": bool(cur), **({"pid": cur["pid"], "url": service.url(cur["port"])} if cur else {})}
        out(data, f"Dashboard running: {data['url']}" if cur else "The dashboard is not running.")
        return 0 if cur else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
