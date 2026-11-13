"""The last /api/state answer, served at once; a stale copy is rebuilt by one background thread."""

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from .data import load_state

MAX_AGE = 2.0


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

    def _signature(self):
        try:
            return self.revisions.signature() if self.revisions is not None else None
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

    def _served(self):
        state, age = self.state, time.monotonic() - self.at
        return {**state, "now": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}, max(0.0, age)

    def get(self) -> tuple[dict, float]:
        if self.state is None:
            with self.first:
                if self.state is None:
                    self._store(*self._build())
        with self.lock:
            served = self._served()
            stale = served[1] >= MAX_AGE
            start = not self.busy and not self.closed
            gen = self.gen
        if self.revisions is not None and not stale and not self.closed and self._signature() != self.sig:
            # A file that matters changed (new question, new helper request): the page asks because it was told so,
            # and a stale copy would be the last answer it gets. Rebuild now, once; others wait for that build.
            return self.fresh()
        if start and stale:
            with self.lock:
                if self.busy or gen != self.gen:
                    return served
                self.busy = True
            threading.Thread(target=self._refresh, args=(gen,), daemon=True).start()
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
                except Exception:  # noqa: BLE001 - keep the old copy; the caller still gets an answer
                    if self.state is None:
                        raise
            with self.lock:
                return self._served()

    def _refresh(self, gen):
        try:
            self._store(*self._build(), gen=gen)
        except Exception:  # noqa: BLE001, S110 - keep the old copy; a later request tries again
            pass
        finally:
            with self.lock:
                self.busy = False

    def invalidate(self, state: dict):
        """After a change: `state` (the fresh answer of that change) replaces the copy; a rebuild already running
        cannot overwrite it with older data. A shallow copy: the caller may add its own keys to its dict."""
        self._store(dict(state), self._signature())

    def close(self):
        with self.lock:
            self.closed = True
