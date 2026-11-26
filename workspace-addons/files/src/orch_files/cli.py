"""`orch files`: search every file in the workspace by name or by what is written in it, and run the Files page."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import webbrowser
from pathlib import Path

from . import index, service
from .server import DEFAULT_PORT, make_server

SEARCH_TEXT_SECONDS = 3.0  # a search from the command line reads at most this long of not-yet-read text first


def find_workspace(start: Path) -> Path | None:
    path = start.resolve()
    return next((p for p in (path, *path.parents) if (p / ".orch").is_dir()), None)


def _serve(args, root: Path) -> int:
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
    print(f"Files: {service.url(server.server_address[1])}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.indexer.stop.set()
        server.server_close()
    return 0


def _manage(args, root: Path) -> int:
    if args.cmd in ("start", "open"):
        cur = service.start(root)
        url = service.url(cur["port"])
        data, message = {"running": True, "pid": cur["pid"], "url": url}, url
        if args.cmd == "open" and not args.no_open:
            webbrowser.open(url)
    elif args.cmd == "stop":
        result = service.stop(root)
        data, message = {"stopped": result == "stopped", "note": result}, f"Files: {result}."
    else:
        cur = service.running(root)
        data = {"running": bool(cur)}
        if cur:
            data.update(pid=cur["pid"], url=service.url(cur["port"]))
        message = f"Files: {data['url']}" if cur else "Files is not running."
    print(json.dumps(data) if args.json else message)
    if not args.json:
        if data.get("url"):
            print(f"Next: browse the files at {data['url']}")
        else:
            print("Next: open Files with orch files open")
    return 1 if args.cmd == "status" and not data["running"] else 0


def _when(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _search(args, root: Path) -> int:
    words = " ".join(args.words).strip()
    if not words:
        print('Say what to look for: orch files search "<words>"', file=sys.stderr)
        return 2
    if not args.no_refresh:
        index.refresh(root, text_seconds=SEARCH_TEXT_SECONDS)
    res = index.search(root, words, args.limit)
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
        return 0
    if not res["items"]:
        print(f'Nothing found for "{words}".')
    for it in res["items"]:
        where = f"  (ticket {it['ticket']})" if it["ticket"] else ""
        print(f"{it['path']}{where}  ·  {it['word']}  ·  {_when(it['changed'])}")
        if it.get("line"):
            print(f"    {it['line']}")
    tail = f"{len(res['items'])} found among {res['total']:,} files in {res['ms']} ms"
    if res["unread"]:
        tail += f"; the text of {res['unread']:,} files is still being read"
    print(tail + ".")
    if res["items"]:
        print("Next: open a matching file in the workspace.")
    elif res["unread"]:
        print("Next: finish reading the files with orch files index, then search again.")
    else:
        print('Next: try another word with orch files search "<word>".')
    return 0


def _index(args, root: Path) -> int:
    pr = index.refresh(root)
    st = index.status(root)
    data = {**pr.as_dict(), "index_bytes": index.size_on_disk(root), "ready": st["ready"]}
    if args.json:
        print(json.dumps(data))
    else:
        print(
            f"{pr.total:,} files; {pr.changed:,} new or changed, {pr.removed:,} gone, "
            f"text read of {pr.read:,}, in {pr.seconds} s."
        )
        print('Next: find a file with orch files search "<word>".')
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="orch files", description="Every file in this workspace, found fast."
    )
    parser.add_argument("--dir", default=os.environ.get("ORCH_ROOT") or ".")
    commands = parser.add_subparsers(dest="cmd")
    s = commands.add_parser("search", help="find files by name or by what is written in them")
    s.add_argument("words", nargs="+")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument(
        "--no-refresh", action="store_true", help="use the index as it is (no check for changed files)"
    )
    s.add_argument("--json", action="store_true")
    i = commands.add_parser("index", help="bring the search index up to date now (all text)")
    i.add_argument("--json", action="store_true")
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--auto-port", action="store_true", help=argparse.SUPPRESS)
    serve.add_argument("--ready-file", help=argparse.SUPPRESS)
    for name in ("start", "stop", "status", "open"):
        c = commands.add_parser(name)
        c.add_argument("--json", action="store_true")
        if name == "open":
            c.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)
    root = find_workspace(Path(args.dir))
    if root is None:
        print("No orch workspace here (no .orch/ folder). Run `orch init` first.", file=sys.stderr)
        return 2
    if args.cmd is None:
        parser.print_help()
        return 0
    if args.cmd in ("search", "index") and not index.has_fts5():
        msg = "Files cannot search with this Python (SQLite FTS5 is missing); search in your file manager instead."
        print(json.dumps({"error": msg}) if getattr(args, "json", False) else msg, file=sys.stdout)
        return 2
    try:
        if args.cmd == "search":
            return _search(args, root)
        if args.cmd == "index":
            return _index(args, root)
        return _serve(args, root) if args.cmd == "serve" else _manage(args, root)
    except (RuntimeError, OSError) as error:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(error)}))
        else:
            print(str(error), file=sys.stderr)
        return 2
