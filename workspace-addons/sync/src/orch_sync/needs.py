"""Plain Needs rows consumed by the core's existing add-on collector."""

import hashlib
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path

from . import approval, cli


def row(kind, key, text, since, command, options, ticket=None, title="Sync needs you", tone="needs-you"):
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
    return out


TID = re.compile(r"t_[a-z0-9]{6,16}")


def _ticket_of(path):
    parts = path.split("/")
    tid = parts[1].removesuffix(".json") if len(parts) > 1 and parts[0] == "tickets" else None
    return tid if tid and TID.fullmatch(tid) else None


def rows(root):
    state = cli.read(root, "state")
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    out = []
    paused = state.get("paused")
    if paused:
        if paused.get("kind") == "history":
            # no file to choose; the pause clears by itself when the other computer's history changes
            out.append(
                row(
                    "history",
                    "state",
                    "Sync paused: the histories of the two computers cannot be combined automatically. Your "
                    "files stay as they are. Sync goes on by itself once the other computer sends a change.",
                    paused["since"],
                    "orch sync status --json",
                    None,
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
            text = (
                f"Not synced: {path} looks like it contains a secret."
                if secret
                else f'Sync paused: "{Path(path).name}" needs your choice. Both copies are kept.'
            )
            if "Many files" in reason:
                text = reason + " Keep files to preserve every copy."
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
    for _, block in approval.held(root, waiting=True):
        grouped.setdefault(block["ticket"], []).append(block["addon"])
        dates[block["ticket"]] = min(dates.get(block["ticket"], now), block.get("since", now))
    for tid, names in grouped.items():
        out.append(
            row(
                "held",
                tid,
                f"A synced ticket wants {', '.join(sorted(names))} to run something. Allow?",
                dates[tid],
                f"orch sync approve {shlex.quote(tid)} {shlex.quote(min(names))}",
                ["Allow", "Ignore"],
                ticket=tid,
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
            )
        )
    return out
