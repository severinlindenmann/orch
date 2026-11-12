"""`orch sync act <verb> [--value V] -- <target>`: what the dashboard's Sync card and Needs rows do, through the
dashboard's ONE generic add-on op (`orch <addon> act <verb> -- <target>`).

The address and the choice come from the person's click in the local dashboard. A verb that decides for the person
checks a proof over stdin (`--proof-stdin`, the same targets as `resolve`, `approve`, `deleted`); with
`--proof-target` it only says which target that proof must name (or null) and what the sign step shows (`review`),
both worked out from the same read of the same bytes, and changes nothing. The page shows exactly that review and
the server mints only for the target it echoes back; the verb checks the target again when it runs. Reading verbs
(status, check) change nothing.
"""

import json
import re
import tempfile
from pathlib import Path

from orch import config, humanproof

from . import cli, paths, repo

# Needs rows that are part of a pause: Sync now never clears them (the card says "Still paused: N things need you").
PAUSE_KINDS = ("sync:paused", "sync:secret", "sync:key-clash", "sync:case", "sync:history")
WHY = {
    "File exceeds 25 MB": "too big, stays on this computer",
    "busy": "in use, sync tries again",
    "the local file cannot be synced; it was kept as it is": "stays on this computer",
}
SECRET_WHY = "may contain a password or access key"
PUBLIC = "pending-public"  # run/sync/pending-public.json: a public address waiting for the person's signed choice
PUBLIC_KIND = "sync-pending-public"  # its local1 domain: only set_where writes (signs) it
NO_ADDRESS = "Sync can't use this address: https or ssh, without a password"
# what a sign step never shows as such: controls (C0, C1), bidi overrides and marks, zero-width characters
HIDDEN = re.compile("[\x00-\x1f\x7f-\x9f\u061c\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]")


def _person(what):
    """A person's click only: an agent tool in the environment is refused (the dashboard runs this without one)."""
    from orch import tickets

    if tickets.agent_tool():
        raise repo.Refused(f"A person {what} in the dashboard: Settings, General, Sync.")


def plain(value, limit=200):
    """Text from a peer, a file or the agent as one clipped plain line for a sign step: whitespace collapsed, every
    control, bidi or zero-width character shown as U+FFFD (never hidden), at most `limit` characters."""
    text = HIDDEN.sub("\ufffd", " ".join(str(value).split()))
    return text if len(text) <= limit else text[: limit - 1] + "…"


REVIEW_MAX = 3000  # characters a sign step shows in full (the dashboard allows 4000 per review)
TOO_LARGE = ("This change is too large to review here, so it can't be signed in the dashboard. "
             "See it with: orch sync needs --json, then decide on the command line.")


def whole(value):
    """A signed value shown in FULL (M-C): never clipped, so what the person signs is what they see. Hidden
    characters are shown as U+FFFD. Too long for a sign step: refused (nothing is offered for signing)."""
    text = HIDDEN.sub("\ufffd", " ".join(str(value).split()))
    if len(text) > REVIEW_MAX:
        raise repo.Refused(TOO_LARGE)
    return text


def _address(remote):
    """A sync address as the sign step shows it: whole, without a login."""
    return plain(cli.safe_address(remote), 600)


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


def pending_public(root):
    """The public address that waits for the person's choice ({remote, interval}), read once: only exactly as
    set_where signed it (local1). A planted, edited or unreadable record counts as absent everywhere (status, the
    proof target, use-public, Sync now)."""
    try:
        data = cli.read(root, PUBLIC)
    except (ValueError, OSError, RecursionError):
        return None
    body = {k: v for k, v in data.items() if k != "mac"}
    if set(body) != {"remote", "interval"} or not isinstance(body["remote"], str):
        return None
    return body if humanproof.local_ok(root, PUBLIC_KIND, body, data.get("mac")) else None


def _write_public(root, remote, minutes):
    from .step import encoded, write

    body = {"remote": remote, "interval": minutes}
    mac = humanproof.local_sign(root, PUBLIC_KIND, body)
    if not mac:
        raise repo.Refused("orch could not sign this choice; nothing was changed")
    write(root, f"run/sync/{PUBLIC}.json", encoded({**body, "mac": mac}))


def _forget_public(root):
    repo.safe(root, f"run/sync/{PUBLIC}.json").unlink(missing_ok=True)


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
    public = pending_public(root)
    # an address the person never confirmed (settings.json is agent-writable) is never shown as theirs (no pre-fill)
    confirmed = bool(settings.get("remote")) and cli.address_confirmed(root, settings["remote"])
    return {
        "mode": settings["mode"],
        "remote": cli.safe_address(settings["remote"]) if confirmed else None,
        "confirmed": confirmed,
        "unconfirmed": settings["mode"] == "remote" and bool(settings.get("remote")) and not confirmed,
        "interval": result["interval"],
        "shown": shown,
        "last_ok": result["last_ok"],
        "last_try": result["last_try"],
        "last_error": result["last_error"],
        "paused_needs": _paused_needs(root) if result["paused"] else 0,
        "not_synced": _not_synced(root, state),
        "public": cli.safe_address(public["remote"]) if public else None,
        "remote_allowed": result["remote_allowed"],
        "running": result["running"],
    }


