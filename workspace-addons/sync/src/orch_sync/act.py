"""`orch sync act <verb> [--value V] -- <target>`: what the dashboard's Sync card and Needs rows do, through the
dashboard's ONE generic add-on op (`orch <addon> act <verb> -- <target>`).

The address and the choice come from the person's click in the local dashboard. The verbs run plain, as
`resolve`, `approve` and `deleted` do. Reading verbs (status, check) change nothing.
"""

import tempfile
import unicodedata
from pathlib import Path

from . import cli, history, paths, repo

# Needs rows that are part of a pause: Sync now never clears them (the card says "Still paused: N things need you").
PAUSE_KINDS = ("sync:paused", "sync:secret", "sync:key-clash", "sync:case", "sync:history")
WHY = {
    "File exceeds 25 MB": "too big, stays on this computer",
    "busy": "in use, sync tries again",
    "the local file cannot be synced; it was kept as it is": "stays on this computer",
}
SECRET_WHY = "may contain a password or access key"
PUBLIC = "pending-public"  # run/sync/pending-public.json: a public address waiting for the person's choice
NO_ADDRESS = "Sync can't use this address: https or ssh, without a password"
# what a page never shows as such: decided by Unicode category, not by a list that has gaps: control (Cc), format
# (Cf: bidi, zero-width, soft hyphen, tag characters), private use, surrogate, unassigned, line and paragraph
# separators; plus the Hangul fillers (blank letters) and every variation selector (they change nothing visible).
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp"})
_BLANK_LETTERS = frozenset("\u115f\u1160\u3164\uffa0")
_VARIATION_SELECTORS = ((0x180B, 0x180D), (0x180F, 0x180F), (0xFE00, 0xFE0F), (0xE0100, 0xE01EF))


def hidden_char(c):
    """True for a character a page must never show as such (it is shown as U+FFFD)."""
    cp = ord(c)
    return (
        unicodedata.category(c) in _HIDDEN_CATEGORIES
        or c in _BLANK_LETTERS
        or any(lo <= cp <= hi for lo, hi in _VARIATION_SELECTORS)
    )


def _visible(value):
    """`value` as one line, whitespace collapsed, every hidden character replaced by U+FFFD."""
    return "".join("\ufffd" if hidden_char(c) else c for c in " ".join(str(value).split()))


def plain(value, limit=200):
    """Text from a peer, a file or the agent as one clipped plain line: whitespace collapsed, every control, bidi
    or zero-width character shown as U+FFFD (never hidden), at most `limit` characters."""
    text = _visible(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


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
    """The public address that waits for the person's choice ({remote, interval}), read once. A record of any
    other shape counts as absent everywhere (status, use-public, Sync now). An old record with a mac field
    loads as before (the field is ignored)."""
    try:
        data = cli.read(root, PUBLIC)
    except (ValueError, OSError, RecursionError):
        return None
    body = {k: v for k, v in data.items() if k != "mac"}
    if set(body) != {"remote", "interval"} or not isinstance(body["remote"], str):
        return None
    return body


def _write_public(root, remote, minutes):
    from .step import encoded, write

    write(root, f"run/sync/{PUBLIC}.json", encoded({"remote": remote, "interval": minutes}))


def _forget_public(root):
    repo.safe(root, f"run/sync/{PUBLIC}.json").unlink(missing_ok=True)


def status(root, settings):
    """The status line and facts of the Sync card (status --json plus what the card shows)."""
    result = cli.status_result(root, settings)
    state = result["state"]
    shown = (
        "off"
        if settings["mode"] == "off"
        else "syncing"
        if _syncing(root)
        else "paused"
        if result["paused"]
        else "offline"
        if result["last_error"] == "offline"
        else "synced"
        if result["last_ok"]
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
        "next_run": result["next_run"],
        "folder": Path(root).name[:80],
        "counts": _counts(root),
        "history": history.read(root),
    }


def _counts(root):
    """{tickets, files, bytes} of what the last sync keeps (the committed tree); zeros before the first one."""
    out = {"tickets": 0, "files": 0, "bytes": 0}
    try:
        raw = repo.git(root, "ls-tree", "-r", "-l", "-z", "HEAD", allowed_codes=(0, 128)).stdout
    except (repo.Refused, OSError, ValueError):
        return out
    for row in raw.split(b"\0"):
        meta, _, name = row.partition(b"\t")
        parts = meta.split()
        if len(parts) < 4 or not parts[3].isdigit():
            continue
        path = name.decode("utf-8", "replace")
        if paths.TICKET.fullmatch(path):
            out["tickets"] += 1
        elif paths.ARTIFACT.fullmatch(path):
            out["files"] += 1
        else:
            continue
        out["bytes"] += int(parts[3])
    return out


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
    chooses no address. An address settings.json names without that record is chosen again."""
    return (
        settings["mode"] == "remote"
        and target == settings.get("remote")
        and cli.address_confirmed(root, target)
    )


def set_where(root, settings, target, value, args):
    """Off, On this computer only, or an address (Also on another computer or server) every 5, 15 or 60 minutes.
    An address is the person's choice (recorded in cli.apply_set). A public address is not used yet: it waits
    for the person's second choice (use-public) or Keep on this computer."""
    if target in ("off", "local"):
        settings, _ = cli.apply_set(root, settings, target)
        _forget_public(root)
        return {"mode": settings["mode"], "text": "Saved."}
    minutes = _interval(value)
    if not cli.remote_allowed():
        raise repo.Refused("Remote sync is preview-only")
    repo.validate_url(target)
    if _same_address(root, settings, target):  # only how often
        settings, _ = cli.apply_set(root, settings, interval=minutes)
        return {
            "mode": settings["mode"],
            "remote": cli.safe_address(target),
            "interval": minutes,
            "text": "Saved.",
        }
    try:
        settings, _ = cli.apply_set(root, settings, "remote", target, minutes, args=args)
    except cli.PublicAddress:
        # visibility probed just now (never a cached answer); that it is public waits for their own choice
        _write_public(root, target, minutes)
        return {
            "mode": settings["mode"],
            "public": cli.safe_address(target),
            "text": "This sync address is public. Anyone can read your tickets.",
        }
    _forget_public(root)
    return {
        "mode": settings["mode"],
        "remote": cli.safe_address(target),
        "interval": minutes,
        "text": "Saved.",
    }


def use_public(root, settings, args):
    """The person's choice to sync to the public address anyway. The record is read ONCE, under the step lock."""
    from .step import step_lock

    with step_lock(root):
        pending = pending_public(root)
        if pending is None:
            raise repo.Refused("No public address waits for a choice")
        remote = pending["remote"]
        settings, _ = cli.apply_set(
            root, settings, "remote", remote, _interval(pending["interval"]), args=args, public=True
        )
        _forget_public(root)
    return {
        "mode": settings["mode"],
        "remote": cli.safe_address(remote),
        "text": "Using the public location.",
    }


def now(root, settings):
    """Sync now. It never clears a pause or a public address that waits: it says what still needs the person."""
    import time

    from . import loop, service
    from .pause import verified_pause

    if verified_pause(root, cli.read(root, "state")):
        n = max(_paused_needs(root), 1)
        return {
            "still_paused": n,
            "text": f"Still paused: {n} thing{'s' if n > 1 else ''} need{'' if n > 1 else 's'} you",
        }
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


def act(root, settings, args):
    verb, target = args.verb, args.target
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
        return {
            "paused": bool(result.get("paused")),
            "text": "Kept your version." if verb == "keep-mine" else "Kept the other version.",
        }
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
