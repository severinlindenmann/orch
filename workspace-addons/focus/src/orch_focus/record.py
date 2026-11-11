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
import unicodedata
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


LABEL_KINDS = ("skill", "tool", "mcp")
SOURCES = ("harness", "admin", "workspace", "builtin", "marketplace")


def _label(e: dict) -> dict | None:
    """What a step used, for the page's Skill / Tool / Connection label: kind, name, action, source."""
    u = _used(e)
    if u.get("kind") not in LABEL_KINDS or not isinstance(u.get("name"), str) or not u["name"]:
        return None
    action = u.get("action") if isinstance(u.get("action"), str) else None
    source = u.get("source") if u.get("source") in SOURCES else "harness"
    return {"kind": u["kind"], "name": u["name"], "action": action, "source": source}


MAX_FILES = 8
MAX_PATH = 260
_HIDDEN = ("Cc", "Cf", "Zl", "Zp")  # control and format characters (unicodedata categories)
_NOT_PLAIN = re.compile(r"^(?:[~$]|[A-Za-z][A-Za-z0-9+.\-]*:)")  # ~, $, a scheme or a drive letter


def file_ok(p) -> bool:
    """One entry of a step's `files` (contracts/activity.md, Files): 1..260 characters, NFC, workspace-relative POSIX
    (no leading /, no `..` segment, no backslash, no ~ $ scheme or drive start, no control or format character).
    The core writer checks the same; Focus checks again because it shows whatever it is handed."""
    return (
        isinstance(p, str)
        and 1 <= len(p) <= MAX_PATH
        and unicodedata.is_normalized("NFC", p)
        and not p.startswith("/")
        and "\\" not in p
        and not _NOT_PLAIN.match(p)
        and ".." not in p.split("/")
        and not any(unicodedata.category(c) in _HIDDEN for c in p)
    )


def clean_files(raw) -> list[str]:
    """The `files` of a step: the good entries, at most 8. Display only: Focus never opens these paths."""
    out: list[str] = []
    for p in raw if isinstance(raw, list) else []:
        if file_ok(p):
            out.append(p)
        if len(out) == MAX_FILES:
            break
    return out


def _data(e: dict) -> dict:
    d = e.get("data")
    return d if isinstance(d, dict) else {}


TRUSTED_DENIAL = (
    "log",
    "core",
)  # a hook line can be written by anything the agent runs: it never drives a prompt


def to_events(e: dict, ticket: str, want_run: str) -> list[dict]:
    """One activity event -> zero or more Focus run events. Unknown kinds, odd shapes, another run or ticket give
    nothing; a denial counts only from a collector or the core (via log/core), never from a hook."""
    try:
        kind, run, agent = e["kind"], e["run"], e.get("agent") or "main"
        if run != want_run or e.get("ticket") != ticket:
            return []  # not this run's line: never shown, never acted on
        text, at = str(e.get("text") or ""), e.get("at")
        done = e.get("outcome")
        eid = str(e["id"])
        source = str(e.get("via") or "log")

        def make(k, **data):
            return events.make(run, ticket, agent, k, text, source, at=at, **data)

        if kind == "step":
            used, files = _label(e), clean_files(e.get("files")) or None
            if done is None:
                return [make("tool.start", id=eid, used=used, files=files)]
            return [make("tool.end", id=eid, ok=done.get("ok") is not False, used=used, files=files)]
        if kind == "helper.start":
            return [make("helper.start", id=eid, parent=e.get("parent"))]
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
            if e.get("via") not in TRUSTED_DENIAL:
                return []
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
            got = to_events(doc["event"], self.ticket, self.run)
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
