"""One bounded revision watcher per server, running only while streams are open.

Same watcher as the dashboard's orch_dashboard/events.py (add-ons share no code, so it is copied)."""

import hashlib
import os
import threading
import time

# A scan takes this share of the watcher's time at most: the wait after a scan is the scan's own time times
# SCAN_GAP, within WAIT_MIN..WAIT_MAX seconds (ORCH-609: at about 1,000 tickets a scan takes 10-30 ms, four scans a
# second were 4-12% of a core while a page was open). A small workspace keeps the 0.25 s wait.
WAIT_MIN, WAIT_MAX, SCAN_GAP = 0.25, 2.0, 50


def next_wait(scan_seconds):
    return max(WAIT_MIN, min(WAIT_MAX, scan_seconds * SCAN_GAP))


def json_rows(folder, nested, rows):
    """(path, mtime_ns, size) of every .json file in `folder` (and below it when `nested`), symlinked folders
    left out: os.walk's answer with one system call per file (scandir knows the entry type), not three."""
    todo = [str(folder)]
    while todo:
        top = todo.pop()
        try:
            it = os.scandir(top)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if nested:
                            todo.append(e.path)
                    elif e.name.endswith(".json"):
                        st = e.stat(follow_symlinks=False)
                        rows.append((e.path, st.st_mtime_ns, st.st_size))
                except OSError:
                    pass


class Revisions:
    def __init__(self, root):
        self.root = root
        self.condition = threading.Condition()
        self.clients = 0
        self.thread = None
        self.rev = ""
        self.closed = False

    def signature(self):
        rows = []
        for folder in (self.root / ".orch" / "tickets", self.root / ".orch" / "run"):
            # Ticket artifacts are not state; run records can be nested.
            json_rows(folder, folder.name != "tickets", rows)
        return hashlib.sha256(repr(sorted(rows)).encode()).hexdigest()

    def join(self):
        first = self.signature()  # the folder walk happens outside the lock
        with self.condition:
            if self.closed or self.clients >= 20:
                return False
            self.clients += 1
            if self.thread is None:
                self.rev = first
                self.thread = threading.Thread(target=self.watch, daemon=True)
                self.thread.start()
            return True

    def leave(self):
        with self.condition:
            self.clients -= 1
            self.condition.notify_all()

    def watch(self):
        while True:
            began = time.monotonic()
            rev = self.signature()  # the folder walk happens outside the lock; the lock only publishes
            wait = next_wait(time.monotonic() - began)
            with self.condition:
                if not self.clients or self.closed:
                    self.thread = None
                    return
                if rev != self.rev:
                    self.rev = rev
                    self.condition.notify_all()
                self.condition.wait(wait)

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
