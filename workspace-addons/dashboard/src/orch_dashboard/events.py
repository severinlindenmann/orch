"""One bounded revision watcher per server, running only while streams are open."""

import contextlib
import hashlib
import os
import re
import threading
import time
from pathlib import Path

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
        self.ticket_files = {}
        self.closed = False
        self._health = None  # the login check results file in the guarded home, once found
        # set by the state cache: a file change starts its background build, and the pages are told by publish()
        # when the new copy is ready (told at the change itself, every page asked while the copy was old)
        self.on_change = None

    def fingerprint(self, ticket_files=None):
        rows = []
        # one level of .json files (ticket artifacts are not state): one scandir pass, a few dozen ms at 10,000
        # tickets where a walk with a stat per path took a quarter second (ORCH-522)
        # checks: the workspace's own login checks (`orch logins add|remove`), shown on Home and Settings > Helper
        for name in ("tickets", "chat", "inbox", "checks"):
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
                        if ticket_files is not None and name == "tickets":
                            ticket_files[("ticket", e.name)] = (st.st_mtime_ns, st.st_size)
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
                        if ticket_files is not None and parent == str(run / "tickets"):
                            ticket_files[("run", name)] = (st.st_mtime_ns, st.st_size)
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
        return self.fingerprint()

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
            # the add-on list (`orch addon uninstall` rewrites it): without it a removed add-on stayed in the
            # cached Settings list until the 120 s safety rebuild (ORCH-1034)
            files.append(addons.registry_path())
            # the add-ons on in this workspace (`orch addon add|remove` rewrites it): a removed add-on's tab and
            # ticket rows leave the open page at once, not after the 120 s safety rebuild
            files.append(addons.activation_path(self.root))
        # Changes made in the terminal that the page shows (ORCH-308 / #1402): the last login check result
        # (`orch logins`), git (`git add` of the orch files: the private-files card; a remote) and the saved
        # problem reports folder (its own mtime moves when a report is added or deleted; the busy notes beside
        # it are not watched).
        with contextlib.suppress(Exception):
            if self._health is None:  # found once: the guarded home does not move while the server runs
                from orch import home as orch_home

                self._health = orch_home.key_dir(self.root, create=False) / "health.json"
            files.append(self._health)
        git = self.git_dir()
        # config: a remote added or removed (the pull-request switches)
        files += [git / "index", git / "config"]
        files.append(self.root / ".orch" / "diag" / "reports")
        return files

    def git_dir(self):
        """The folder git keeps its index in: .git, or where a worktree's .git file points."""
        dot = self.root / ".git"
        with contextlib.suppress(OSError, ValueError):
            if dot.is_file():
                line = dot.read_text(encoding="utf-8", errors="replace").strip()
                if line.startswith("gitdir:"):
                    target = Path(line[len("gitdir:") :].strip())
                    return target if target.is_absolute() else self.root / target
        return dot

    def join(self):
        files = {}
        first = self.fingerprint(files)  # the folder walk happens outside the lock
        with self.condition:
            if self.closed or self.clients >= 20:
                return False
            self.clients += 1
            if self.thread is None:
                self.seen = first
                self.ticket_files = files
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
            files = {}
            rev = self.fingerprint(files)  # the folder walk happens outside the lock; the lock only publishes
            rest = max(0.25, REST_FACTOR * (time.monotonic() - began))
            changed = None
            with self.condition:
                if not self.clients or self.closed:
                    self.thread = None
                    return
                if rev != self.seen:
                    self.seen = rev
                    before, self.ticket_files = self.ticket_files, files
                    if self.on_change is None:
                        self.rev = rev
                        self.condition.notify_all()
                    else:
                        changed = self.on_change
            if changed is not None:
                names = {key[1] for key in before.keys() | files.keys() if before.get(key) != files.get(key)}
                name = next(iter(names)) if len(names) == 1 else ""
                with contextlib.suppress(Exception):  # the watcher keeps running whatever the cache does
                    changed(name[:-5] if re.fullmatch(r"t_[a-z0-9]{6,16}\.json", name) else None)
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
