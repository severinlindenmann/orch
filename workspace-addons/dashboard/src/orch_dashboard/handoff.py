"""Hand-offs: a command in a terminal asked for a human-only action without a proof (H1). The core queued an
item; this page shows it as "Requested by a command" with the full text, and ONE plain click mints the proof
and runs the command the core stored. The launch token is never involved here and never shown."""

from __future__ import annotations

import subprocess
from pathlib import Path

try:
    from orch import humanproof
    from orch.pageproof import run_with_proof, start_detached
except ImportError:  # standalone use without orch: no hand-offs
    humanproof = None
    run_with_proof = None
    start_detached = None

SHOW = ("id", "op", "target", "parts", "value", "exact", "at")


def listing(root: Path) -> list[dict]:
    """What the page may show: no command line, no token."""
    if humanproof is None:
        return []
    return [{k: i.get(k) for k in SHOW} for i in humanproof.handoffs(root)][:12]


def notices(root: Path) -> list[dict]:
    """Notices from the core (e.g. protection was reset): the core's own text, read-only."""
    if humanproof is None:
        return []
    return humanproof.read_notices(root)[:5]  # reading never clears: only "Got it" does (ack_notice)


def confirm(
    root: Path, orch_bin, mint, hid, env, run_proof=None, session=None, start=None
) -> tuple[int, str]:
    """The person clicked Continue. mint(op, target) exists only for a request with a page session."""
    if humanproof is None or mint is None:
        return 403, "Open the dashboard from this computer to do this."
    item = humanproof.handoff_take(root, hid) if isinstance(hid, str) else None
    if item is None:
        return 404, "That request is gone. Ask again from the terminal."
    if item["op"] == "update":
        # an update restarts this server: run it detached with no timeout, answer the click at once, and let the
        # restarted server adopt this page's session so the open tab keeps working
        if session is not None:
            humanproof.write_resume_cookie(root, session.server, session.cookie, session.secret)
        try:
            pid = (start or start_detached)(
                item["argv"], mint(item["op"], item["target"]), orch_bin=orch_bin, cwd=root, env=env
            )
        except OSError:
            return 503, "The update could not be started. Please try again from the terminal."
        _record_update(root, pid)
        return 202, "Update started. This page reconnects when it is done."
    if item["op"] == "addon.add_local" and session is not None:  # it restarts this server like an update
        humanproof.write_resume_cookie(root, session.server, session.cookie, session.secret)
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


def start_update(root: Path, orch_bin, mint, env, session=None, start=None) -> tuple[int, str]:
    """The person clicked Update in Settings (About & updates): the same detached update as Continue on a request
    from the terminal, for the source this install updates from. mint(op, target) exists only for a page with
    a session (a curl or an agent gets 403)."""
    if humanproof is None or mint is None:
        return 403, "Open the dashboard from this computer to do this."
    try:
        from orch import addons

        target = humanproof.update_target(addons.repo(), addons.ref())
    except Exception:  # noqa: BLE001 - e.g. a source name orch refuses
        return 422, "orch cannot find where to update from."
    if session is not None:
        humanproof.write_resume_cookie(root, session.server, session.cookie, session.secret)
    try:
        pid = (start or start_detached)(
            ["update"], mint("update", target), orch_bin=orch_bin, cwd=root, env=env
        )
    except OSError:
        return 503, "The update could not be started. Please try again."
    _record_update(root, pid)
    return 202, "Update started. This page reconnects when it is done."


def update_info() -> dict:
    """Installed and newest version with what changed (plain words, cached by orch for 10 minutes)."""
    try:
        from orch import addons, updateinfo

        data = dict(updateinfo.info())
        data["source"] = f"{addons.repo()} ({addons.ref()})"[:200]
        return data
    except Exception:  # noqa: BLE001 - never an error page for a version line
        return {}


def _record_update(root: Path, pid: int) -> None:
    """The detached update's pid, kept in the add-on's run folder (display and cleanup only)."""
    try:
        from . import runfiles

        runfiles.write_json(runfiles.run_dir(root, "dashboard") / "update.json", {"pid": pid})
    except (OSError, RuntimeError, ImportError):
        pass


def update_status(root: Path) -> dict | None:
    """The detached update's state for the page: running, or finished / failed (read once)."""
    return humanproof.take_update_status(root) if humanproof is not None else None


def ack_notice(root: Path, nid) -> bool:
    return humanproof is not None and isinstance(nid, str) and humanproof.ack_notice(root, nid)


def dismiss(root: Path, hid) -> None:
    if humanproof is not None and isinstance(hid, str):
        humanproof.handoff_drop(root, hid)
