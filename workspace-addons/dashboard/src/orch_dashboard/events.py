"""One bounded revision watcher per server, running only while streams are open."""

import contextlib
import hashlib
import os
import threading
import time

# Files in .orch/run that a state build reads AND writes itself (a cache, a "last seen" time): a change there is no
# news for the page. Counted, every build changed them, the change started the next build and told every open page
# to fetch the state again, over and over while nothing happened (ORCH-522).
READER_CACHES = frozenset(
    {"last-seen.json", "ticket-index.json", "pull-checks.json", "usage-cache.json", "needs-cache"}
)
# The watcher rests at least this many times as long as one look took: a big workspace is looked at less often
# instead of keeping a processor busy.
REST_FACTOR = 4


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
        # one level of .json files (ticket artifacts are not state): one scandir pass, a few dozen ms at 10,000
        # tickets where a walk with a stat per path took a quarter second (ORCH-522)
        for name in ("tickets", "chat", "inbox"):
            try:
                with os.scandir(self.root / ".orch" / name) as it:
                    for e in it:
                        if not e.name.endswith(".json"):
                            continue
                        try:
                            if e.is_dir():
                                continue
                            st = e.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        rows.append((e.path, st.st_mtime_ns, st.st_size))
            except OSError:
                pass
        run = self.root / ".orch" / "run"
        for parent, dirs, files in os.walk(run, followlinks=False):  # run records can be nested
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(parent, d))]
            if parent == str(run):
                dirs[:] = [d for d in dirs if d not in READER_CACHES]
            for name in files:
                if name.endswith(".json") and not (parent == str(run) and name in READER_CACHES):
                    path = os.path.join(parent, name)
                    try:
                        st = os.stat(path, follow_symlinks=False)
                        rows.append((path, st.st_mtime_ns, st.st_size))
                    except OSError:
                        pass
        # Settings come from these files: a changed helper command (committed config) or a person's Allow (the
        # machine's approvals) must reach the open page and the cached /api/state, not only ticket changes.
        for path in self.settings_files():
            try:
                st = os.stat(path, follow_symlinks=False)
                rows.append((str(path), st.st_mtime_ns, st.st_size))
            except OSError:
                pass
        return hashlib.sha256(repr(sorted(rows)).encode()).hexdigest()

    def current(self):
        """The files' state: what the running watcher saw last (it looks again within a moment), else a new look.
        A page request then costs no folder walk while a page is open (ORCH-522)."""
        with self.condition:
            if self.thread is not None and self.seen and not self.closed:
                return self.seen
        return self.signature()

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
            rest = max(0.25, REST_FACTOR * (time.monotonic() - began))
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
                self.condition.wait(rest)

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
