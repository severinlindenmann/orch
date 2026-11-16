"""The Update button (Settings > About & updates): one detached `orch update`, what changed, and its result.
Also the automatic update (off until a person turns it on): a background thread asks orch about once a minute
(orch.autoupdate.tick) and passes it the person's clicks, so an update never starts in the middle of one."""

from __future__ import annotations

import threading
import time
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
        return 503, "Updating is not available in this install."
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
        data["auto"] = autoupdate_status()
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


# ---- the automatic update

TICK_SECONDS = 60
_clicks = {"busy": 0, "last": 0.0}
_clicks_lock = threading.Lock()


class click:
    """`with update.click():` around a person's action (POST /api/act): no automatic update starts meanwhile
    or in the two minutes after it."""

    def __enter__(self):
        with _clicks_lock:
            _clicks["busy"] += 1
            _clicks["last"] = time.time()

    def __exit__(self, *exc):
        with _clicks_lock:
            _clicks["busy"] = max(0, _clicks["busy"] - 1)
            _clicks["last"] = time.time()
        return False


def autoupdate_status() -> dict:
    try:
        from orch import autoupdate

        return autoupdate.status()
    except Exception:  # noqa: BLE001
        return {}


def auto_note() -> dict | None:
    """The note Home shows after an automatic update (the new version and what changed, or why it failed)."""
    try:
        from orch import autoupdate

        return autoupdate.note()
    except Exception:  # noqa: BLE001
        return None


def dismiss_auto_note() -> None:
    try:
        from orch import autoupdate

        autoupdate.dismiss_note()
    except Exception:  # noqa: BLE001, S110 - the note stays; the next click tries again
        pass


def tick_once(root: Path, orch_bin, env_for, start=None) -> str:
    """One automatic-update look. `env_for()` gives the person's environment for the detached update."""
    try:
        from orch import autoupdate
    except ImportError:
        return "off"

    def run() -> int:
        pid = (start or start_detached)(["update"], orch_bin=orch_bin, cwd=root, env=env_for())
        _record_update(root, pid)
        return pid

    with _clicks_lock:
        busy, last = _clicks["busy"] > 0, _clicks["last"]
    try:
        return autoupdate.tick(root, run, last_click=last or None, clicking=busy)
    except Exception:  # noqa: BLE001 - a broken look must never stop the dashboard
        return "error"


def start_ticker(root: Path, orch_bin, env_for, every: float = TICK_SECONDS) -> threading.Thread | None:
    """The background look, in this dashboard's process (no daemon of its own)."""
    if start_detached is None:
        return None

    def loop():
        time.sleep(min(every, 20))  # let the server come up first
        while True:
            tick_once(root, orch_bin, env_for)
            time.sleep(every)

    t = threading.Thread(target=loop, daemon=True, name="autoupdate")
    t.start()
    return t
