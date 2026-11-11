"""Plain Needs rows consumed by the core's existing add-on collector."""

import hashlib
import shlex
from datetime import UTC, datetime
from pathlib import Path

from . import approval, cli


def row(kind, key, text, since, command, options, ticket=None, title="Sync needs you"):
    return {
        "id": f"sync:{kind}:{key}",
        "source": "sync",
        "kind": f"sync:{kind}",
        "ticket": ticket,
        "title": title[:200],
        "text": text[:500],
        "tone": "needs-you",
        "since": since,
        "answer": {"question": "q1", "options": options, "recommended": None},
        "cli": command[:300],
    }


def rows(root):
    state = cli.read(root, "state")
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    out = []
    paused = state.get("paused")
    if paused:
        if not paused["files"]:
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
        for path in paused["files"]:
            key = hashlib.sha256(path.encode()).hexdigest()[:24]
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
                    f"orch sync resolve {shlex.quote(path)} --keep mine|theirs",
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
    for _, block in approval.held(root):
        grouped.setdefault(block["ticket"], []).append(block["addon"])
        dates[block["ticket"]] = min(dates.get(block["ticket"], now), block.get("since", now))
    for tid, names in grouped.items():
        out.append(
            row(
                "held",
                tid,
                f"A synced ticket wants {', '.join(sorted(names))} to run something. Allow?",
                dates[tid],
                f"orch sync approve {tid} {min(names)}",
                ["Allow", "Ignore"],
                ticket=tid,
            )
        )
    for tid, since in state.get("deleted", {}).items():
        out.append(
            row(
                "deleted",
                tid,
                f"A ticket file is missing: {tid}. Restored it.",
                since,
                f"orch sync deleted {tid} --keep",
                ["Leave deleted", "OK"],
                ticket=tid,
            )
        )
    return out
