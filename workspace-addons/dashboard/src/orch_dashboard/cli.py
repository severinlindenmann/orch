"""`orch dashboard` / `orch-dashboard`: serve, snapshot."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .data import find_workspace
from .server import DEFAULT_PORT, make_server
from .snapshot import publish_snapshot, write_snapshot


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="orch dashboard", description="Read-only dashboard of the workspace tickets.")
    ap.add_argument("--dir", default=".", help="workspace folder (default: current, searched upwards for .orch/)")
    sub = ap.add_subparsers(dest="cmd")
    sv = sub.add_parser("serve", help="serve on 127.0.0.1 (default command)")
    sv.add_argument("--port", type=int, default=DEFAULT_PORT)
    sn = sub.add_parser("snapshot", help="write a static read-only HTML snapshot")
    sn.add_argument("--out", default="dashboard-snapshot.html")
    sn.add_argument("--with-addons", action="store_true", help="include add-on tabs and ticket rows (left out by default)")
    sn.add_argument("--publish", action="store_true", help="publish it as a private publish app")
    args = ap.parse_args(argv)
    root = find_workspace(Path(args.dir))
    if root is None:
        print("No orch workspace here (no .orch/ folder). Run `orch init` first.", file=sys.stderr)
        return 2
    if args.cmd == "snapshot":
        if args.publish:
            return publish_snapshot(root, with_addons=args.with_addons)
        print(write_snapshot(root, Path(args.out), args.with_addons))
        return 0
    port = getattr(args, "port", DEFAULT_PORT)
    srv = make_server(root, port)
    print(f"orch dashboard for {root.name}: http://127.0.0.1:{srv.server_address[1]}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
