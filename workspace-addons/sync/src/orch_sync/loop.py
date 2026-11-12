"""The background sync loop, the automation loop's shape: one step per interval, woken early by `orch sync now` or
`orch sync set`. It ends by itself when the add-on is turned off here or sync is set to off, and after the current
pass when it is asked to stop (SIGTERM or `orch sync stop`): never in the middle of a sync.

Mode and interval come only from this machine's run/sync/settings.json (never synced, written by `orch sync set`)."""

import threading
import time
import traceback
from datetime import UTC, datetime

from . import orchcli, repo, service
from .settings import DEFAULTS, FILE, minutes

POLL = 2.0  # seconds: how often a waiting loop looks for a wake or a stop request from another process
RECHECK = 300.0  # seconds: while waiting, ask the core at most this often whether the add-on is still on here
INFO = "run/sync/loop.json"  # last_try, next_run, last_error of the loop itself
WAKE = "run/sync/wake"


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
        self.stopping = False
        self.logged = None  # the last problem written to loop.log (not repeated while it lasts)

    def stop(self):
        """SIGTERM: finish the current pass, then end."""
        self.stopping = True
        self.wake.set()

    def stop_asked(self):
        if not self.stopping:
            try:
                self.stopping = repo.safe(self.root, service.STOP).is_file()  # `orch sync stop`, on every OS
            except (OSError, ValueError):
                pass
        return self.stopping

    def settings(self):
        return DEFAULTS | service.read(self.root, FILE)  # unreadable = off

    def ended(self):
        """Why the loop ends now (one plain line for loop.log), or None."""
        if self.stop_asked():
            return "stopped on request"
        raw = service.read(self.root, FILE)
        if not raw:
            return "no readable sync settings here (counted as off)"
        if (DEFAULTS | raw).get("mode") not in ("local", "remote"):
            return "sync is set to off here"
        if orchcli.is_active(self.root) is False:
            return "the sync add-on is turned off here"
        return None

    def log(self, line, detail=""):
        """One line (and a traceback) to loop.log; not again while the same problem repeats, so the log stays small."""
        if line != self.logged:
            self.logged = line
            print(line + (f"\n{detail.rstrip()}" if detail else ""), flush=True)

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
        now = time.monotonic()
        end, check = now + secs, now + RECHECK
        while not self.stop_asked() and (left := end - time.monotonic()) > 0:
            if self.wake.wait(min(left, POLL)) or self.woken():
                return
            if time.monotonic() >= check:
                check = time.monotonic() + RECHECK
                if orchcli.is_active(self.root) is False:
                    return  # turned off here: the next round ends the loop

    def run_forever(self, once=False, wait=None):
        """Passes until the loop ends; returns why (one line for loop.log)."""
        wait = wait or self.sleep
        while True:
            if why := self.ended():
                return why
            settings = self.settings()
            self.wake.clear()
            try:
                result, error = self.tick(), None
            except Exception as e:  # noqa: BLE001 - like the step's catch-all: a failing pass never ends the loop
                result, error = None, f"Sync stopped: {type(e).__name__}"
                self.log(f"sync: {error}", traceback.format_exc())
            secs = self.delay(result, settings)
            try:
                note(self.root, last_error=error, next_run=iso(self.clock() + secs))
                if error is None:
                    self.logged = None
            except Exception as e:  # noqa: BLE001 - a status file that can't be written never ends the loop
                self.log(f"sync: the loop status was not saved ({type(e).__name__})", traceback.format_exc())
            if once:
                return "one pass done"
            wait(secs)
