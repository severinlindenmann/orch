"""Hook entry of the record (contracts/activity.md, "The hook entry is narrow"): `orch record hook`.

A live agent session calls it from its tool hooks (before and after every tool call) with ONE event as a JSON
line on stdin. It must be fast and must never get in the agent's way, so by default it ends with exit 0 and
says in one plain stderr line why nothing was recorded. What it never does:
- write a kind the hook may not write (record.hook_entry_filter: no run.state, ask, task.*, key.use, job,
  session.input) or any `via` but "hook";
- trust the caller for the run or the ticket: both come from ORCH_RUN / ORCH_TICKET and must name a live
  claim that belong together (the rule of secretrun.require_run); a line naming another run is dropped;
- write when key hiding is not ready (no registered hider: nothing is written, never raw);
- read anything but the one run file (the writer's per-run strict read; no scan of other runs).
--strict turns every "not recorded" into a refusal (exit 2) for scripts and tests.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

from orch import hider, record
from orch.errors import Refused

MAX_LINE = 256 * 1024  # a larger payload is not read further
_FIELDS = (
    "id",
    "kind",
    "text",
    "session",
    "agent",
    "parent",
    "at",
    "harness",
    "coverage",
    "used",
    "outcome",
    "data",
)
_HARNESS = re.compile(r"[a-z][a-z0-9-]{0,31}")
_BAD = "The record entry is not valid; nothing was recorded."


class NotRecorded(Exception):
    """Nothing was written. `note` is the plain sentence for stderr."""

    def __init__(self, note: str):
        super().__init__(note)
        self.note = note


def _ids(environ):
    run, ticket = environ.get("ORCH_RUN"), environ.get("ORCH_TICKET")
    return (run, ticket) if run and ticket else None


def require_run(root, ids) -> None:
    """ORCH_RUN + ORCH_TICKET must name a live claim that belong together (secretrun.require_run's rule)."""
    from orch import runs

    run, ticket = ids
    try:
        rec = runs.read(root, ticket)
        ok = bool(rec) and rec.get("run") == run and runs.state(rec) in ("alive", "maybe-stale")
    except Exception:
        ok = False
    if not ok:
        raise NotRecorded("This run is not active, so nothing was recorded.")


def _parse(text: str) -> dict:
    if len(text) > MAX_LINE:
        raise NotRecorded("The record entry is too large; nothing was recorded.")
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        raise NotRecorded(_BAD) from None
    if not isinstance(value, dict):
        raise NotRecorded(_BAD)
    return value


def _event(raw: dict, ids, tool) -> tuple[dict, dict | None]:
    for key, mine in (("run", ids[0]), ("ticket", ids[1])):
        if key in raw and raw[key] != mine:
            raise NotRecorded("That entry belongs to another run; nothing was recorded.")
    try:
        filtered = record.hook_entry_filter(raw)  # kind allowed, via forced to hook
    except record.RecordRefused:
        raise NotRecorded("This kind of record is not allowed here; nothing was recorded.") from None
    harness = tool if isinstance(tool, str) and _HARNESS.fullmatch(tool) else "generic"
    event = {
        "session": None,
        "agent": "main",
        "parent": None,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "harness": harness,
        "coverage": "full",
        "outcome": None,
        "text": "",
        **{k: filtered[k] for k in _FIELDS if k in filtered},
        "v": 1,
        "run": ids[0],
        "ticket": ids[1],
        "via": "hook",
        "detail": None,
    }
    if filtered["kind"] != "step":
        event.setdefault("used", None)  # only a step names the thing it used
    if event.get("id") is None:
        event.pop("id", None)  # the writer assigns <run>:<seq>
    payload = raw.get("payload")
    if payload is not None and not (isinstance(payload, dict) and {"input", "output"} <= payload.keys()):
        raise NotRecorded(_BAD)
    return event, payload


def _writer(root):
    """The writer with a registered hider; none = recording is off (never raw)."""
    try:
        return record.registered_writer(root)
    except record.RecordOff:
        pass
    from orch import keystore

    needles = getattr(keystore, "all_needles", None)  # this workspace's own key store, in its guarded home
    if needles is None:
        raise record.RecordOff("Recording is off until key hiding is ready.")
    try:
        return record.RecordWriter(root, hider=hider.Hider(needles(root)))
    except (Refused, ValueError, TypeError):
        raise record.RecordOff("Recording is off until key hiding is ready.") from None


def hook(root, text: str, environ=None) -> dict | None:
    """Record one event line; raises NotRecorded (or a RecordRefused) when nothing was written."""
    environ = os.environ if environ is None else environ
    ids = _ids(environ)
    if ids is None:
        raise NotRecorded("Not inside an orch run; nothing was recorded.")
    raw = _parse(text)
    from orch import tickets

    event, payload = _event(raw, ids, tickets.agent_tool())
    require_run(root, ids)
    return _writer(root).append(event, detail=payload)


def cli(root, stream=None, strict: bool = False) -> None:
    """Exit 0 with one plain stderr line when nothing was recorded; with strict a Refused (exit 2) instead."""
    stream = sys.stdin if stream is None else stream
    try:
        hook(root, stream.readline(MAX_LINE + 1))
        return
    except NotRecorded as e:
        note = e.note
    except record.RecordRefused as e:
        note = str(e) or "Nothing was recorded."
    if strict:
        raise Refused(note)
    sys.stderr.write(f"orch: {note}\n")