def check(root, address):
    """Can this address be reached? Read-only: sync's own transport rules (https and ssh; a local folder on a test
    install), an empty scratch repository for the call, no login sent to an address that was only typed (repo.git:
    no prompt, no credential helper, ssh in batch mode). The reason is a fixed line, never the address."""
    try:
        repo.validate_url(address)
    except repo.Refused:
        return {"ok": False, "reason": NO_ADDRESS}
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
    except (TypeError, ValueError):
        raise repo.Refused("Sync can run every 5, 15 or 60 minutes") from None
    if minutes not in (5, 15, 60):
        raise repo.Refused("Sync can run every 5, 15 or 60 minutes")
    return minutes


def _same_address(root, settings, target):
    """Remote sync to exactly this address already, as the person confirmed it: a click that only changes how often
    chooses no address. An address settings.json names without that record is chosen again (signed)."""
    return settings["mode"] == "remote" and target == settings.get("remote") and cli.address_confirmed(root, target)


def set_where(root, settings, target, value, args):
    """Off, On this computer only, or an address (Also on another computer or server) every 5, 15 or 60 minutes.
    An address is the person's signed choice (sync:set-remote:<sha256(address)>, checked in cli.apply_set). A
    public address is not used yet: it waits, signed by this core, for the person's second signed choice
    (use-public) or Keep on this computer."""
    _person("chooses where sync keeps a copy")
    if target in ("off", "local"):
        settings, _ = cli.apply_set(root, settings, target)
        _forget_public(root)
        return {"mode": settings["mode"], "text": "Saved."}
    minutes = _interval(value)
    if not cli.remote_allowed():
        raise repo.Refused("Remote sync is preview-only")
    repo.validate_url(target)
    if _same_address(root, settings, target):  # only how often: unsigned
        settings, _ = cli.apply_set(root, settings, interval=minutes)
        return {"mode": settings["mode"], "remote": cli.safe_address(target), "interval": minutes, "text": "Saved."}
    try:
        settings, _ = cli.apply_set(root, settings, "remote", target, minutes, args=args)
    except cli.PublicAddress:
        # visibility probed just now (never a cached answer); the person chose this address (its proof), and that
        # it is public waits for their own choice
        by = humanproof.person_by(root, args, "addon.act", cli.remote_target(target),
                                  no_handoff="Choosing where sync keeps a copy needs a person's proof over stdin.")
        config.require_person(by, "choose where sync keeps a copy")
        _write_public(root, target, minutes)
        return {"mode": settings["mode"], "public": cli.safe_address(target),
                "text": "This sync address is public. Anyone can read your tickets."}
    _forget_public(root)
    return {"mode": settings["mode"], "remote": cli.safe_address(target), "interval": minutes, "text": "Saved."}


def _public_review(pending):
    return cli.remote_target(pending["remote"], public=True), {
        "title": "Use a public location?",
        "body": "Anyone who knows the address can read your tickets.",
        "value": _address(pending["remote"]),
    }


def use_public(root, settings, args):
    """The person's signed choice to sync to the public address anyway, bound to that exact address. The record is
    read ONCE, under the step lock: the proof's target and the address applied both come from that one read."""
    from .step import step_lock

    with step_lock(root):
        pending = pending_public(root)
        if pending is None:
            raise repo.Refused("No public address waits for a choice")
        remote = pending["remote"]
        settings, _ = cli.apply_set(root, settings, "remote", remote, _interval(pending["interval"]), args=args,
                                    public=True)
        _forget_public(root)
    return {"mode": settings["mode"], "remote": cli.safe_address(remote), "text": "Using the public location."}


def now(root, settings):
    """Sync now. It never clears a pause or a public address that waits: it says what still needs the person."""
    import time

    from . import loop, service
    from .pause import verified_pause

    if verified_pause(root, cli.read(root, "state")):
        n = max(_paused_needs(root), 1)
        return {"still_paused": n, "text": f"Still paused: {n} thing{'s' if n > 1 else ''} need{'' if n > 1 else 's'} you"}
    if pending_public(root):
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


def _held_review(root, target, kind):
    """allow / ignore: the target over the held value and that same value shown (clipped plain text, byte count)."""
    import hashlib

    from .approval import canonical, held

    tid, addon = _pair(target)
    found = [b for _, b in held(root, tid) if b["addon"] == addon]
    if len(found) != 1:
        raise repo.Refused("No single held change for this ticket and add-on")
    raw = canonical(found[0]["value"])  # the bytes approve() hashes
    name = plain(addon, 40)
    review = (
        {"title": f"Allow {name} to use this change on {tid}?", "body": "The change from the other computer is used here."}
        if kind == "allow"
        else {"title": f"Ignore this change of {name} on {tid}?", "body": "It is not used here. A different change asks again."}
    )
    review["value"] = f"{whole(raw.decode('utf-8', 'replace'))} ({len(raw)} bytes)"
    return f"sync:{kind}:{tid}:{addon}:{hashlib.sha256(raw).hexdigest()}", review


