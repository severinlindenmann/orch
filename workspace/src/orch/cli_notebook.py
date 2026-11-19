"""`orch notebook ...`: the small orch app on the person's notebook (notebook_app.py). Needs no workspace
folder and is
not in `orch --help`: the person types only the line the relay admin page shows (Notebooks)."""

from __future__ import annotations

import argparse
import json
import sys

from orch import notebook_app as app
from orch.errors import Refused


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orch notebook", description="The small orch app on your notebook.")
    sub = p.add_subparsers(dest="cmd", required=True)
    x = sub.add_parser("connect", help="connect this notebook (the line from the relay admin page)")
    x.add_argument("url")
    x.add_argument("code")
    x.add_argument("--no-start", action="store_true", help="do not start it in the background")
    sub.add_parser("start", help="run in the background (starts again at login)")
    sub.add_parser("stop", help="stop the background app; requests wait in the relay")
    x = sub.add_parser("run", help="run in this terminal (Ctrl-C stops)")
    x.add_argument("--service", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("check", help="run the self-check of every way in now")
    sub.add_parser("status", help="connected, running, ways in and their last self-check")
    for x in sub.choices.values():
        x.add_argument("--json", action="store_true")
    return p


def _say(args, data, text: str) -> None:
    print(json.dumps(data, ensure_ascii=False) if args.json else text)


def _ways_lines(rows) -> list[str]:
    return [
        f"{r.get('name', r.get('way'))}: {'works' if r.get('ok') else 'stopped working'}"
        + (f" ({r['problem']})" if r.get("problem") else "")
        for r in rows
    ]


def main(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.cmd == "connect":
            c = app.connect(args.url, args.code)
            text = f"Connected for {c['workspace'] or 'your workspace'}."
            if not args.no_start:
                try:
                    text += "\n" + app.start()
                except Refused as e:
                    text += f"\n{e}"
            text += f"\nPut your ways in into {app.home() / 'ways'} (one folder each, with a way.toml)."
            _say(args, c, text)
        elif args.cmd == "start":
            _say(args, {"running": True}, app.start())
        elif args.cmd == "stop":
            _say(args, {"running": False}, app.stop())
        elif args.cmd == "run":
            if not args.service and app.service_running():
                raise Refused(
                    "The notebook app already runs in the background. Stop it first: orch notebook stop"
                )
            app.connection()
            if not args.json:
                print("The notebook app waits for requests. Ctrl-C stops it.", flush=True)
            try:
                app.run()
            except KeyboardInterrupt:
                pass
        elif args.cmd == "check":
            rows = app.self_check()
            try:
                app.send_status(app.connection(), app.home(), rows)
            except Refused:
                pass
            _say(args, rows, "\n".join(_ways_lines(rows)))
        elif args.cmd == "status":
            st = app.status()
            lines = [
                f"Connected for {st.get('workspace') or 'your workspace'}."
                if st["connected"]
                else "Not connected. Run the line from the relay admin page (Notebooks)."
            ]
            if st["connected"]:
                lines.append(
                    "Running in the background."
                    if st["running"]
                    else "Not running. Start it: orch notebook start"
                )
            lines += _ways_lines(st["ways"])
            _say(args, st, "\n".join(lines))
    except Refused as e:
        print(f"Refused: {e}", file=sys.stderr)
        if args.json:
            print(json.dumps({"error": str(e)}))
        return 2
    return 0
