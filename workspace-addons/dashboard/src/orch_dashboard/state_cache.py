"""The last /api/state answer, served at once; a stale copy is rebuilt by one background thread.

A request never waits for a build once a copy exists (issue: 4 to 20 s per answer with five helpers, every helper
step changed a file and every page request rebuilt the whole state). A change starts one background build; the
open pages are told "changed" (Revisions.publish) only when the new copy is stored, so the answer they then fetch
already holds it."""

import hashlib
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path

from . import state_delta
from .data import load_state, patch_ticket, start_line

MAX_AGE = 2.0  # without a revision watcher the copy is this old at most
# with a watcher: a poll that changed nothing costs no process; time-based values refresh this often
SAFETY_AGE = 120.0
# rest between two background builds: helpers that change files every second do not keep a build running
# without a pause (one build is a dozen `orch` processes)
MIN_GAP = 0.5


class StateCache:
    def __init__(self, root: Path, orch_bin: str | None, revisions=None):
        self.root, self.orch_bin, self.revisions = root, orch_bin, revisions
        self.lock = threading.Lock()
        self.first = threading.Lock()  # single flight for the first, synchronous build
        self.state: dict | None = None
        self.at = 0.0
        self.sig: str | None = None
        self.busy = False
        self.closed = False
        self.rebuild = threading.Lock()  # single flight for a synchronous rebuild after a change
        self.gen = 0  # bumped by every put(): a rebuild started earlier never overwrites a newer copy
        self.dirty = False  # a change arrived: the background builder builds (once more)
        self.ended = 0.0  # when the last background build ended (MIN_GAP)
        # fingerprints of the last revisions served (ORCH-517): a poll that holds one of them gets only the change
        self.prints: OrderedDict[str, dict] = OrderedDict()
        self.prints_lock = threading.Lock()
        if revisions is not None:
            revisions.on_change = self._changed

    def _changed(self, tid):
        """Publish a single changed ticket and its run without waiting for unrelated workspace reads."""
        with self.lock:
            # At most one quick copy between full builds: frequent run writes must not keep
            # advancing gen and discarding the build that refreshes the rest of the page.
            state, gen = self.state if self.sig is not None else None, self.gen
        try:
            if tid and state and any(t["id"] == tid for t in state["tickets"]):
                patched = patch_ticket(self.root, self.orch_bin, state, tid)
                if patched is not None:
                    self._store(patched, None, gen=gen)
        finally:
            self.kick()  # refresh the rest too, including simultaneous changes outside this ticket

    def _signature(self):
        try:
            return self.revisions.fingerprint() if self.revisions is not None else None
        except OSError:
            return None

    def _current(self):
        """For a page request: the watcher's last look when it runs (no folder walk per request), else a new one."""
        look = getattr(self.revisions, "current", None)
        if look is None:
            return self._signature()
        try:
            return look()
        except OSError:
            return None

    def _build(self):
        sig = self._signature()  # taken before the read: a change during the build makes the copy stale
        return load_state(self.root, orch_bin=self.orch_bin, with_settings=True), sig

    def _store(self, state, sig, gen=None):
        with self.lock:
            if gen is not None and gen != self.gen:
                return
            self.gen += 1
            self.state, self.at, self.sig = state, time.monotonic(), sig
            gen = self.gen
        if self.revisions is not None and hasattr(self.revisions, "publish"):
            self.revisions.publish(f"s{gen}-{sig or ''}")  # the pages fetch now, and get this copy

    def _served(self):
        state, age = self.state, time.monotonic() - self.at
        out = {**state, "now": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
        if "auto_update_note" in state:  # the live page: read each time (it lives in the orch home, which
            from . import update  # no workspace change signals), and a new note changes the revision

            note = update.auto_note()
            if note != state["auto_update_note"]:
                out["auto_update_note"] = note
                out["rev"] = f"{state.get('rev', '')}-u{note['at'] if note else 0}"
        if "update_check" in state:  # the card after a failed self-check: in the orch home too
            from . import update

            card = update.check_card()
            if card != state["update_check"]:
                out["update_check"] = card
                out["rev"] = f"{out.get('rev', state.get('rev', ''))}-c{card['at'] if card else 0}"
        if state.get("start_line"):  # why the line does not move changes with the load, not with a file
            line = start_line(self.root)
            if line != state["start_line"]:
                out["start_line"] = line
                out["rev"] = f"{out.get('rev', '')}-l{hashlib.sha1(repr(line).encode()).hexdigest()[:8]}"
        return out, max(0.0, age)

    def get(self) -> tuple[dict, float]:
        if self.state is None:
            with self.first:
                if self.state is None:
                    self._store(*self._build())
        with self.lock:
            served = self._served()
            stale = served[1] >= (MAX_AGE if self.revisions is None else SAFETY_AGE)
            busy = self.busy
        if stale or (not busy and self.revisions is not None and self._current() != self.sig):
            # Changed or old: build in the background and answer with the copy now. With an open event stream the
            # page is told when the new copy is ready; without one its next poll gets it.
            self.kick()
        return served

    def fresh(self) -> tuple[dict, float]:
        """Rebuild now (single flight) unless a build that started after this call began has just finished."""
        began = time.monotonic()
        with self.rebuild:
            with self.lock:
                done = self.at >= began and self.sig == self._signature()
            if not done:
                try:
                    self._store(*self._build())
                except Exception:  # keep the old copy; the caller still gets an answer
                    if self.state is None:
                        raise
            with self.lock:
                return self._served()

    def _print(self, state: dict) -> dict | None:
        rev = state_delta.base_rev(str(state.get("rev") or ""))
        if not rev:
            return None
        with self.prints_lock:  # one fingerprint per revision, made once (a few dozen ms for 500 tickets)
            fp = self.prints.get(rev)
            if fp is None:
                fp = state_delta.fingerprint(state)
                if fp is None:
                    return None
                self.prints[rev] = fp
                while len(self.prints) > state_delta.KEEP:
                    self.prints.popitem(last=False)
            return fp

    def answer(self, state: dict, have: str) -> dict:
        """The body for a poll that holds revision `have`: only what changed when `have` is one of the last
        revisions served, else the whole state. Either way this revision is remembered for the next poll."""
        cur = self._print(state)
        with self.prints_lock:
            base = self.prints.get(state_delta.base_rev(have)) if have else None
        if cur is None or base is None:
            return state
        return state_delta.delta(base, cur, state, have)

    def kick(self, *_ignored):
        """A change (or an old copy): one background build; a change during that build makes one more after it."""
        with self.lock:
            if self.closed:
                return
            self.dirty = True
            if self.busy:
                return
            self.busy = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            with self.lock:
                if not self.dirty or self.closed:
                    self.busy = False  # a kick after this check must start the next worker
                    return
                self.dirty = False
                gen = self.gen
                rest = MIN_GAP - (time.monotonic() - self.ended)
            if rest > 0:
                time.sleep(rest)
            try:
                self._store(*self._build(), gen=gen)
            except Exception:  # noqa: BLE001, S110 - keep the old copy; a later change or request tries again
                pass
            finally:
                self.ended = time.monotonic()

    def quick(self, state: dict):
        """A click's answer (the last copy with the clicked ticket read again) is served at once, and a full build
        follows in the background: it replaces this copy, and the pages are told when it is stored."""
        self._store(dict(state), None)  # stored as changed: it counts as old until the build has run
        self._print(state)  # the page takes this revision from the click's answer: its next poll gets a delta
        self.kick()

    def invalidate(self, state: dict):
        """After a change: `state` (the fresh answer of that change) replaces the copy; a rebuild already running
        cannot overwrite it with older data. A shallow copy: the caller may add its own keys to its dict."""
        self._store(dict(state), self._signature())
        self._print(state)

    def close(self):
        with self.lock:
            self.closed = True
