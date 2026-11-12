"""`orch sync`: local settings, one-shot sync, the background loop (start/stop/status/now) and the person's choices."""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from orch.errors import Refused as CoreRefused

from . import repo
from .settings import DEFAULTS, minutes

ACT_VERBS = ("status", "check", "set", "now", "use-public", "keep-mine", "keep-theirs", "leave-out", "allow",
             "ignore", "leave-deleted", "restored")


def remote_allowed():
    """PR 4's sync step must call this on every run, before remote operations."""
    return os.environ.get("ORCH_SYNC_REMOTE_PREVIEW") == "1"


def read(root, name):
    p = repo.safe(root, f"run/sync/{name}.json")
    data = json.loads(p.read_text()) if p.exists() else {}
    if not isinstance(data, dict):
        raise repo.Refused("Invalid local sync settings or state")
    return data


def safe_address(url):
    address = urlsplit(url)
    return urlunsplit(address._replace(netloc=address.netloc.rsplit("@", 1)[-1]))


def consent(settings):
    """What turning sync on means, in plain words: what, where, how often, and that it can be turned off."""
    if settings["mode"] == "local":
        where, often = "on this computer only; nothing leaves it", "every 5 minutes at most, when something changed"
    else:
        where = f"on this computer and at {safe_address(settings.get('remote') or '')}"
        often = f"every {minutes(settings)} minutes"
    return (
        "Sync keeps a copy of your tickets and their files in .orch. It never copies secrets or private files "
        f"(settings, chat, keys and passwords stay here). Where: {where}. How often: {often}. "
        "You can turn it off any time: orch sync set --mode off"
    )


def status_line(s):
    if s["mode"] == "off":
        return "Sync is off."
    run = f"running, next {s['next_run']}" if s["running"] else "not running (orch sync start)"
    return (f"Sync: {s['mode']}, every {s['interval']} minutes, {run}. Last synced: {s['last_ok'] or 'never'}. "
            f"Paused: {'yes' if s['paused'] else 'no'}." + (f" Problem: {s['last_error']}" if s["last_error"] else ""))


def save_settings(root, settings):
    target = repo.safe(root, "run/sync/settings.json")
    with tempfile.NamedTemporaryFile(mode="w", dir=repo.local_dir(root), delete=False) as f:
        json.dump(settings, f)
        f.flush()
        os.fsync(f.fileno())
    try:
        os.replace(f.name, target)
    finally:
        Path(f.name).unlink(missing_ok=True)


def apply_set(root, settings, mode=None, remote=None, interval=None, kind="private"):
    """`orch sync set` (also `orch sync act set`): check, save and wake the loop. Returns (settings, notice): the
    notice is the visibility line for a remote address seen for the first time, else None."""
    if mode is None and interval is None:
        raise repo.Refused("Say what to change: --mode off|local|remote or --interval 5|15|60")
    if interval is not None and interval not in (5, 15, 60):
        raise repo.Refused("Sync can run every 5, 15 or 60 minutes")
    mode = mode or settings["mode"]
    if mode == "local" and interval is not None:
        raise repo.Refused("Local sync runs every 5 minutes at most. --interval is only for remote sync")
    if kind != "private":
        raise repo.Refused("Team sync is not available yet")
    if (mode == "remote" or remote is not None) and not remote_allowed():
        raise repo.Refused("Remote sync is preview-only")
    if remote:
        repo.validate_url(remote)
    if mode == "off" and remote:
        raise repo.Refused("Set a remote in local or remote mode")
    if mode == "remote" and not (remote or settings.get("remote")):
        raise repo.Refused("A remote address is required")
    if mode != "off":
        repo.ensure(root)
    notice = None
    if remote:
        repo.set_remote(root, remote)
        settings["remote"] = remote
        from .visibility import remote_visibility

        safe_url = safe_address(remote)
        notices = read(root, "visibility")
        if safe_url not in notices:
            visibility = remote_visibility(remote)
            notices[safe_url] = visibility
            from .step import encoded, write

            write(root, "run/sync/visibility.json", encoded(notices))
            notice = "Anyone can read this repository" if visibility == "public" else "Make sure this repository is private"
    settings.update(mode=mode, kind=kind, interval=interval or settings["interval"])
    save_settings(root, settings)
    from . import loop, service

    if service.running_pid(root):
        loop.wake_up(root)  # the loop reads the new settings now (and ends when set to off)
    return settings, notice


