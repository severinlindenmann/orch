"""Each click the page sends carries an id the page made (X-Orch-Act-Id, ORCH-580). The server remembers what an
id did for a while: a repeat of the same id (a retry after a lost answer, a double click) gets the first result
and is never run again, and the page can ask whether an id went through before it offers Retry.

Kept in memory only: a restarted dashboard forgets them (the page then says it could not tell)."""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict

ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
TTL = 15 * 60  # seconds an id is remembered after it finished
KEEP = 256  # at most this many ids
WAIT = 600  # a repeat waits this long for the first run of its id (ticket.new with files can take a while)


class Entry:
    __slots__ = ("at", "caller", "done", "op", "reply", "result", "what")

    def __init__(self, op: str, caller: tuple = (), what: str = ""):
        self.op = op
        self.caller = caller  # who sent it: (has the person's session, the add-on page's pass or None)
        self.what = what  # a hash of the op and its arguments: a repeat must send the same
        self.done = threading.Event()
        self.result: tuple[int, str, object] | None = None  # (status, text, extra) of the op
        self.reply: dict | None = (
            None  # the small keys the answer carried (the new ticket's id, saved files ...)
        )
        self.at = time.monotonic()


class ActIds:
    def __init__(self):
        self.lock = threading.Lock()
        self.items: OrderedDict[str, Entry] = OrderedDict()

    def _prune(self):
        now = time.monotonic()
        for key in [k for k, e in self.items.items() if e.done.is_set() and now - e.at > TTL]:
            del self.items[key]
        while len(self.items) > KEEP:
            key = next((k for k, e in self.items.items() if e.done.is_set()), None)
            if key is None:
                break
            del self.items[key]

    def claim(self, act_id: str, op: str, caller: tuple = (), what: str = "") -> tuple[Entry, bool]:
        """(entry, True) when this request runs the op; (entry, False) when an earlier request with the same id
        did or does: wait on `entry.done`, then use `entry.result` (None = it ran into a refusal; run it now)."""
        with self.lock:
            self._prune()
            e = self.items.get(act_id)
            if e is not None and (not e.done.is_set() or e.result is not None):
                return e, False
            e = Entry(op, caller, what)
            self.items[act_id] = e
            return e, True

    def finish(self, entry: Entry, result, reply: dict | None = None):
        """Only a done op (status 200) is remembered. `result` None or a refusal (orch said no, nothing was done):
        the id is forgotten, so a repeat (after the person fixed what was refused) runs again."""
        if result is not None and result[0] != 200:
            result = None
        with self.lock:
            entry.result, entry.reply, entry.at = result, reply, time.monotonic()
            if result is None:
                for k, e in list(self.items.items()):
                    if e is entry:
                        del self.items[k]
            entry.done.set()

    def status(self, act_id: str, caller: tuple = ()) -> dict:
        """What the page's question "did my click go through?" gets: done (with its status and small reply),
        running, or unknown (never arrived, refused, or forgotten)."""
        with self.lock:
            self._prune()
            e = self.items.get(act_id)
        if e is None or e.caller != caller:  # only who sent the click learns about it
            return {"state": "unknown"}
        if not e.done.is_set():
            return {"state": "running", "op": e.op}
        out: dict = {"state": "done", "op": e.op, "status": e.result[0]}
        if e.reply:
            out["reply"] = e.reply
        return out