def _shown(doc, key):
    if key not in doc:
        return "(none)"
    v = doc[key]
    return whole(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)) or "(empty)"


def _side(path, doc, data, gone):
    """One side of a choice: a ticket's every differing key with its value (clipped); a file's size."""
    if data is None:
        return gone
    if paths.TICKET.fullmatch(path):
        return whole("; ".join(f"{whole(k)}: {_shown(doc[0], k)}" for k in doc[1])) or "No other change."
    if path == "ticket-counter.json":
        return f"{whole(data.decode('utf-8', 'replace'))} ({len(data)} bytes)"
    return f"{plain(Path(path).name, 120)}, {len(data)} bytes"


def _keep_review(path, keep, sides):
    from .needs import _doc

    _paused, _remote, mine, theirs = sides
    ticket = paths.TICKET.fullmatch(path)
    a, b = (_doc(mine), _doc(theirs)) if ticket else ({}, {})
    missing = object()
    keys = sorted((k for k in a.keys() | b.keys() if a.get(k, missing) != b.get(k, missing)), key=str)
    title = (a.get("title") or b.get("title")) if ticket else None
    name = plain(title, 80) if isinstance(title, str) and title.strip() else plain(Path(path).name, 120)
    review = (
        {"title": f"Keep your version of “{name}”?", "body": "The change from the other computer is set aside."}
        if keep == "mine"
        else {"title": f"Keep the other computer’s version of “{name}”?", "body": "The change made here is set aside."}
    )
    review["here"] = _side(path, (a, keys), mine, "Removed here.")
    review["there"] = _side(path, (b, keys), theirs, "Removed there.")
    return review


def _deleted_review(root, tid):
    """leave-deleted: the ticket's id and the title of the synced copy that would be left deleted (L4)."""
    from .needs import TID, _doc
    from .step import blob, entries

    deleted = cli.read(root, "state").get("deleted")
    if not TID.fullmatch(str(tid)) or not isinstance(deleted, dict) or tid not in deleted:
        raise repo.Refused("No missing ticket notice")
    old = entries(root, "HEAD").get(f"tickets/{tid}.json")
    if not old:
        raise repo.Refused("This ticket has no synced copy to leave deleted")
    title = _doc(blob(root, old)).get("title")
    shown = f"“{plain(title, 120)}” ({tid})" if isinstance(title, str) and title.strip() else tid
    return "sync:deleted:" + tid, {"title": "Leave this ticket deleted?",
                                    "body": "It is removed on every computer that syncs.", "value": shown}


REVIEW_TOTAL = 3800  # UTF-16 units of all shown review fields together (the dashboard shows 4000 per review)


def _units(text):
    return len(str(text).encode("utf-16-le")) // 2  # what the dashboard's JS .length counts


def proof_target(root, verb, target, value=None):
    """(target, review) of _proof_target, refused when the WHOLE review would not fit what the sign step shows
    (N-2: never a review the dashboard would clip; the person signs only what they see)."""
    target_out, review = _proof_target(root, verb, target, value)
    if review and sum(_units(v) for v in review.values() if isinstance(v, str)) > REVIEW_TOTAL:
        raise repo.Refused(TOO_LARGE)
    return target_out, review


def _proof_target(root, verb, target, value=None):
    """(target, review): the target the proof of this click must name (None when it needs none) and what the sign
    step shows (None when there is none), both from the same read of the same bytes the target hashes. Changes
    nothing."""
    from . import pause

    if verb in ("keep-mine", "keep-theirs"):
        keep = verb.removeprefix("keep-")
        sides = pause.resolve_sides(root, target)
        return pause.resolve_target(root, target, keep, sides), _keep_review(target, keep, sides)
    if verb == "leave-out":
        data = pause.left_bytes(root, target)
        name = plain(Path(target).name, 120)
        return pause.leave_out_target(root, target, data), {
            "title": f"Leave {name} out of sync?", "body": "It stays on this computer only.",
            "value": f"{name}, {len(data)} bytes"}
    if verb in ("allow", "ignore"):
        return _held_review(root, target, verb)
    if verb == "leave-deleted":
        return _deleted_review(root, target)
    if verb == "use-public":
        pending = pending_public(root)
        if pending is None:
            raise repo.Refused("No public address waits for a choice")
        return _public_review(pending)
    if verb == "set" and target not in ("off", "local"):
        repo.validate_url(target)
        minutes = _interval(value)
        if _same_address(root, cli.DEFAULTS | cli.read(root, "settings"), target):
            return None, None
        return cli.remote_target(target), {
            "title": "Sync to this address?",
            "body": f"Your tickets and their files are copied there every {minutes} minutes.",
            "value": _address(target)}
    return None, None


def act(root, settings, args):
    verb, target = args.verb, args.target
    if args.proof_target:
        signed, review = proof_target(root, verb, target, args.value)
        return {"target": signed, **({"review": review} if review else {})}
    if verb == "status":
        return status(root, settings)
    if verb == "check":
        return check(root, target)
    if verb == "set":
        return set_where(root, settings, target, args.value, args)
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