def status_result(root, settings):
    """`orch sync status --json`: the settings with the loop's and the last step's facts."""
    from . import loop, service
    from .pause import verified_pause

    state = read(root, "state")
    info = service.read(root, loop.INFO)
    pid = service.running_pid(root)
    return {
        "state": state,
        **settings,
        "interval": loop.minutes(settings),
        "running": bool(pid),
        "remote_allowed": remote_allowed(),
        **{k: state.get(k) for k in ("last_ok", "ahead", "behind")},
        "last_try": info.get("last_try"),
        "last_error": info.get("last_error") or state.get("last_error"),
        "paused": verified_pause(root, state) is not None,
        "next_run": info.get("next_run") if pid else None,
    }


def deleted(root, ticket, keep, args):
    """A missing ticket notice: OK (keep it restored) or leave it deleted on every computer (a person's proof)."""
    from orch import config, humanproof, syncgate

    from .step import encoded, entries, step_lock, write

    with step_lock(root), syncgate.hold(root):
        state = read(root, "state")
        if ticket not in state.get("deleted", {}):
            raise repo.Refused("No missing ticket notice")
        if not keep:
            by = humanproof.person_by(
                root,
                args,
                "addon.act",
                "sync:deleted:" + ticket,
                no_handoff="Leaving a ticket deleted needs a person's proof.",
            )
            config.require_person(by, "leave this ticket deleted")
            from . import records

            # bound to the synced copy the person leaves deleted: a changed ticket needs them again
            old = entries(root, "HEAD").get(f"tickets/{ticket}.json")
            if not old:
                raise repo.Refused("This ticket has no synced copy to leave deleted")
            allowed = read(root, "allow-delete")
            allowed[ticket] = records.make(root, "delete", f"{ticket}:{old[1]}", {"ticket": ticket, "blob": old[1]})
            write(root, "run/sync/allow-delete.json", encoded(allowed))
        state["deleted"].pop(ticket)
        from .pause import verified_pause

        state["paused"] = verified_pause(root, state)  # a planted pause is not written back
        write(root, "run/sync/state.json", encoded(state))
    return {"acknowledged": ticket}


def _run_loop(root):
    """`orch sync run`: the loop in the foreground; `start` runs it in the background. One loop per folder: it holds
    the loop lock for its whole life, and a second loop ends at once. Every end leaves one line (loop.log)."""
    import signal
    import threading
    import traceback

    from . import loop, service

    held = service.announce(root)  # the lock, then pid + start time in .orch/run/sync/
    if held is None:
        print("sync: another sync loop already runs for this folder; this one ends.", flush=True)
        return 0
    lp, code, why = loop.Loop(root), 0, "interrupted"
    if threading.current_thread() is threading.main_thread():
        # finish the current pass, then end. Only a flag here: Event.set() inside a signal handler can block on the
        # lock its own thread holds in wake.wait(); sleep() polls stop_asked() every POLL seconds.
        signal.signal(signal.SIGTERM, lambda *_: setattr(lp, "stopping", True))
    try:
        why = lp.run_forever()
    except KeyboardInterrupt:
        pass
    except Exception:  # noqa: BLE001 - logged with its traceback, never silent
        traceback.print_exc(file=sys.stdout)
        code, why = 2, "an error (traceback above)"
    finally:
        service.forget(root, held)
        print(f"sync: the loop ended: {why}", flush=True)
    return code


