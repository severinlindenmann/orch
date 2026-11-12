"""`orch sync`: local settings, one-shot sync, the background loop (start/stop/status/now) and the person's choices."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from orch.errors import Refused as CoreRefused

from . import repo
from .settings import DEFAULTS, minutes

ACT_VERBS = (
    "status",
    "check",
    "set",
    "now",
    "use-public",
    "keep-mine",
    "keep-theirs",
    "leave-out",
    "allow",
    "ignore",
    "leave-deleted",
    "restored",
)


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
        where, often = (
            "on this computer only; nothing leaves it",
            "every 5 minutes at most, when something changed",
        )
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
    return (
        f"Sync: {s['mode']}, every {s['interval']} minutes, {run}. Last synced: {s['last_ok'] or 'never'}. "
        f"Paused: {'yes' if s['paused'] else 'no'}."
        + (f" Problem: {s['last_error']}" if s["last_error"] else "")
    )


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


REMOTE_TARGET = "sync:set-remote:"
PUBLIC_TARGET = "sync:use-public:"


def remote_target(address, public=False):
    """The proof target of choosing exactly this sync address (the whole address as it is used): use-public for a
    public address the person chose anyway, set-remote for any other."""
    return (PUBLIC_TARGET if public else REMOTE_TARGET) + hashlib.sha256(address.encode()).hexdigest()


ADDRESS = "run/sync/address.json"  # the address the person's signed set-remote / use-public choice applied
ADDRESS_KIND = (
    "sync-remote-address"  # its local1 domain: only apply_set writes (signs) it, after the person's proof
)
UNCONFIRMED = "Sync found an address you did not choose and did not use it. Choose where to sync in Settings."


class Unconfirmed(repo.RemoteRefused):
    """settings.json names a remote the person never chose with a signed choice (it is agent-writable): no network."""

    def __init__(self):
        super().__init__(UNCONFIRMED)


def _address_record(address):
    return {"sha256": hashlib.sha256(address.encode()).hexdigest()}


def approve_address(root, address):
    """Record exactly the address a person's signed choice applies: pinned in the guarded home (humanproof.pin_next:
    a counter + the digest of the ONE current body, so an older signed copy of this file never counts again), then
    local1-signed. Only apply_set calls it."""
    from orch import humanproof

    from .step import encoded, write

    body = humanproof.pin_next(root, ADDRESS_KIND, _address_record(address))
    mac = humanproof.local_sign(root, ADDRESS_KIND, body) if body else None
    if not mac:
        raise repo.Refused("orch could not sign this choice; nothing was changed")
    write(root, ADDRESS, encoded({**body, "mac": mac}))


def revoke_address(root):
    """The person left remote: pin an empty body (every earlier signed address record is now older than the pin,
    so a restored copy confirms nothing) and remove the file. Fails closed: without a pin the file still goes."""
    from orch import humanproof

    try:
        repo.safe(root, ADDRESS).unlink(
            missing_ok=True
        )  # stops sync now either way (address_confirmed is false)
        failed = None
    except (
        OSError,
        repo.Refused,
    ) as e:  # a planted folder or link: the pin still moves, the person sees the error
        failed = e
    pin = humanproof.record_pin(root, ADDRESS_KIND)
    # unreadable (None: e.g. a damaged .orch/.local-id, which an agent can write) or a pin that can't move: the old
    # pin may still name the old record, and a restored copy would count again once the pin reads again (N-1).
    # {}: no pin was ever made, so no address record can ever pass pin_ok
    if pin is None or (pin != {} and not humanproof.pin_next(root, ADDRESS_KIND, {"sha256": None})):
        raise repo.Refused("orch could not record that sync left this address. Sync is stopped; try again.")
    if failed is not None:
        raise repo.Refused(
            "orch could not remove the sync address record. Sync is stopped; ask the owner to clear it."
        )


def address_confirmed(root, address):
    """True only when `address` is exactly the one the record names and the record is as this core signed it. A
    missing, planted, edited or unreadable record confirms nothing."""
    from orch import humanproof

    if not isinstance(address, str) or not address:
        return False
    try:
        data = json.loads(repo.safe(root, ADDRESS).read_text())
    except (ValueError, OSError, RecursionError):
        return False
    if not isinstance(data, dict):
        return False
    body = {k: v for k, v in data.items() if k != "mac"}
    return (
        {k: v for k, v in body.items() if k != "counter"} == _address_record(address)
        and type(body.get("counter")) is int
        and humanproof.local_ok(root, ADDRESS_KIND, body, data.get("mac"))
        and humanproof.pin_ok(root, ADDRESS_KIND, body)  # the current record, never a restored older one
    )


def confirmed_remote(root, settings):
    """The remote of remote mode, only when the person confirmed exactly it (address_confirmed); else refused before
    any network call. Every remote-mode path (step, pause choices) asks this first."""
    url = settings.get("remote")
    if not url:
        raise repo.Refused("A remote address is required")
    if not address_confirmed(root, url):
        raise Unconfirmed()
    return url


class PublicAddress(repo.Refused):
    """A public address on a plain choice: never used then (the person's use-public choice is a separate one)."""

    def __init__(self, address):
        super().__init__(
            "This sync address is public. Anyone can read your tickets. Choose it in the dashboard "
            "(Settings, General, Sync), or add --public with a person's proof"
        )
        self.address = address


def _remote_gate(root, address, args, public):
    """Every path that sets a remote passes here (gate parity): the address's visibility is probed every time (a
    cached answer is agent-writable, M1), a public address is only ever used on the person's use-public choice,
    and the choice itself is a person's proof bound to that exact address (M4). Returns the probed visibility."""
    from orch import config, humanproof

    from .visibility import remote_visibility

    visibility = remote_visibility(address)
    if visibility == "public" and not public:
        raise PublicAddress(address)
    by = humanproof.person_by(
        root,
        args,
        "addon.act",
        remote_target(address, public),
        no_handoff="Choosing where sync keeps a copy needs a person's proof over stdin.",
    )
    config.require_person(by, "choose where sync keeps a copy")
    return visibility


def apply_set(
    root, settings, mode=None, remote=None, interval=None, kind="private", *, args=None, public=False
):
    """`orch sync set` (also `orch sync act set` and `use-public`): check, save and wake the loop. Returns
    (settings, notice): the notice is the visibility line for a remote address seen for the first time, else None.
    Choosing or changing the remote address (`remote`, or turning remote on with the stored one) is a person's
    signed choice (_remote_gate); `public` = the caller is the person's use-public choice. Mode off, mode local
    and the interval need no proof."""
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
    # turning remote on uses the stored address: that is choosing it too (settings.json is agent-writable)
    chosen = remote or (settings.get("remote") if mode == "remote" and settings["mode"] != "remote" else None)
    visibility = None
    if chosen:
        visibility = _remote_gate(
            root, chosen, args, public
        )  # everything that can refuse ran before the proof
    if mode != "off":
        repo.ensure(root)
    notice = None
    if remote:
        repo.set_remote(root, remote)
        settings["remote"] = remote
        safe_url = safe_address(remote)
        notices = read(root, "visibility")  # only words the notice once; never decides anything (M1)
        if safe_url not in notices:
            notices[safe_url] = visibility
            from .step import encoded, write

            write(root, "run/sync/visibility.json", encoded(notices))
            notice = (
                "Anyone can read this repository"
                if visibility == "public"
                else "Make sure this repository is private"
            )
    if chosen:
        approve_address(root, chosen)  # the address this signed choice applies (checked at every use)
    elif mode in ("off", "local"):
        # leaving remote revokes the signed address: planting mode=remote in settings.json later can't bring the old
        # approval back (nor can a restored copy: the pin moved on); turning remote on again is a new signed choice
        settings.pop(
            "remote", None
        )  # off or local: no stored address that could look unconfirmed later (N-3)
        save_settings(
            root, {**settings, "mode": mode}
        )  # stop using the address first, then revoke (fails closed)
        revoke_address(root)
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
            allowed[ticket] = records.make(
                root, "delete", f"{ticket}:{old[1]}", {"ticket": ticket, "blob": old[1]}
            )
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
            # choosing the remote address is a person's signed choice (sync:set-remote:<sha256(address)>; a public
            # address: --public and sync:use-public:<sha256(address)>)
            p.add_argument("--public", action="store_true")
            p.add_argument("--proof-stdin", action="store_true")
            p.add_argument("--by")
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
    p.add_argument(
        "--proof-target", action="store_true", help="say what a signed verb needs proven; changes nothing"
    )
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
            settings, notice = apply_set(
                root,
                settings,
                args.mode,
                args.remote,
                args.interval,
                args.kind,
                args=args,
                public=args.public,
            )
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

            if (
                settings["mode"] == "off"
            ):  # a normal state (orch start starts every add-on): quiet, not an error
                result = {"running": False, "off": True, "message": "Sync is off here: nothing to start."}
            elif (active := orchcli.is_active(root)) is None:
                raise repo.Refused(
                    "Could not check whether the sync add-on is on here (orch did not answer). "
                    "Try again: orch sync start"
                )
            elif not active:
                raise repo.Refused(
                    "The sync add-on is not on here. A person turns it on: orch addon add sync"
                )
            else:
                result = {"running": True, "pid": service.start(root)}
        elif args.cmd == "stop":
            from . import service

            res = service.stop(root)
            result = {"stopped": res == "stopped"}
            if res == "still running":
                result["note"] = "Sync is finishing its current round and stops right after it."
            if res == "not verified":
                result["note"] = (
                    "A file in .orch/run/sync/ names a process that is not the sync loop; nothing was stopped."
                )
        if args.cmd == "set" and not args.json:
            message = (
                "Sync is off"
                if settings["mode"] == "off"
                else (
                    f"Sync: {settings['mode']}, every {minutes(settings)} minutes"
                    + (
                        f", to {safe_address(settings.get('remote') or '')}"
                        if settings["mode"] == "remote"
                        else ""
                    )
                )
            )
            print(message)
        else:
            print(json.dumps(result) if args.json else str(result))
        return 0
    except Exception as e:  # noqa: BLE001 - Fable B14: fail closed on any error, including hostile data shapes
        message = (
            str(e)
            if isinstance(e, (ValueError, OSError, CoreRefused))
            else f"Sync stopped: {type(e).__name__}"
        )
        print(
            json.dumps({"error": message}) if args.json else f"Refused: {message}",
            file=sys.stdout if args.json else sys.stderr,
        )
        return 2
