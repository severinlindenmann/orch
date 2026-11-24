"""`orch dashboard` / `orch-dashboard`: serve, snapshot."""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys
import threading
import time
from pathlib import Path

from . import remote, service
from .actions import SELF
from .data import find_workspace
from .server import DEFAULT_PORT, make_server, warm
from .snapshot import publish_snapshot, write_snapshot


def _bind_again(root: Path, port: int, wait: float = 15.0, listen=None):
    """A fixed port that is busy right after a self-update restart: the old process is the same pid and has
    closed its listener at exec, but a short-lived client socket of the machine may hold the number (the
    port came from the OS, so a busy host can use it as a source port). It frees within moments: retry until
    `wait`, then fail with the original error."""
    end = time.monotonic() + wait
    while True:
        try:
            return make_server(root, port, orch_bin=_orch_bin(), remote=listen)
        except OSError as e:
            if e.errno != errno.EADDRINUSE or time.monotonic() >= end:
                raise
        time.sleep(0.1)


def _running_elsewhere(root: Path) -> dict | None:
    """This workspace's background dashboard when it is another process (a self-update restart is the same
    pid and must bind its own port again)."""
    try:
        rec = service._record(root)
        if not rec or rec.get("pid") == os.getpid():  # nothing recorded, or our own record: leave it alone
            return None
        cur = service.running(root)
    except (RuntimeError, OSError):
        return None
    return cur if cur and cur.get("pid") != os.getpid() else None


def _bind_fallback(root: Path, listen=None):
    """8420 is taken (another workspace): this workspace's own fallback ports first, the same on every start
    (service.fallback_ports), so the browser keeps its sign-in over a restart; any free port only when all
    of them are taken."""
    for p in service.fallback_ports(root):
        try:
            return make_server(root, p, orch_bin=_orch_bin(), remote=listen)
        except OSError:
            continue
    return make_server(root, 0, orch_bin=_orch_bin(), remote=listen)


