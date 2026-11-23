"""`orch insights needs --json`: rows for `orch needs` (contracts/needs.schema.json). One row while the check-up has
proposals nobody has looked at (proposed or tested); nothing otherwise, and nothing when they cannot be read.
Read from the add-on's own files in this process: `orch needs` asks every add-on and waits for each (ORCH-603)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .checkup import build_checkup
from .server import read_json


def _own_listing(root: Path) -> dict | None:
    """The check-up listing from this add-on's own files, in this process (ORCH-603: no second orch)."""
    from . import checkup_core

    try:
        return checkup_core.listing(root, light=True)
    except Exception:  # noqa: BLE001 - an unreadable check-up file is "nothing to show", never an error
        return None


def rows(root: Path, orch_bin=None, now: datetime | None = None) -> list[dict]:
    """`orch_bin`: read the listing through that orch (the page's way); None: from the own files."""
    raw = (
        read_json(root, orch_bin, ["insights", "checkup", "list", "--json"])
        if orch_bin is not None
        else _own_listing(root)
    )
    view = build_checkup(raw)
    if not view["available"]:
        return []
    open_ones = [p for p in view["proposals"] if p["status"] in ("proposed", "tested")]
    if not open_ones:
        return []
    n = len(open_ones)
    since = (view["last"] or {}).get("at") or (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [
        {
            "id": "insights:checkup",
            "source": "insights",
            "kind": "insights:checkup",
            "ticket": None,
            "title": "Health check",
            "text": f"Health check has {n} proposal{'s' if n != 1 else ''} to look at",
            "tone": "warn",
            "since": since,
            "cli": "orch insights open",
        }
    ]


def from_env(root: Path) -> list[dict]:
    return rows(root)
