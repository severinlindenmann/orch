"""Live feel: follow the agent's own output into the run event log through the optional mapper.

Chosen by adapter data (adapterdata.events_kind): a one-shot run's stream log (`.orch/run/logs/<tid>-<run>.log`)
or a live run's transcript. No mapper named -> nothing is read and the board runs on ticket changes alone.
Events pass through events.make() (redacted, clipped) and are appended to the run's event log.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import adapterdata
from .adapters.claude import ClaudeMapper, transcript_path
from .events import RUN_ID, EventLog

MAX_READ = 256 * 1024
TID = re.compile(r"t_[a-z0-9]{6,16}")
MAPPERS = ("claude-stream-json/1", "claude-transcript/1")


class Tail:
    """One per ticket. `poll` reads what is new since the last call and returns the events it wrote."""

    def __init__(self, root: Path, tid: str, run: str, agent: str, mode: str, session=None):
        self.root, self.tid, self.run, self.agent, self.mode = root, tid, run, agent, mode
        self.session = session  # callable -> session id or None (asked lazily, live runs only)
        self.kind = adapterdata.events_kind(root, agent, mode) if RUN_ID.fullmatch(run) else None
        self.mapper = ClaudeMapper(run, tid) if self.kind in MAPPERS else None
        self.offset = 0
        self.log = EventLog(root, run) if RUN_ID.fullmatch(run) else None

    def _path(self) -> Path | None:
        if self.mode == "live":
            sid = self.session() if callable(self.session) else None
            return transcript_path(sid) if sid else None
        if not TID.fullmatch(self.tid):
            return None
        return self.root / ".orch" / "run" / "logs" / f"{self.tid}-{self.run}.log"

    def poll(self) -> list[dict]:
        if self.mapper is None or self.log is None:
            return []
        path = self._path()
        if path is None:
            return []
        try:
            if path.is_symlink():
                return []
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError:
            return []
        with os.fdopen(fd, "rb") as f:
            if self.offset > os.fstat(f.fileno()).st_size:
                self.offset = 0  # the file started over
            f.seek(self.offset)
            raw = f.read(MAX_READ)
        end = raw.rfind(b"\n") + 1  # a half-written last line waits
        events: list[dict] = []
        for line in raw[:end].decode("utf-8", "replace").splitlines():
            if not line.startswith("{"):
                continue  # one-shot logs also hold plain text
            try:
                doc = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if isinstance(doc, dict):
                try:
                    events += self.mapper.feed(doc)
                except (KeyError, TypeError, AttributeError, ValueError):
                    continue  # a line of a shape we do not know is skipped
        self.offset += end
        if events:
            try:
                self.log.append(*events)
            except OSError:
                pass
        return events
