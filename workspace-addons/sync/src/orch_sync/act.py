"""`orch sync act <verb> [--value V] -- <target>`: what the dashboard's Sync card and Needs rows do, through the
dashboard's ONE generic add-on op (`orch <addon> act <verb> -- <target>`).

The address and the choice come from the person's click in the local dashboard. A verb that decides for the person
checks a proof over stdin (`--proof-stdin`, the same targets as `resolve`, `approve`, `deleted`); with
`--proof-target` it only says which target that proof must name (or null) and changes nothing, so the page server
can mint exactly that. Reading verbs (status, check) change nothing.
"""

import hashlib
import tempfile
from pathlib import Path

from orch import config, humanproof

from . import cli, repo

# Needs rows that are part of a pause: Sync now never clears them (the card says "Still paused: N things need you").
PAUSE_KINDS = ("sync:paused", "sync:secret", "sync:key-clash", "sync:case", "sync:history")
WHY = {
    "File exceeds 25 MB": "too big, stays on this computer",
    "busy": "in use, sync tries again",
    "the local file cannot be synced; it was kept as it is": "stays on this computer",
}
SECRET_WHY = "may contain a password or access key"
PUBLIC = "pending-public"  # run/sync/pending-public.json: a public address waiting for the person's signed choice


def _person(what):
    """A person's click only: an agent tool in the environment is refused (the dashboard runs this without one)."""
    from orch import tickets

    if tickets.agent_tool():
        raise repo.Refused(f"A person {what} in the dashboard: Settings, General, Sync.")


def _paused_needs(root):
    from .needs import rows

    return sum(r["kind"] in PAUSE_KINDS for r in rows(root))


def _syncing(root):
    """True while a sync step holds its lock (a live owner)."""
    from orch import procs

    p = repo.safe(root, "run/sync/step.lock")
    try:
        return p.is_file() and not procs.owner_dead(p.read_text())
    except (OSError, ValueError):
        return False


def _not_synced(root, state):
    """[{name, why}]: what the last step kept here (state.skipped) and the files a person left out."""
    from .pause import left_out_names

    out = []
    for line in state.get("skipped") if isinstance(state.get("skipped"), list) else []:
        if not isinstance(line, str):
            continue
        path, sep, reason = line.partition(": ")
        if sep and "/" in path:
            out.append({"name": Path(path).name[:120], "why": WHY.get(reason, "stays on this computer")})
        else:
            out.append({"name": line[:120], "why": ""})
    out += [{"name": Path(p).name[:120], "why": SECRET_WHY} for p in left_out_names(root)]
    return out[:50]


def status(root, settings):
    """The status line and facts of the Sync card (status --json plus what the card shows)."""
    result = cli.status_result(root, settings)
    state = result["state"]
    shown = (
        "off" if settings["mode"] == "off"
        else "syncing" if _syncing(root)
        else "paused" if result["paused"]
        else "offline" if result["last_error"] == "offline"
        else "synced" if result["last_ok"]
        else "never"
    )
    public = cli.read(root, PUBLIC).get("remote")
    return {
        "mode": settings["mode"],
        "remote": cli.safe_address(settings["remote"]) if settings.get("remote") else None,
        "interval": result["interval"],
        "shown": shown,
        "last_ok": result["last_ok"],
        "last_try": result["last_try"],
        "last_error": result["last_error"],
        "paused_needs": _paused_needs(root) if result["paused"] else 0,
        "not_synced": _not_synced(root, state),
        "public": cli.safe_address(public) if isinstance(public, str) else None,
        "remote_allowed": result["remote_allowed"],
        "running": result["running"],
    }


def check(root, address):
    """Can this address be reached? Read-only: sync's own transport rules (https and ssh; a local folder on a test
    install), an empty scratch repository for the call, no login sent to an address that was only typed."""
    try:
        repo.validate_url(address)
    except repo.Refused as e:
        return {"ok": False, "reason": str(e)}
    try:
        with tempfile.TemporaryDirectory(dir=repo.local_dir(root)) as folder:
            scratch = Path(folder)
            (scratch / ".orch").mkdir()
            repo.git(scratch, "init", "-q", "--template=")
            repo.git(scratch, "ls-remote", "--heads", address, timeout=20)
        return {"ok": True}
    except (repo.Refused, OSError):
        return {"ok": False, "reason": "No answer from this address"}


def _interval(value):
    try:
        minutes = int(value) if value not in (None, "") else 15
    except ValueError:
        raise repo.Refused("Sync can run every 5, 15 or 60 minutes") from None
    if minutes not in (5, 15, 60):
        raise repo.Refused("Sync can run every 5, 15 or 60 minutes")
    return minutes


def _forget_public(root):
    from .step import encoded, write

    if cli.read(root, PUBLIC):
        write(root, f"run/sync/{PUBLIC}.json", encoded({}))


