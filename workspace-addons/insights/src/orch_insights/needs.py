"""`orch insights needs --json`: rows for `orch needs` (contracts/needs.schema.json). One row while the check-up has
suggestions nobody has looked at (proposed or tested); nothing otherwise, and nothing when the CLI fails."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from .checkup import build_checkup
from .server import read_json


def rows(root: Path, orch_bin=None, now: datetime | None = None) -> list[dict]:
    view = build_checkup(read_json(root, orch_bin, ["checkup", "list", "--json"]))
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
            "title": "Check-up",
            "text": f"Check-up has {n} suggestion{'s' if n != 1 else ''} to look at",
            "tone": "warn",
            "since": since,
            "cli": "orch insights open",
        }
    ]


def from_env(root: Path) -> list[dict]:
    return rows(root, os.environ.get("ORCH_BIN") or None)
