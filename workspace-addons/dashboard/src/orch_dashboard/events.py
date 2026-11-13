"""One bounded revision watcher per server, running only while streams are open."""

import contextlib
import hashlib
import os
import threading


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
            for parent, dirs, files in os.walk(folder, followlinks=False):
                dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(parent, d))]
                # Ticket artifacts are not state; run records can be nested.
                if folder.name == "tickets":
                    dirs[:] = []
                for name in sorted(files):
                    if name.endswith(".json"):
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
            rev = self.signature()  # the folder walk happens outside the lock; the lock only publishes
            with self.condition:
                if not self.clients or self.closed:
                    self.thread = None
                    return
                if rev != self.rev:
                    self.rev = rev
                    self.condition.notify_all()
                self.condition.wait(0.25)

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
