"""Hand-offs: a command in a terminal asked for a human-only action without a proof (H1). The core queued an
item; this page shows it as "Requested by a command" with the full text, and ONE plain click mints the proof
and runs the command the core stored. The launch token is never involved here and never shown."""

from __future__ import annotations

import subprocess
from pathlib import Path

try:
    from orch import humanproof
    from orch.pageproof import run_with_proof
except ImportError:  # standalone use without orch: no hand-offs
    humanproof = None
    run_with_proof = None

SHOW = ("id", "op", "target", "label", "value", "at")


def listing(root: Path) -> list[dict]:
    """What the page may show: no command line, no token."""
    if humanproof is None:
        return []
    return [{k: i.get(k) for k in SHOW} for i in humanproof.handoffs(root)][:12]


def notices(root: Path) -> list[dict]:
    """One-time notices from the core (e.g. protection was reset), read once: the text is the core's own."""
    if humanproof is None:
        return []
    return [
        {"kind": str(n.get("kind"))[:40], "text": str(n.get("text"))[:600]}
        for n in humanproof.take_notices(root)
    ][:5]


def confirm(root: Path, orch_bin, mint, hid, env, run_proof=None) -> tuple[int, str]:
    """The person clicked Continue. mint(op, target) exists only for a request with a page session."""
    if humanproof is None or mint is None:
        return 403, "Open the dashboard from this computer to do this."
    item = humanproof.handoff_take(root, hid) if isinstance(hid, str) else None
    if item is None:
        return 404, "That request is gone. Ask again from the terminal."
    run = run_proof or run_with_proof
    try:
        r = run(
            item["argv"], mint(item["op"], item["target"]), orch_bin=orch_bin, cwd=root, env=env, timeout=60
        )
    except (subprocess.TimeoutExpired, OSError):
        return 504, "That took too long. Please try again from the terminal."
    if r.returncode == 0:
        return 200, ""
    msg = (r.stderr.strip().splitlines() or ["That did not work."])[0].removeprefix("Refused: ")
    return 422, msg[:300]


def dismiss(root: Path, hid) -> None:
    if humanproof is not None and isinstance(hid, str):
        humanproof.handoff_drop(root, hid)
