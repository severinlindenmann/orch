"""One bounded revision watcher per server, running only while streams are open."""

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
        return hashlib.sha256(repr(sorted(rows)).encode()).hexdigest()

    def join(self):
        with self.condition:
            if self.closed or self.clients >= 20:
                return False
            self.clients += 1
            if self.thread is None:
                self.rev = self.signature()
                self.thread = threading.Thread(target=self.watch, daemon=True)
                self.thread.start()
            return True

    def leave(self):
        with self.condition:
            self.clients -= 1
            self.condition.notify_all()

    def watch(self):
        with self.condition:
            while self.clients and not self.closed:
                rev = self.signature()
                if rev != self.rev:
                    self.rev = rev
                    self.condition.notify_all()
                self.condition.wait(0.25)
            self.thread = None

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
