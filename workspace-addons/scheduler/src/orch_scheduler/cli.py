"""`orch scheduler` / `orch-scheduler`: run, start, stop, status, list."""
from __future__ import annotations

import argparse
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import service
from .loop import OPEN, Scheduler, read_tickets
from .runner import load_state


def find_workspace(start: Path) -> Path | None:
    p = start.resolve()
    for d in (p, *p.parents):
        if (d / ".orch").is_dir():
            return d
    return None


def describe(root: Path) -> list[str]:
    """Next wake-ups and recurring runs, in plain words."""
    state = load_state(root)
    rows = []
    for t in read_tickets(root):
        if t["status"] not in OPEN:
            continue
        cron = ((t.get("ext") or {}).get("scheduler") or {}).get("cron")
        if t.get("wake_at"):
            rows.append((t["wake_at"], f"{t['id']}  wakes at {t['wake_at']}  {t['title']}"))
        if t.get("type") == "recurring" and cron:
            nxt = state.get(t["id"], {}).get("next_run") or "next pass"
            rows.append((nxt, f"{t['id']}  repeats ({cron} UTC), next {nxt}  {t['title']}"))
    return [r[1] for r in sorted(rows)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="orch scheduler", description="Starts agent runs: wake_at, cron, relay inbox.")
    ap.add_argument("--dir", default=".", help="workspace folder (default: current, searched upwards for .orch/)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run in the foreground")
    r.add_argument("--once", action="store_true", help="one pass, wait for the agents, then stop")
    sub.add_parser("start", help="run in the background")
    sub.add_parser("stop", help="stop the background run")
    sub.add_parser("status", help="is it running?")
    sub.add_parser("list", help="next wake-ups and recurring runs")
    args = ap.parse_args(argv)
    root = find_workspace(Path(args.dir))
    if root is None:
        print("No orch workspace here (no .orch/ folder). Run `orch init` first.", file=sys.stderr)
        return 2
    if args.cmd == "run":
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        print(f"orch scheduler for {root.name} started {datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}", flush=True)
        try:
            Scheduler(root).run_forever(once=args.once)
        except KeyboardInterrupt:
            pass
    elif args.cmd == "start":
        print(f"Scheduler running (pid {service.start(root)}).")
    elif args.cmd == "stop":
        print("Scheduler stopped." if service.stop(root) else "Scheduler was not running.")
    elif args.cmd == "status":
        pid = service.running_pid(root)
        print(f"Scheduler running (pid {pid})." if pid else "Scheduler is not running.")
        return 0 if pid else 1
    elif args.cmd == "list":
        print("\n".join(describe(root)) or "Nothing scheduled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
