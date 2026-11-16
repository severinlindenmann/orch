"""The Update button (Settings > About & updates): one detached `orch update`, what changed, and its result."""

from __future__ import annotations

from pathlib import Path

try:
    from orch import pagelaunch
    from orch.pagesession import start_detached
except ImportError:  # standalone use without orch: nothing runs
    pagelaunch = None
    start_detached = None


def start_update(root: Path, orch_bin, env, session=None, start=None) -> tuple[int, str]:
    """The person clicked Update: run `orch update` detached. `session` is the page session to keep open
    across the restart; a request without a page session is refused by the caller before this runs."""
    if pagelaunch is None:
        return 403, "Open the dashboard from this computer to do this."
    if session is not None:
        pagelaunch.write_resume_cookie(root, session.server, session.cookie, session.secret)
    try:
        pid = (start or start_detached)(["update"], orch_bin=orch_bin, cwd=root, env=env)
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
        data["ref"] = addons.ref()[:100]
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
    return pagelaunch.take_update_status(root) if pagelaunch is not None else None
