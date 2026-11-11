"""Local settings and one-shot sync. Consent flows are not shipped yet."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from orch.errors import Refused as CoreRefused

from . import repo

DEFAULTS = {"mode": "off", "interval": 15, "kind": "private"}


def remote_allowed():
    """PR 4's sync step must call this on every run, before remote operations."""
    return os.environ.get("ORCH_SYNC_REMOTE_PREVIEW") == "1"


def read(root, name):
    p = repo.safe(root, f"run/sync/{name}.json")
    data = json.loads(p.read_text()) if p.exists() else {}
    if not isinstance(data, dict):
        raise repo.Refused("Invalid local sync settings or state")
    return data


def main(argv=None):
    ap = argparse.ArgumentParser(prog="orch sync")
    ap.add_argument("--dir", default=os.environ.get("ORCH_ROOT", "."))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("set", "status", "now", "start", "stop", "needs"):
        p = sub.add_parser(name)
        p.add_argument("--json", action="store_true")
        if name == "set":
            p.add_argument("--mode", choices=("off", "local", "remote"), required=True)
            p.add_argument("--remote")
            p.add_argument("--interval", type=int, choices=(5, 15, 60))
            p.add_argument("--kind", choices=("private", "team"), default="private")
    p = sub.add_parser("resolve")
    p.add_argument("path")
    choice = p.add_mutually_exclusive_group(required=True)
    choice.add_argument("--keep", choices=("mine", "theirs"))
    # a name that differs from this machine's only in case: keep my file name, or rename my file
    choice.add_argument("--keep-local-name", action="store_true")
    choice.add_argument("--rename-local", metavar="NEW_NAME")
    p.add_argument("--proof-stdin", action="store_true")
    p.add_argument("--by")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("keep-key")
    p.add_argument("key")
    p.add_argument("ticket")
    p.add_argument("--proof-stdin", action="store_true")
    p.add_argument("--by")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("approve")
    p.add_argument("ticket")
    p.add_argument("addon")
    p.add_argument("--ignore", action="store_true")
    p.add_argument("--proof-stdin", action="store_true")
    p.add_argument("--by")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("deleted")
    p.add_argument("ticket")
    p.add_argument("--keep", action="store_true")
    p.add_argument("--proof-stdin", action="store_true")
    p.add_argument("--by")
    p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        start = Path(args.dir).absolute()
        root = next((p for p in (start, *start.parents) if (p / ".orch").exists()), None)
        if root is None:
            raise repo.Refused("No orch workspace here")
        settings = DEFAULTS | read(root, "settings")
        if args.cmd == "set":
            if args.kind != "private":
                raise repo.Refused("Team sync is not available yet")
            if (args.mode == "remote" or args.remote is not None) and not remote_allowed():
                raise repo.Refused("Remote sync is preview-only")
            if args.remote:
                repo.validate_url(args.remote)
            if args.mode == "off" and args.remote:
                raise repo.Refused("Set a remote in local or remote mode")
            if args.mode == "remote" and not (args.remote or settings.get("remote")):
                raise repo.Refused("A remote address is required")
            if args.mode != "off":
                repo.ensure(root)
            if args.remote:
                repo.set_remote(root, args.remote)
                settings["remote"] = args.remote
                from .visibility import remote_visibility

                address = urlsplit(args.remote)
                safe_url = urlunsplit(address._replace(netloc=address.netloc.rsplit("@", 1)[-1]))
                notices = read(root, "visibility")
                if safe_url not in notices:
                    visibility = remote_visibility(args.remote)
                    notices[safe_url] = visibility
                    from .step import encoded, write

                    write(root, "run/sync/visibility.json", encoded(notices))
                    print(
                        "Anyone can read this repository"
                        if visibility == "public"
                        else "Make sure this repository is private",
                        file=sys.stderr,
                    )
            settings.update(mode=args.mode, kind=args.kind, interval=args.interval or settings["interval"])
            target = repo.safe(root, "run/sync/settings.json")
            with tempfile.NamedTemporaryFile(mode="w", dir=repo.local_dir(root), delete=False) as f:
                json.dump(settings, f)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.replace(f.name, target)
            finally:
                Path(f.name).unlink(missing_ok=True)
            result = settings
        elif args.cmd == "now":
            from .step import run_once

            result = run_once(root, "manual")
            print(json.dumps(result) if args.json else str(result))
            return 2 if result.get("last_error") else 0
        elif args.cmd == "status":
            state = read(root, "state")
            result = {
                "state": state,
                **settings,
                "running": False,
                "remote_allowed": remote_allowed(),
                **{k: state.get(k) for k in ("last_ok", "last_error", "ahead", "behind")},
            }
        elif args.cmd == "resolve":
            from .pause import resolve, resolve_case

            if args.keep:
                result = resolve(root, args.path, args.keep, args)
            else:
                result = resolve_case(root, args.path, args, rename=args.rename_local)
        elif args.cmd == "keep-key":
            from .pause import keep_key

            result = keep_key(root, args.key, args.ticket, args)
        elif args.cmd == "approve":
            from .approval import approve

            result = approve(root, args.ticket, args.addon, args)
        elif args.cmd == "needs":
            from .needs import rows

            result = rows(root)
        elif args.cmd == "deleted":
            from orch import config, humanproof, syncgate

            from .step import encoded, step_lock, write

            with step_lock(root), syncgate.hold(root):
                state = read(root, "state")
                if args.ticket not in state.get("deleted", {}):
                    raise repo.Refused("No missing ticket notice")
                if not args.keep:
                    by = humanproof.person_by(
                        root,
                        args,
                        "addon.act",
                        "sync:deleted:" + args.ticket,
                        no_handoff="Leaving a ticket deleted needs a person's proof.",
                    )
                    config.require_person(by, "leave this ticket deleted")
                    allowed = read(root, "allow-delete")
                    allowed[args.ticket] = True
                    write(root, "run/sync/allow-delete.json", encoded(allowed))
                state["deleted"].pop(args.ticket)
                write(root, "run/sync/state.json", encoded(state))
            result = {"acknowledged": args.ticket}
        elif args.cmd == "start":
            raise repo.Refused("The sync loop is not available yet")
        else:
            result = [] if args.cmd == "needs" else {"stopped": False}
        if args.cmd == "set" and not args.json:
            message = (
                "Sync is off"
                if settings["mode"] == "off"
                else (
                    f"Sync: {settings['mode']}, every {settings['interval']} minutes"
                    + (f", to {settings['remote']}" if settings["mode"] == "remote" else "")
                )
            )
            print(message)
        else:
            print(json.dumps(result) if args.json else str(result))
        return 0
    except Exception as e:  # noqa: BLE001 - Fable B14: fail closed on any error, including hostile data shapes
        message = str(e) if isinstance(e, (ValueError, OSError, CoreRefused)) else f"Sync stopped: {type(e).__name__}"
        print(
            json.dumps({"error": message}) if args.json else f"Refused: {message}",
            file=sys.stdout if args.json else sys.stderr,
        )
        return 2