def main(argv=None):
    ap = argparse.ArgumentParser(prog="orch sync")
    ap.add_argument("--dir", default=os.environ.get("ORCH_ROOT", "."))
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("set", "status", "now", "start", "stop", "needs", "run"):
        p = sub.add_parser(name)
        p.add_argument("--json", action="store_true")
        if name == "set":
            p.add_argument("--mode", choices=("off", "local", "remote"))
            p.add_argument("--remote")
            p.add_argument("--interval", type=int, help="minutes between remote syncs: 5, 15 or 60")
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
    p = sub.add_parser("take-remote")  # a history pause: the other computer's history becomes the base
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
    # what the dashboard's Sync card and Needs rows do: `orch sync act <verb> [--value V] -- <target>` (act.py)
    p = sub.add_parser("act")
    p.add_argument("verb", choices=ACT_VERBS)
    p.add_argument("target")
    p.add_argument("--value")
    p.add_argument("--proof-target", action="store_true", help="say what a signed verb needs proven; changes nothing")
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
        if args.cmd == "run":
            return _run_loop(root)
        if args.cmd == "act":
            from .act import act

            result = act(root, settings, args)
            print(json.dumps(result) if args.json else result.get("text") or str(result))
            return 0
        if args.cmd == "set":
            asked = args.mode
            settings, notice = apply_set(root, settings, args.mode, args.remote, args.interval, args.kind)
            if notice:
                print(notice, file=sys.stderr)
            result = settings
            if asked in ("local", "remote"):
                text = consent(settings)
                if args.json:
                    result = {**settings, "consent": text}
                else:
                    print(text, file=sys.stderr)
        elif args.cmd == "now":
            import time

            from . import loop, service
            from .step import run_once

            if service.running_pid(root):
                loop.wake_up(root)
                result = {"woken": True}
                print(json.dumps(result) if args.json else "Sync runs now in the background.")
                return 0
            loop.note(root, last_try=loop.iso(time.time()))
            result = run_once(root, "manual")
            # status shows the loop's own error first: an old one must not outlive this pass (its error, if any,
            # is in state.json now)
            loop.note(root, last_error=None)
            print(json.dumps(result) if args.json else str(result))
            return 2 if result.get("last_error") else 0
        elif args.cmd == "status":
            result = status_result(root, settings)
            if not args.json:
                print(status_line(result))
                return 0
        elif args.cmd == "resolve":
            from .pause import resolve, resolve_case

            if args.keep:
                result = resolve(root, args.path, args.keep, args)
            else:
                result = resolve_case(root, args.path, args, rename=args.rename_local)
        elif args.cmd == "keep-key":
            from .pause import keep_key

            result = keep_key(root, args.key, args.ticket, args)
        elif args.cmd == "take-remote":
            from .pause import take_remote

            result = take_remote(root, args)
        elif args.cmd == "approve":
            from .approval import approve

            result = approve(root, args.ticket, args.addon, args)
        elif args.cmd == "needs":
            from .needs import rows

            result = rows(root)
        elif args.cmd == "deleted":
            result = deleted(root, args.ticket, args.keep, args)
        elif args.cmd == "start":
            from . import orchcli, service

            if settings["mode"] == "off":  # a normal state (orch start starts every add-on): quiet, not an error
                result = {"running": False, "off": True, "message": "Sync is off here: nothing to start."}
            elif (active := orchcli.is_active(root)) is None:
                raise repo.Refused("Could not check whether the sync add-on is on here (orch did not answer). "
                                   "Try again: orch sync start")
            elif not active:
                raise repo.Refused("The sync add-on is not on here. A person turns it on: orch addon add sync")
            else:
                result = {"running": True, "pid": service.start(root)}
        elif args.cmd == "stop":
            from . import service

            res = service.stop(root)
            result = {"stopped": res == "stopped"}
            if res == "still running":
                result["note"] = "Sync is finishing its current round and stops right after it."
            if res == "not verified":
                result["note"] = "A file in .orch/run/sync/ names a process that is not the sync loop; nothing was stopped."
        if args.cmd == "set" and not args.json:
            message = (
                "Sync is off"
                if settings["mode"] == "off"
                else (
                    f"Sync: {settings['mode']}, every {minutes(settings)} minutes"
                    + (f", to {safe_address(settings.get('remote') or '')}" if settings["mode"] == "remote" else "")
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
