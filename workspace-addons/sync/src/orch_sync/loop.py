"""The background sync loop, the automation loop's shape: one step per interval, woken early by `orch sync now` or
`orch sync set`. It ends by itself when the add-on is turned off here or sync is set to off.

Mode and interval come only from this machine's run/sync/settings.json (never synced, written by `orch sync set`)."""

import threading
import time
from datetime import UTC, datetime

from . import orchcli, repo, service

LOCAL = 5  # minutes: local mode commits what changed, every 5 minutes at most
INTERVALS = (5, 15, 60)  # minutes a remote sync may wait; anything else is 15
DEFAULT = 15
POLL = 2.0  # seconds: how often a waiting loop looks for a wake from another process
INFO = "run/sync/loop.json"  # last_try, next_run, last_error of the loop itself
WAKE = "run/sync/wake"


def minutes(settings):
    if settings.get("mode") == "local":
        return LOCAL
    n = settings.get("interval")
    return n if type(n) is int and n in INTERVALS else DEFAULT


def iso(ts):
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def note(root, **changes):
    from .step import encoded, write

    write(root, INFO, encoded(service.read(root, INFO) | changes))


def wake_up(root):
    """Ask a running loop (another process) for one pass now."""
    from .step import write

    write(root, WAKE, b"")


class Loop:
    def __init__(self, root, clock=time.time):
        self.root = root
        self.clock = clock
        self.wake = threading.Event()
        self.failures = 0  # offline passes in a row

    def settings(self):
        from .cli import DEFAULTS

        return DEFAULTS | service.read(self.root, "run/sync/settings.json")  # unreadable = off

    def delay(self, result, settings):
        """Seconds to the next pass. Offline: 1, 2, 4 ... minutes, never longer than the interval; reset on success."""
        base = minutes(settings) * 60
        if isinstance(result, dict) and result.get("last_error") == "offline":
            self.failures += 1
            return min(60 * 2 ** min(self.failures - 1, 10), base)
        self.failures = 0
        return base

    def tick(self):
        """One step; nothing while a pause this core signed waits for the person."""
        from . import cli, pause, step

        if pause.verified_pause(self.root, cli.read(self.root, "state")):
            return None
        note(self.root, last_try=iso(self.clock()))
        return step.run_once(self.root, "timer")

    def woken(self):
        try:
            p = repo.safe(self.root, WAKE)
            if p.is_file():
                p.unlink()
                return True
        except (OSError, ValueError):
            pass
        return False

    def sleep(self, secs):
        end = time.monotonic() + secs
        while (left := end - time.monotonic()) > 0:
            if self.wake.wait(min(left, POLL)) or self.woken():
                return

    def run_forever(self, once=False, wait=None):
        wait = wait or self.sleep
        while True:
            if orchcli.is_active(self.root) is False:
                return  # turned off in this workspace: stop by ourselves
            settings = self.settings()
            if settings.get("mode") not in ("local", "remote"):
                return  # sync set to off here
            self.wake.clear()
            try:
                result, error = self.tick(), None
            except Exception as e:  # noqa: BLE001 - like the step's catch-all: a failing pass never ends the loop
                result, error = None, f"Sync stopped: {type(e).__name__}"
            secs = self.delay(result, settings)
            try:
                note(self.root, last_error=error, next_run=iso(self.clock() + secs))
            except Exception as e:  # noqa: BLE001 - a status file that can't be written never ends the loop
                print(f"sync: the loop status was not saved ({type(e).__name__})", flush=True)  # to loop.log
            if once:
                return
            wait(secs)
