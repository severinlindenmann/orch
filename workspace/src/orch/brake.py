"""The runaway brake (R8.6): `orch pause` stops all automation in this workspace, and automatic starts have a
default cap per ticket. A person's own start is never held back, never counted."""

from __future__ import annotations

import contextlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from orch import tickets
from orch.errors import Refused

CAP_PER_DAY = 20  # automatic starts per ticket in a rolling 24 hours (a default, not a setting)
WINDOW = 24 * 3600

PAUSED_REFUSAL = "Automation is paused in this workspace. Turn it back on with: orch resume."


def _dir(root: Path) -> Path:
    return root / ".orch" / "run"


def _paused_path(root: Path) -> Path:
    return _dir(root) / "paused.json"


def _starts_path(root: Path) -> Path:
    return _dir(root) / "starts.json"


def _write(path: Path, data) -> None:
    from orch import runs

    runs._atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def paused(root: Path) -> dict | None:
    """The pause record ({by, at}) while automation is paused, else None."""
    d = _read(_paused_path(root))
    return d if isinstance(d, dict) else None


def pause(root: Path, by: str) -> dict:
    rec = paused(root)
    if rec is None:
        rec = {"by": by, "at": datetime.now(UTC).isoformat(timespec="seconds")}
        _write(_paused_path(root), rec)
    return rec


def resume(root: Path) -> bool:
    """Clear the pause; True when it was paused."""
    was = paused(root) is not None
    _paused_path(root).unlink(missing_ok=True)
    return was


def is_person(by: str) -> bool:
    return tickets._is_person(by)  # the one person check: human:<name> and no agent tool in the environment


def check_start(root: Path, tid: str, by: str) -> None:
    """Called by runs.start before anything is planned: refuse an automatic start while paused or over the
    cap; count an automatic start that goes ahead. A person's start passes untouched."""
    if is_person(by):
        return
    if paused(root) is not None:
        raise Refused(PAUSED_REFUSAL)
    now = time.time()
    data = _read(_starts_path(root))
    data = data if isinstance(data, dict) else {}
    starts = data.get("starts") if isinstance(data.get("starts"), dict) else {}
    capped = data.get("capped") if isinstance(data.get("capped"), dict) else {}
    starts = {
        t: [x for x in v if isinstance(x, (int, float)) and now - x < WINDOW]
        for t, v in starts.items()
        if isinstance(v, list)
    }
    capped = {t: x for t, x in capped.items() if isinstance(x, (int, float)) and now - x < WINDOW}
    mine = starts.get(tid, [])
    if len(mine) >= CAP_PER_DAY:
        msg = (
            f"This ticket already ran {CAP_PER_DAY} times on its own today; "
            "start it yourself or wait until tomorrow."
        )
        if tid not in capped:  # one history line the first time the cap is hit
            capped[tid] = now
            _write(_starts_path(root), {"starts": starts, "capped": capped})
            with contextlib.suppress(Exception):
                tickets.log(root, tid, msg, "agent:automation")
        raise Refused(msg)
    starts[tid] = [*mine, now]
    _write(_starts_path(root), {"starts": starts, "capped": capped})
