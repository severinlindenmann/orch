"""One bounded revision watcher per server, running only while streams are open."""

import contextlib
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
        try:  # opening the folder or reading its next entry can fail (os.walk skipped such a folder too)
            with os.scandir(top) as it:
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
        except OSError:
            continue


class Revisions:
    def __init__(self, root):
        self.root = root
        self.condition = threading.Condition()
        self.clients = 0
        self.thread = None
        self.rev = ""  # what the event stream sends: the files' state, or the stored copy's mark
        self.seen = ""  # the files' state the watcher saw last
        self.closed = False
        # set by the state cache: a file change starts its background build, and the pages are told by publish()
        # when the new copy is ready (told at the change itself, every page asked while the copy was old)
        self.on_change = None

    def signature(self):
        rows = []
        flat = ("tickets", "chat", "inbox")  # one level of .json files; run records can be nested
        for folder in (self.root / ".orch" / n for n in (*flat, "run")):
            # Ticket artifacts are not state; run records can be nested.
            json_rows(folder, folder.name not in flat, rows)
        # Settings come from these files: a changed helper command (committed config) or a person's Allow (the
        # machine's approvals) must reach the open page and the cached /api/state, not only ticket changes.
        for path in self.settings_files():
            try:
                st = os.stat(path, follow_symlinks=False)
                rows.append((str(path), st.st_mtime_ns, st.st_size))
            except OSError:
                pass
        return hashlib.sha256(repr(sorted(rows)).encode()).hexdigest()

    def settings_files(self):
        files = [
            self.root / ".orch" / "config.toml",
            self.root / ".orch" / "workspace.toml",
            self.root / "workspace.toml",
        ]
        # no orch installed or no home: the workspace files still count
        with contextlib.suppress(Exception):
            from orch import addons

            files.append(addons.home() / "agent-approvals.json")
        return files

    def join(self):
        first = self.signature()  # the folder walk happens outside the lock
        with self.condition:
            if self.closed or self.clients >= 20:
                return False
            self.clients += 1
            if self.thread is None:
                self.seen = first
                if self.on_change is None:
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
            changed = None
            with self.condition:
                if not self.clients or self.closed:
                    self.thread = None
                    return
                if rev != self.seen:
                    self.seen = rev
                    if self.on_change is None:
                        self.rev = rev
                        self.condition.notify_all()
                    else:
                        changed = self.on_change
            if changed is not None:
                with contextlib.suppress(Exception):  # the watcher keeps running whatever the cache does
                    changed(rev)
            with self.condition:
                if not self.clients or self.closed:
                    self.thread = None
                    return
                self.condition.wait(wait)

    def publish(self, rev):
        """The state cache stored a new copy: the open pages fetch it now."""
        with self.condition:
            if rev != self.rev:
                self.rev = rev
                self.condition.notify_all()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
