"""Live steps from the record: `orch record tail --run <run> --follow --json` (contracts/activity.md).

Focus never reads the record files. One followed command per run feeds a small reader thread; `poll()` hands over
what arrived since the last call, already shaped as the run events the Board folds (tool.start / tool.end,
helper.*, run.state, usage, denial). Task and question lines of the record are skipped: the ticket watcher
already makes them from the ticket itself. The newest cursor is kept, so a restart of the command never shows a
step twice. If the command cannot run, the board simply gets no steps (it still works from ticket changes).
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from pathlib import Path

from . import actions, events

RESTART_SECONDS = 2.0
MAX_LINE = 64 * 1024
MAX_QUEUE = 500
RUN = re.compile(r"r_[a-z0-9_]{6,32}")  # contracts/activity.schema.json $defs/run
_popen = subprocess.Popen  # tests may patch this name, never the global


def _used(e: dict) -> dict:
    u = e.get("used")
    return u if isinstance(u, dict) else {}


def _data(e: dict) -> dict:
    d = e.get("data")
    return d if isinstance(d, dict) else {}


def to_events(e: dict, ticket: str) -> list[dict]:
    """One activity event -> zero or more Focus run events. Unknown kinds and odd shapes give nothing."""
    try:
        kind, run, agent = e["kind"], e["run"], e.get("agent") or "main"
        text, at = str(e.get("text") or ""), e.get("at")
        done = e.get("outcome")
        eid = str(e["id"])
        source = str(e.get("via") or "log")

        def make(k, **data):
            return events.make(run, ticket, agent, k, text, source, at=at, **data)

        if kind == "step":
            if done is None:
                return [make("tool.start", id=eid)]
            return [make("tool.end", id=eid, ok=done.get("ok") is not False)]
        if kind == "helper.start":
            return [make("helper.start", id=eid)]
        if kind == "helper.end":
            return [make("helper.end", id=eid, ok=(done or {}).get("ok") is not False)]
        if kind == "run.state":
            state = _data(e).get("state")
            return [make("run.state", state="idle" if state == "waiting_you" else state)] if state else []
        if kind == "usage":
            d = _data(e)
            if not isinstance(d.get("used"), (int, float)) or isinstance(d.get("used"), bool):
                return []
            return [make("usage", used=d["used"], window=d.get("window"), status=d.get("status", "ok"))]
        if kind == "denial":
            return [make("denial", tool=str(_used(e).get("name") or "a tool"))]
    except (KeyError, TypeError, AttributeError, ValueError):
        pass
    return []


class RecordFeed:
    """One per run. Starts the followed command on first poll; `close()` ends it (by its own pid)."""

    def __init__(self, root: Path, orch_bin: str | None, run: str, ticket: str):
        self.root, self.orch_bin, self.run, self.ticket = Path(root), orch_bin, run, ticket
        self.cursor: str | None = None
        self.lock = threading.Lock()
        self.queue: list[dict] = []
        self.stopped = threading.Event()
        self.proc = None
        self.thread: threading.Thread | None = None

    def poll(self) -> list[dict]:
        if not RUN.fullmatch(self.run) or not self.orch_bin:
            return []
        if self.thread is None and not self.stopped.is_set():
            self.thread = threading.Thread(target=self._loop, daemon=True, name="focus-record")
            self.thread.start()
        with self.lock:
            out, self.queue = self.queue, []
        return out

    def _argv(self) -> list[str]:
        argv = [*actions.argv0(self.orch_bin), "record", "tail", "--run", self.run, "--follow", "--json"]
        return argv + ["--since", self.cursor] if self.cursor else argv

    def _loop(self) -> None:
        while not self.stopped.is_set():
            try:
                self._once()
            except OSError:
                pass  # the command cannot start: no steps, the board goes on without them
            self.stopped.wait(RESTART_SECONDS)

    def _once(self) -> None:
        p = _popen(
            self._argv(), cwd=self.root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=actions.human_env(self.root, self.orch_bin),
        )  # fmt: skip
        self.proc = p
        try:
            if self.stopped.is_set():
                return
            for raw in p.stdout:
                if self.stopped.is_set():
                    return
                self._line(raw[:MAX_LINE])
        finally:
            self._end(p)

    def _line(self, raw: bytes) -> None:
        try:
            doc = json.loads(raw)
        except (ValueError, RecursionError):
            return
        if not isinstance(doc, dict):
            return
        cur = doc.get("cursor")
        if doc.get("type") == "event" and isinstance(doc.get("event"), dict):
            got = to_events(doc["event"], self.ticket)
            with self.lock:
                self.queue = (self.queue + got)[-MAX_QUEUE:]
        if doc.get("type") in ("event", "ping", "unavailable") and isinstance(cur, str) and cur:
            self.cursor = cur

    @staticmethod
    def _end(p) -> None:
        try:
            if p.poll() is None:
                p.terminate()
            p.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                p.kill()
                p.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def close(self) -> None:
        self.stopped.set()
        p = self.proc
        if p is not None:
            self._end(p)
        if self.thread is not None:
            self.thread.join(timeout=5)
