"""`orch focus`: serve, start, stop, status, open."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import webbrowser
from pathlib import Path

from . import service
from .server import DEFAULT_PORT, TID_RE, make_server, stop_started


def find_workspace(start: Path) -> Path | None:
    p = start.resolve()
    for d in (p, *p.parents):
        if (d / ".orch").is_dir():
            return d
    return None


def _orch_bin() -> str | None:
    """This Python's own orch (`-I -m orch`), never ORCH_BIN or PATH (H1). Without an importable orch the old
    ORCH_BIN is all there is, and there is no key to protect either."""
    import importlib.util
    import os

    from .actions import SELF

    return SELF if importlib.util.find_spec("orch") else os.environ.get("ORCH_BIN") or None


def _launch(root: Path, page: str) -> str:
    """The page address with a one-time launch token in the fragment (a person opens it: H1)."""
    try:
        from orch import humanproof

        return humanproof.launch_url(root, "focus", page)
    except ImportError:
        return page


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="orch focus", description="A live page for one ticket.")
    ap.add_argument(
        "--dir", default=".", help="workspace folder (default: current, searched upwards for .orch/)"
    )
    sub = ap.add_subparsers(dest="cmd")
    sv = sub.add_parser("serve", help="serve on 127.0.0.1 (used by start)")
    sv.add_argument("--port", type=int, default=DEFAULT_PORT)
    sv.add_argument("--auto-port", action="store_true", help=argparse.SUPPRESS)
    sv.add_argument("--ready-file", help=argparse.SUPPRESS)
    for name, text in (("start", "serve in the background"), ("stop", "stop the background page"),
                       ("status", "is it running, and where?")):  # fmt: skip
        sub.add_parser(name, help=text).add_argument("--json", action="store_true")
    for name, text in (("view", "dashboard tab data (always JSON)"), ("needs", "rows for `orch needs`")):
        sub.add_parser(name, help=text).add_argument("--json", action="store_true")
    op = sub.add_parser("open", help="open the live page of a ticket")
    op.add_argument("ticket")
    op.add_argument("--no-open", action="store_true", help="only print the address")
    op.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = find_workspace(Path(args.dir))
    if root is None:
        print("No orch workspace here (no .orch/ folder). Run `orch init` first.", file=sys.stderr)
        return 2
    if args.cmd in (None, "serve"):
        return _serve(args, root)
    if args.cmd in ("view", "needs"):
        return _data(args, root)
    return _service(args, root)


def _data(args, root: Path) -> int:
    import os

    orch_bin = os.environ.get("ORCH_BIN") or "orch"
    if args.cmd == "view":
        from .view import build

        print(json.dumps(build(root, orch_bin)))
        return 0
    from .needs import rows

    rs = rows(root, orch_bin)
    print(
        json.dumps(rs)
        if args.json
        else "\n".join(f"{r['title']}: {r['text']}" for r in rs) or "Nothing needs you here."
    )
    return 0


def _serve(args, root: Path) -> int:
    port = getattr(args, "port", DEFAULT_PORT)
    try:
        srv = make_server(root, port, orch_bin=_orch_bin())
    except OSError:
        if not getattr(args, "auto_port", False):
            raise
        srv = make_server(root, 0, orch_bin=_orch_bin())
    if getattr(args, "ready_file", None):
        service.write_ready(Path(args.ready_file), srv.server_address[1])
    print(f"orch focus for {root.name}: http://127.0.0.1:{srv.server_address[1]}  (Ctrl+C to stop)")

    def term(*_):
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGTERM, term)
    except (ValueError, OSError):
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_started(srv)
    return 0


def _by_key(root: Path, ref: str) -> str:
    """A ticket key (DM1-12, any case) gives that ticket's id; anything else is returned as it is."""
    want = ref.strip().upper()
    for p in sorted((root / ".orch" / "tickets").glob("t_*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(t, dict)
            and t.get("general") is not True
            and str(t.get("key") or "").upper() == want
            and TID_RE.fullmatch(str(t.get("id")))
        ):
            return t["id"]
    return ref


def _service(args, root: Path) -> int:
    def out(data: dict, text: str, as_json: bool) -> None:
        print(json.dumps(data) if as_json else text)

    as_json = bool(getattr(args, "json", False))
    if args.cmd in ("start", "open"):
        try:
            cur = service.start(root)
        except RuntimeError as e:
            print(
                json.dumps({"error": str(e)}) if as_json else f"Refused: {e}",
                file=None if as_json else sys.stderr,
            )
            return 2
        u = service.url(cur["port"])
        if args.cmd == "open":
            args.ticket = _by_key(root, args.ticket)
            if not TID_RE.fullmatch(args.ticket):
                print("Give a ticket id like t_ab12cd or its key like DM1-12.", file=sys.stderr)
                return 2
            page = f"{u}/t/{args.ticket}"
            out({"running": True, "pid": cur["pid"], "url": page}, page, as_json)
            if not args.no_open:
                webbrowser.open(_launch(root, page))
        else:
            out(
                {"running": True, "pid": cur["pid"], "url": u},
                f"Focus: {u}  (stop: orch focus stop)",
                as_json,
            )
    elif args.cmd == "stop":
        try:
            res = service.stop(root)
        except RuntimeError as e:
            res = "not verified: " + str(e)
        if res == "stopped":
            out({"stopped": True}, "Focus stopped.", as_json)
        elif res == "not running":
            out({"stopped": False}, "Focus was not running.", as_json)
        else:
            note = (
                "A file in .orch/run/focus/ names a process that is not Focus; nothing was stopped."
                if res == "not verified"
                else res
            )
            out({"stopped": False, "note": note}, note, as_json)
    else:
        try:
            cur = service.running(root)
        except RuntimeError:
            cur = None
        data = {"running": bool(cur), **({"pid": cur["pid"], "url": service.url(cur["port"])} if cur else {})}
        out(data, f"Focus running: {data['url']}" if cur else "Focus is not running.", as_json)
        return 0 if cur else 1
    return 0
