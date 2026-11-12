"""Plain Needs rows consumed by the core's existing add-on collector."""

import hashlib
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path

from . import approval, cli, paths, pause


def action(label, verb=None, target=None, *, sign=False, review=None, op=None, later=False, view=None):
    """One button of a row for the dashboard (`orch sync act <verb> -- <target>`, or a core op it already has).
    sign = the click goes through the person's sign step; review = what that step shows (plain text)."""
    out = {"label": label}
    if verb:
        out.update(verb=verb, target=target)
    if op:
        out["op"] = op
    if sign:
        out["sign"] = True
    if review:
        out["review"] = {k: str(v)[:400] for k, v in review.items() if v}
    if later:
        out["later"] = True
    if view:
        out["view"] = view
    return out


FIELDS = (("title", "Title"), ("status", "Status"), ("due", "Due"), ("owner", "Owner"), ("note", "Note"),
          ("done_when", "Done when"), ("summary", "Summary"))


def _doc(data):
    import json

    try:
        doc = json.loads(data) if data else {}
    except (ValueError, RecursionError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _sides(root, path):
    """(title, here, there): a ticket's title and, per side, the fields that differ between the two copies."""
    from . import repo, step

    try:
        live = repo.safe(root, path)
        mine = live.read_bytes() if live.is_file() else step.blob(root, step.entries(root, "HEAD").get(path))
        saved = repo.safe(root, "run/sync/theirs/" + path)
        theirs = saved.read_bytes() if saved.is_file() else None
    except Exception:  # noqa: BLE001 - only the wording suffers: the row still shows
        return None, "", ""
    if not paths.TICKET.fullmatch(path):
        return None, "Changed on this computer." if mine else "Removed here.", "Changed on the other computer." if theirs else "Removed there."
    a, b = _doc(mine), _doc(theirs)
    def clip(v):
        return " ".join(str(v).split())[:60] if v not in (None, "") else "empty"

    diff = [(label, a.get(k), b.get(k)) for k, label in FIELDS if a.get(k) != b.get(k)]
    here = "; ".join(f"{label}: {clip(x)}" for label, x, _ in diff[:3]) or ("Other changes." if mine else "Removed here.")
    there = "; ".join(f"{label}: {clip(y)}" for label, _, y in diff[:3]) or ("Other changes." if theirs else "Removed there.")
    title = a.get("title") or b.get("title")
    return (str(title)[:80] if isinstance(title, str) and title.strip() else None), here, there


def _needs_move(root):
    """True when this workspace's orch files are kept in the team repository (sync can't start then)."""
    from . import repo

    try:
        return not repo.safe(root, ".git").exists() and repo.state(root) == "needs-move"
    except Exception:  # noqa: BLE001 - no row rather than a wrong one
        return False


def _unconfirmed(root):
    """Remote mode with an address the person did not confirm (cli.address_confirmed): sync makes no network call."""
    try:
        settings = cli.DEFAULTS | cli.read(root, "settings")
    except Exception:  # noqa: BLE001 - no row rather than a wrong one (the step reports the bad file)
        return False
    return settings.get("mode") == "remote" and not cli.address_confirmed(root, settings.get("remote"))


def row(kind, key, text, since, command, options, ticket=None, title="Sync needs you", tone="needs-you", actions=None):
    out = {
        "id": f"sync:{kind}:{key}",
        "source": "sync",
        "kind": f"sync:{kind}",
        "ticket": ticket,
        "title": title[:200],
        "text": text[:500],
        "tone": tone,
        "since": since,
        "answer": {"question": "q1", "options": options, "recommended": None},
        "cli": command[:300],
    }
    if options is None:  # nothing to answer: a notice the person sees until it clears
        del out["answer"]
    if actions:
        out["actions"] = actions
    return out


TID = re.compile(r"t_[a-z0-9]{6,16}")
ADDON = re.compile(r"[a-z][a-z0-9-]{0,31}")


def _ticket_of(path):
    parts = path.split("/")
    tid = parts[1].removesuffix(".json") if len(parts) > 1 and parts[0] == "tickets" else None
    return tid if tid and TID.fullmatch(tid) else None


def rows(root):
    state = cli.read(root, "state")
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    out = []
    paused = pause.verified_pause(root, state)  # an edited or planted pause shows nothing
    if paused:
        if paused.get("kind") == "history":
            # no file to choose: take the other computer's history (a person's proof), or it clears by itself
            out.append(
                row(
                    "history",
                    "state",
                    "Sync paused: the histories of the two computers cannot be combined automatically. Your "
                    "files stay as they are. Take the other computer's copy (Done, ticket numbers and add-on "
                    "changes are still checked here; files only you have stay), or wait for its next change.",
                    paused["since"],
                    "orch sync take-remote --proof-stdin",
                    ["Take theirs", "Wait"],
                    tone="warn",
                )
            )
        elif not paused["files"]:
            out.append(
                row(
                    "paused",
                    "state",
                    "Sync paused: the incoming files could not be accepted.",
                    paused["since"],
                    "orch sync status --json",
                    ["Check address", "Stop sync"],
                )
            )
        clash_paths = set()
        for key, candidates in sorted(paused.get("key_clashes", {}).items()):
            clash_paths.update(f"tickets/{t['id']}.json" for t in candidates)
            out.append(
                row(
                    "key-clash",
                    key,
                    f"Two tickets have the same number {key}. Which keeps it?",
                    paused["since"],
                    f"orch sync keep-key {shlex.quote(key)} <ticket-id> --proof-stdin",
                    (
                        [f"{t['title'][:77 - len(t['id'])]} ({t['id']})" for t in candidates]
                        if len(candidates) <= 8
                        else []
                    ),
                    title=key,
                )
            )
        case = paused.get("case_names") if isinstance(paused.get("case_names"), dict) else {}
        for path in paused["files"]:
            if path in clash_paths:
                continue
            key = hashlib.sha256(path.encode()).hexdigest()[:24]
            if isinstance(case.get(path), str):
                out.append(
                    row(
                        "case",
                        key,
                        f'"{Path(path).name}" from the other computer has the same name as your '
                        f'"{Path(case[path]).name}" except for capital letters. Keep your name, or rename '
                        "your file?",
                        paused["since"],
                        f"orch sync resolve {shlex.quote(path)} --keep-local-name --proof-stdin "
                        "(or --rename-local <new name> --proof-stdin)",
                        ["Keep my name", "Rename my file"],
                        title=Path(path).name,
                    )
                )
                continue
            reason = paused["reason"]
            secret = "secret" in reason
            name, here, there = _sides(root, path) if not secret else (None, "", "")
            name = name or Path(path).name
            text = (
                f"Not synced: {Path(path).name} may contain a password or access key."
                if secret
                else f"Sync paused: “{name}” changed here and on another computer."
            )
            if "Many files" in reason:
                text = reason + " Keep files to preserve every copy."
            if reason == pause.JUMP and path == "ticket-counter.json":
                # LOW-5: either choice lets the far-numbered tickets you reviewed arrive; only the counter differs.
                text = (
                    f"{reason}. Keep mine keeps your counter, Keep theirs takes theirs; either way the tickets "
                    "with the far numbers arrive."
                )
            if secret:
                art = paths.ARTIFACT.fullmatch(path)
                acts = [
                    action("Leave it out", "leave-out", path, sign=True, review={
                        "title": f"Leave {Path(path).name} out of sync?", "body": "It stays on this computer only.",
                        "done": "Left out. It stays on this computer."}) if art else None,
                    action("View file", view={"ticket": path.split("/")[1], "name": path.split("/artifacts/", 1)[-1]})
                    if art else None,
                ]
            else:
                acts = [
                    action("Keep mine", "keep-mine", path, sign=True, review={
                        "title": f"Keep your version of “{name}”?", "body": "The change from the other computer is set aside.",
                        "here": here, "there": there, "done": "Kept your version."}),
                    action("Keep theirs", "keep-theirs", path, sign=True, review={
                        "title": f"Keep the other computer’s version of “{name}”?", "body": "The change made here is set aside.",
                        "here": here, "there": there, "done": "Kept the other version."}),
                ]
            out.append(
                row(
                    "secret" if secret else "paused",
                    key,
                    text,
                    paused["since"],
                    f"orch sync resolve {shlex.quote(path)} --keep mine|theirs"
                    + (" --proof-stdin" if path == "ticket-counter.json" else ""),
                    ["Keep mine", "Keep theirs"],
                    title=Path(path).name,
                    actions=[a for a in acts if a],
                )
            )
        if (datetime.now(UTC) - datetime.fromisoformat(paused["since"])).days >= 7:
            out.append(
                row(
                    "paused",
                    "week",
                    "Sync has been paused for 7 days.",
                    paused["since"],
                    "orch sync needs --json",
                    ["Review files"],
                )
            )
    grouped, dates = {}, {}
    for _, block in approval.held(root):
        grouped.setdefault(block["ticket"], []).append(block["addon"])
        dates[block["ticket"]] = min(dates.get(block["ticket"], now), block.get("since", now))
    installed = approval.manifests()
    for tid, names in grouped.items():
        # LOW-7: an add-on name from the other computer is shown only when it is an installed add-on's
        # (never free text from the peer in a person's row or an agent's --json)
        shown = sorted({n if n in installed and ADDON.fullmatch(n) else "an add-on not installed here" for n in names})
        first = min((n for n in names if n in installed and ADDON.fullmatch(n)), default=None)
        out.append(
            row(
                "held",
                tid,
                f"A synced ticket wants {', '.join(shown)} to run something. Allow?",
                dates[tid],
                f"orch sync approve {shlex.quote(tid)} {shlex.quote(first)}" if first else "orch sync needs --json",
                ["Allow", "Ignore"] if first else None,
                ticket=tid,
                actions=[
                    action("Allow", "allow", f"{tid}:{first}", sign=True, review={
                        "title": f"Allow {first} to run something on this ticket?",
                        "body": "The change from the other computer is used here.", "done": "Allowed."}),
                    action("Ignore", "ignore", f"{tid}:{first}", sign=True, review={
                        "title": f"Ignore this change of {first}?",
                        "body": "It is not used here. A different change asks again.", "done": "Ignored."}),
                ] if first else None,
            )
        )
    # Fable A2: a path that could not be applied this tick (the local file is kept as it is). Until it applies.
    unapplied = state.get("unapplied") if isinstance(state.get("unapplied"), dict) else {}
    for path, since in sorted(unapplied.items()):
        if not isinstance(path, str) or not isinstance(since, str):
            continue
        out.append(
            row(
                "unapplied",
                hashlib.sha256(path.encode()).hexdigest()[:24],
                f"A file couldn't be updated: {Path(path).name}. orch will try again.",
                since,
                "orch sync status --json",
                None,
                ticket=_ticket_of(path),
                title=Path(path).name or "Sync",
                tone="warn",
            )
        )
    for tid, since in state.get("deleted", {}).items():
        out.append(
            row(
                "deleted",
                tid,
                f"A ticket file is missing: {tid}. Restored it.",
                since,
                f"orch sync deleted {shlex.quote(tid)} --keep",
                ["Leave deleted", "OK"],
                ticket=tid,
                actions=[
                    action("Leave deleted", "leave-deleted", tid, sign=True, review={
                        "title": "Leave this ticket deleted?",
                        "body": "It is removed on every computer that syncs.", "done": "Left deleted."}),
                    action("OK", "restored", tid),
                ],
            )
        )
    if _unconfirmed(root):
        out.append(
            row(
                "address",
                "remote",
                cli.UNCONFIRMED,
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "orch sync set --mode remote --remote <address> --proof-stdin",
                None,
                title="Sync",
                tone="warn",
            )
        )
    if _needs_move(root):
        out.append(
            row(
                "move",
                "orch-files",
                "Move your orch files out of the team repository?",
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "orch private move",
                None,
                title="Sync",
                actions=[
                    action("Move", op="private.move", sign=True, review={
                        "title": "Move your orch files out of the team repository?",
                        "body": "Why: your tickets sit in your team’s repository, so everyone on the team sees each "
                                "change. Where: they stay in this folder on this computer; the team repository no "
                                "longer keeps them. Your team’s files are not touched.",
                        "done": "Moved your orch files."}),
                    action("Not now", later=True),
                ],
            )
        )
    return out
