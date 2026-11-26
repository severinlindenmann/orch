"""`orch focus needs --json`: rows for `orch needs` (needs.schema.json): a live helper that waits for the person's
OK on its screen (the tool's Notification hook sets the run's live state to attention). Read from core's run claim
records; nothing here writes or starts anything."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

TID = re.compile(r"t_[a-z0-9]{6,16}")
MAX_ROWS = 200  # a cap on the rows returned, never on the run records read: a waiting helper is never cut off


def _title(t: dict) -> str:
    return (str(t.get("title") or "A ticket").replace("<", "").replace(">", "").strip() or "A ticket")[:200]


def rows(root: Path, now: datetime | None = None) -> list[dict]:
    return scan(root, now)[0]


def scan(root: Path, now: datetime | None = None) -> tuple[list[dict], int]:
    """(the eligible rows, the number of run records read). Every record is read (one small JSON file each);
    a ticket file is opened only for a record that is live, waiting and alive."""
    from orch import runs, tickets

    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = runs.run_dir(root) / "tickets"
    if d.is_symlink() or not d.is_dir():
        return [], 0
    out: list[dict] = []
    scanned = 0
    for f in sorted(d.glob("t_*.json")):
        if not TID.fullmatch(f.stem) or f.is_symlink():
            continue
        scanned += 1
        rec = runs.read(root, f.stem)
        live = (rec or {}).get("live")
        live = live if isinstance(live, dict) else {}  # a hand-edited claim file must not break every row
        if (
            not rec
            or rec.get("mode") != "live"
            or live.get("state") != "attention"
            or runs.state(rec) != "alive"
        ):
            continue
        try:
            t = tickets.load(root, f.stem)
        except Exception:  # noqa: BLE001, S112 - a broken ticket file must not hide the other rows
            continue
        if t.get("general") is True or t.get("manager") is True:
            continue  # the hidden phone conversation and the Manager have their own place
        out.append(
            {
                "id": f"focus:waiting-{f.stem}",
                "source": "focus",
                "kind": "focus:waiting",
                "ticket": f.stem,
                "title": _title(t),
                "text": str(live.get("why") or "Waiting for your OK in the live session.")[:400],
                "tone": "needs-you",
                "since": str(live.get("since") or rec.get("renewed_at") or stamp),
                "cli": f"orch focus open {f.stem}",
            }
        )
        if len(out) >= MAX_ROWS:
            break
    return out, scanned