def _orch_bin() -> str | None:
    """This Python's own orch (`-I -m orch`), never ORCH_BIN or PATH (H1). Without an importable orch (a
    stand-alone or test install) the old ORCH_BIN is all there is, and there is no key to protect either."""
    import importlib.util

    return SELF if importlib.util.find_spec("orch") else os.environ.get("ORCH_BIN") or None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="orch dashboard", description="Read-only dashboard of the workspace tickets."
    )
    ap.add_argument(
        "--dir", default=".", help="workspace folder (default: current, searched upwards for .orch/)"
    )
    sub = ap.add_subparsers(dest="cmd")
    sv = sub.add_parser("serve", help="serve on 127.0.0.1 (default command)")
    sv.add_argument("--port", type=int, default=None)  # None: 8420, and the background one is reused
    sv.add_argument("--auto-port", action="store_true", help=argparse.SUPPRESS)  # 8420, else any free port
    sv.add_argument(
        "--ready-file", help=argparse.SUPPRESS
    )  # background run: bound port written here after bind
    for name, text in (
        ("start", "serve in the background"),
        ("stop", "stop the background dashboard"),
        ("status", "is it running, and where?"),
    ):
        sub.add_parser(name, help=text).add_argument("--json", action="store_true")
    op = sub.add_parser("open", help="open the dashboard in your browser, signed in")
    op.add_argument("--print", action="store_true", help="print a one-time sign-in link instead")
    op.add_argument("--json", action="store_true")
    rm = sub.add_parser("remote", help="let other computers open the dashboard (with a sign-in link)")
    rm.add_argument("action", nargs="?", choices=("on", "off", "status", "link"), default="status")
    rm.add_argument("--new", action="store_true", help="link: a new bookmark (the old one stops working)")
    rm.add_argument("--remove", action="store_true", help="link: remove the bookmark")
    rm.add_argument("--listen", default="0.0.0.0", help="address to listen on (default 0.0.0.0: all)")
    rm.add_argument("--port", help="the fixed port other computers use")
    rm.add_argument("--name", help="the name other computers use for this computer")
    rm.add_argument("--json", action="store_true")
    tk = sub.add_parser("token", help="login tokens for the dashboard's login screen (30 days)")
    tk.add_argument("action", nargs="?", choices=("new", "list", "revoke"), default="list")
    tk.add_argument("id", nargs="?", help="revoke: the token's id (from orch dashboard token list)")
    tk.add_argument("--label", help="new: a short name to tell tokens apart (e.g. Anna's laptop)")
    tk.add_argument("--json", action="store_true")
    sn = sub.add_parser("snapshot", help="write a static read-only HTML snapshot")
    sn.add_argument("--out", default="dashboard-snapshot.html")
    sn.add_argument(
        "--with-addons", action="store_true", help="include add-on tabs and ticket rows (left out by default)"
    )
    sn.add_argument("--publish", action="store_true", help="publish it as a private publish app")
    args = ap.parse_args(argv)
    root = find_workspace(Path(args.dir))
    if root is None:
        print("No orch workspace here (no .orch/ folder). Run `orch init` first.", file=sys.stderr)
        return 2
    if args.cmd in ("start", "stop", "status"):
        return _service(args, root)
    if args.cmd == "open":
        return _open(args, root)
    if args.cmd == "remote":
        return _remote(args, root)
    if args.cmd == "token":
        return _token(args, root)
    if args.cmd == "snapshot":
        if args.publish:
            return publish_snapshot(root, with_addons=args.with_addons)
        print(write_snapshot(root, Path(args.out), args.with_addons))
        return 0
    explicit = getattr(args, "port", None) is not None
    port = args.port if explicit else DEFAULT_PORT
    if not explicit and not getattr(args, "auto_port", False) and not getattr(args, "ready_file", None):
        cur = _running_elsewhere(root)
        if cur:  # a person typed `orch dashboard` while the background one runs: its link, no traceback
            print(f"The dashboard already runs for {root.name}: {service.url(cur['port'])}")
            return 0
    listen, why = _listen(root)
    try:
        try:
            srv = make_server(root, port, orch_bin=_orch_bin(), remote=listen)
        except OSError as e:
            if getattr(args, "auto_port", False):
                srv = _bind_fallback(root, listen)  # another workspace has 8420
            elif e.errno == errno.EADDRINUSE:
                srv = _bind_again(
                    root, port, listen=listen
                )  # a self-update restart keeps its port (see _bind_again)
            else:
                raise
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            raise
        print(
            f"Port {port} is taken by another program. Start the dashboard in the background with "
            f"orch start, or pick another port: orch dashboard serve --port <number>",
            file=sys.stderr,
        )
        return 1
    if srv.state_cache.orch_bin == SELF:
        warm(srv)  # the first state is ready by the time a page asks (ORCH-522)
    if getattr(args, "ready_file", None):
        service.write_ready(Path(args.ready_file), srv.server_address[1])
    print(f"orch dashboard for {root.name}: http://127.0.0.1:{srv.server_address[1]}  (Ctrl+C to stop)")
    why = why or srv.remote_error
    if why:
        print(f"Other computers cannot open it: {why}", flush=True)
    elif srv.remote_server is not None:
        threading.Thread(target=srv.remote_server.serve_forever, daemon=True, name="remote").start()
        print(f"Other computers: port {listen[1]} on {listen[0]} (sign in with a link from orch)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


AGENT_RESTART_WARNING = (
    "a helper's restart of a dashboard that other computers open leaves them locked out. "
    "Restart it yourself: orch stop, then orch start."
)


def _by_agent() -> bool:
    from orch import tickets

    return bool(tickets.agent_tool())


def _remote_on(root: Path) -> bool:
    return _listen(root)[0] is not None


def _listen(root: Path) -> tuple[tuple[str, int] | None, str | None]:
    """(address, port) for other computers from the [dashboard] setting, or None; a broken setting says why."""
    try:
        s = remote.settings(root)
    except Exception as e:  # noqa: BLE001 - a bad setting leaves the dashboard local, never down
        return None, str(e)
    return ((s["listen"], s["port"]), None) if s else (None, None)


def _remote(args, root: Path) -> int:
    def out(data: dict, text: str) -> None:
        print(json.dumps(data) if args.json else text)

    if args.action == "link":
        return _link(args, root, out)
    try:
        if args.action == "on":
            if not args.port:
                raise remote.Invalid("Say which port other computers use: --port <number>.")
            s = remote.turn_on(root, args.listen, args.port, args.name)
        elif args.action == "off":
            remote.turn_off(root)
            s = None
        else:
            s = remote.settings(root)
    except remote.Invalid as e:
        print(
            json.dumps({"error": str(e)}) if args.json else f"Refused: {e}",
            file=None if args.json else sys.stderr,
        )
        return 2
    if s is None:
        text = "Other computers cannot open the dashboard (off)."
    else:
        where = remote.url(s) or f"port {s['port']} of this computer"
        text = (
            f"Other computers can open the dashboard at {where} after the sign-in."
            " A sign-in link: orch dashboard open --print (in your own terminal)."
        )
    if args.action != "status":
        text += " Restart the dashboard to apply it: orch stop, then orch start."
    out({"on": s is not None, **({"url": remote.url(s), **s} if s else {})}, text)
    return 0


def _link(args, root: Path, out) -> int:
    """The standing sign-in link (a bookmark that logs this browser in again; a person only)."""
    from orch import pagelaunch
    from orch.errors import Refused

    if args.remove:
        gone = pagelaunch.remove_standing_link(root)
        out(
            {"removed": gone},
            "The sign-in bookmark was removed." if gone else "There was no sign-in bookmark.",
        )
        return 0
    try:
        s = remote.settings(root)
    except remote.Invalid:
        s = None
    cur = service.running(root)
    base = (remote.url(s) if s else None) or (service.url(cur["port"]) if cur else None)
    if base is None:  # checked before the secret is made or renewed: a refused --new keeps the old bookmark
        print(
            json.dumps({"error": "not running"})
            if args.json
            else "Refused: The dashboard is not running, so its address is not known. Start it with: orch start",
            file=None if args.json else sys.stderr,
        )
        return 2
    try:
        secret = pagelaunch.standing_link_secret(root, new=args.new)
    except Refused as e:
        print(
            json.dumps({"error": str(e)}) if args.json else f"Refused: {e}",
            file=None if args.json else sys.stderr,
        )
        return 2
    link = f"{base}/go/{secret}"
    out(
        {"url": link},
        f"Sign-in bookmark: {link}\nOpening it logs that browser in (30 days). Keep it private like a password;"
        " a new one: orch dashboard remote link --new.",
    )
    return 0


OPEN_COMMAND = "orch dashboard open"  # the command the sign-in notice names (orch.pagesession.SIGNIN_MSG)


def _open(args, root: Path) -> int:
    """`orch dashboard open`: open the running dashboard in the person's browser, signed in (a fresh one-time
    sign-in link). `--print`: print that link instead, to open in a browser on another computer (10 minutes,
    once). A person only: under an agent tool it is refused (an agent never signs in as the person)."""
    from orch import pagelaunch, tickets
    from orch.errors import Refused

    def fail(text: str, code: str) -> int:
        print(
            json.dumps({"error": code}) if args.json else f"Refused: {text}",
            file=None if args.json else sys.stderr,
        )
        return 2

    if tickets.agent_tool() is not None and not pagelaunch.is_test_workspace(root):
        return fail(f"Only a person can sign in. Run {OPEN_COMMAND} in your own terminal.", "agent")
    cur = service.running(root)
    if not cur:
        return fail("The dashboard is not running. Start it with: orch start", "not running")
    local = service.url(cur["port"])
    if args.print:
        try:
            s = remote.settings(root)
        except remote.Invalid:
            s = None
        try:
            link = pagelaunch.printable_launch_url(root, "dashboard", (remote.url(s) if s else None) or local)
        except Refused as e:
            return fail(str(e), "refused")
        print(
            json.dumps({"url": link})
            if args.json
            else f"Sign-in link (works once, for 10 minutes): {link}\nKeep it private like a password."
        )
        return 0
    why: list = []
    token = pagelaunch.write_launch_token(root, "dashboard", why=why)
    if not token:  # never open a page without the sign-in and call it signed in
        return fail(why[0] if why else pagelaunch.NO_LINK, "no token")
    if not pagelaunch.open_browser(f"{local}/#launch={token}"):
        return fail(
            f"No browser could be opened here. Use {OPEN_COMMAND} --print and open the link.", "no browser"
        )
    print(json.dumps({"opened": local}) if args.json else f"Opened the dashboard, signed in: {local}")
    return 0


def _when(ts) -> str:
    return time.strftime("%d %b %Y", time.localtime(ts)) if isinstance(ts, int) else "?"


def _token(args, root: Path) -> int:
    """`orch dashboard token new|list|revoke`: the tokens of the login screen (ORCH-1035)."""

    def refuse(text: str) -> int:
        print(
            json.dumps({"error": text}) if args.json else f"Refused: {text}",
            file=None if args.json else sys.stderr,
        )
        return 2

    try:
        from orch import dashlogin
        from orch.errors import Refused
    except ImportError:  # a stand-alone dashboard without orch next to it: no login screen either
        return refuse("Login tokens need orch installed next to the dashboard.")

    if args.action == "new":
        try:
            token, entry = dashlogin.new_token(root, args.label)
        except Refused as e:
            return refuse(str(e))
        if args.json:
            print(json.dumps({"token": token, **entry}))
        else:
            print(
                f"Login token (works until {_when(entry['expires'])}):\n\n  {token}\n\n"
                "Paste it on the dashboard's login screen. It is shown only now: keep it private.\n"
                f"Stop it: orch dashboard token revoke {entry['id']}"
            )
        return 0
    if args.action == "revoke":
        if not args.id:
            return refuse(
                "Say which token: orch dashboard token revoke <id> (see orch dashboard token list)."
            )
        if not dashlogin.revoke_token(root, args.id):
            return refuse(f"There is no token {args.id}. See orch dashboard token list.")
        print(
            json.dumps({"revoked": args.id})
            if args.json
            else f"Token {args.id} revoked. Browsers that logged in with it are logged out."
        )
        return 0
    tokens = dashlogin.list_tokens(root)
    if args.json:
        print(json.dumps({"tokens": tokens}))
        return 0
    if not tokens:
        print("No login tokens yet. Make one: orch dashboard token new")
        return 0
    words = {"active": "works until", "expired": "ended", "revoked": "revoked"}
    for t in tokens:
        when = "" if t["state"] == "revoked" else " " + _when(t["expires"])
        label = f"  {t['label']}" if t["label"] else ""
        print(f"{t['id']}  {words[t['state']]}{when}  (made {_when(t['created'])}){label}")
    return 0


def _service(args, root: Path) -> int:
    if args.cmd == "stop":
        # Check the resolved --dir target too, including direct add-on invocations.
        from orch import service_guard
        from orch.errors import Refused

        try:
            service_guard.require_change(root)
        except Refused as e:
            print(f"Refused: {e}", file=sys.stderr)
            if args.json:
                print(json.dumps({"error": str(e)}))
            return 2

    def out(data: dict, text: str) -> None:
        print(json.dumps(data) if args.json else text)

    warn = (
        AGENT_RESTART_WARNING if args.cmd in ("start", "stop") and _remote_on(root) and _by_agent() else None
    )
    if warn and not args.json:
        print(f"Warning: {warn}", file=sys.stderr)
    if args.cmd == "start":
        try:
            cur = service.start(root)
        except RuntimeError as e:
            print(
                json.dumps({"error": str(e)}) if args.json else f"Refused: {e}",
                file=None if args.json else sys.stderr,
            )
            return 2
        u = service.url(cur["port"])
        out(
            {"running": True, "pid": cur["pid"], "url": u, **({"warning": warn} if warn else {})},
            f"Dashboard for {root.name}: {u}  (stop: orch dashboard stop)",
        )
    elif args.cmd == "stop":
        try:
            res = service.stop(root)
        except RuntimeError as e:
            res = "not verified: " + str(e)
        if res == "stopped":
            out({"stopped": True, **({"warning": warn} if warn else {})}, "Dashboard stopped.")
        elif res == "not running":
            out({"stopped": False}, "The dashboard was not running.")
        else:
            note = (
                "A file in .orch/run/dashboard/ names a process that is not this dashboard; nothing was stopped."
                if res == "not verified"
                else res
            )
            out({"stopped": False, "note": note}, note)
    else:
        try:
            cur = service.running(root)
        except RuntimeError:
            cur = None
        data = {"running": bool(cur), **({"pid": cur["pid"], "url": service.url(cur["port"])} if cur else {})}
        out(data, f"Dashboard running: {data['url']}" if cur else "The dashboard is not running.")
        return 0 if cur else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