def set_where(root, settings, target, value):
    """Off, On this computer only, or an address (Also on another computer or server) every 5, 15 or 60 minutes.
    A public address is not used yet: it waits for the person's signed choice (use-public) or Keep on this computer."""
    _person("chooses where sync keeps a copy")
    if target in ("off", "local"):
        settings, _ = cli.apply_set(root, settings, target)
        _forget_public(root)
        return {"mode": settings["mode"], "text": "Saved."}
    minutes = _interval(value)
    if not cli.remote_allowed():
        raise repo.Refused("Remote sync is preview-only")
    repo.validate_url(target)
    from .visibility import remote_visibility

    known = cli.read(root, "visibility").get(cli.safe_address(target))
    if (known or remote_visibility(target)) == "public":
        from .step import encoded, write

        write(root, f"run/sync/{PUBLIC}.json", encoded({"remote": target, "interval": minutes}))
        return {"mode": settings["mode"], "public": cli.safe_address(target),
                "text": "This sync address is public. Anyone can read your tickets."}
    settings, _ = cli.apply_set(root, settings, "remote", target, minutes)
    _forget_public(root)
    return {"mode": settings["mode"], "remote": cli.safe_address(target), "interval": minutes, "text": "Saved."}


def public_target(root):
    pending = cli.read(root, PUBLIC)
    if not isinstance(pending.get("remote"), str):
        raise repo.Refused("No public address waits for a choice")
    return "sync:use-public:" + hashlib.sha256(pending["remote"].encode()).hexdigest()


def use_public(root, settings, args):
    """The person's signed choice to sync to the public address anyway (bound to that exact address)."""
    target = public_target(root)
    pending = cli.read(root, PUBLIC)
    by = humanproof.person_by(root, args, "addon.act", target,
                              no_handoff="Using a public sync address needs a person's proof over stdin.")
    config.require_person(by, "use a public sync address")
    settings, _ = cli.apply_set(root, settings, "remote", pending["remote"], _interval(pending.get("interval")))
    _forget_public(root)
    return {"mode": settings["mode"], "remote": cli.safe_address(pending["remote"]), "text": "Using the public location."}


def now(root, settings):
    """Sync now. It never clears a pause or a public address that waits: it says what still needs the person."""
    import time

    from . import loop, service
    from .pause import verified_pause

    if verified_pause(root, cli.read(root, "state")):
        n = max(_paused_needs(root), 1)
        return {"still_paused": n, "text": f"Still paused: {n} thing{'s' if n > 1 else ''} need{'' if n > 1 else 's'} you"}
    if cli.read(root, PUBLIC).get("remote"):
        return {"choose_first": True, "text": "Not synced: choose a location above first"}
    if settings["mode"] == "off":
        raise repo.Refused("Sync is off here")
    if service.running_pid(root):
        loop.wake_up(root)
        return {"woken": True, "text": "Syncing…"}
    from .step import run_once

    loop.note(root, last_try=loop.iso(time.time()))
    result = run_once(root, "manual")
    loop.note(root, last_error=None)
    return {"last_error": result.get("last_error"), "last_ok": result.get("last_ok"), "text": "Synced."}


def _pair(target):
    """`<ticket>:<add-on>` of a held add-on change."""
    tid, sep, addon = str(target).partition(":")
    if not sep:
        raise repo.Refused("Say the ticket and the add-on: <ticket>:<add-on>")
    return tid, addon


def _held_target(root, target, kind):
    from .approval import digest, held

    tid, addon = _pair(target)
    found = [b for _, b in held(root, tid) if b["addon"] == addon]
    if len(found) != 1:
        raise repo.Refused("No single held change for this ticket and add-on")
    return f"sync:{kind}:{tid}:{addon}:{digest(found[0]['value'])}"


def proof_target(root, verb, target):
    """The target the proof of this click must name, or None when it needs none. Changes nothing."""
    from . import pause

    if verb in ("keep-mine", "keep-theirs"):
        return pause.resolve_target(root, target, verb.removeprefix("keep-"))
    if verb == "leave-out":
        return pause.leave_out_target(root, target)
    if verb in ("allow", "ignore"):
        return _held_target(root, target, verb)
    if verb == "leave-deleted":
        return "sync:deleted:" + target
    if verb == "use-public":
        return public_target(root)
    return None


def act(root, settings, args):
    verb, target = args.verb, args.target
    if args.proof_target:
        return {"target": proof_target(root, verb, target)}
    if verb == "status":
        return status(root, settings)
    if verb == "check":
        return check(root, target)
    if verb == "set":
        return set_where(root, settings, target, args.value)
    if verb == "now":
        return now(root, settings)
    if verb == "use-public":
        return use_public(root, settings, args)
    if verb in ("keep-mine", "keep-theirs"):
        from .pause import resolve

        result = resolve(root, target, verb.removeprefix("keep-"), args)
        return {"paused": bool(result.get("paused")), "text": "Kept your version." if verb == "keep-mine" else "Kept the other version."}
    if verb == "leave-out":
        from .pause import leave_out

        result = leave_out(root, target, args)
        return {"paused": bool(result.get("paused")), "text": "Left out. It stays on this computer."}
    if verb in ("allow", "ignore"):
        from .approval import approve

        tid, addon = _pair(target)
        args.ignore = verb == "ignore"
        return {**approve(root, tid, addon, args), "text": "Allowed." if verb == "allow" else "Ignored."}
    if verb in ("leave-deleted", "restored"):
        return {**cli.deleted(root, target, verb == "restored", args), "text": "Done."}
    raise repo.Refused("That action is not available")
