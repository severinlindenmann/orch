"""Hook entry of the record (contracts/activity.md, "The hook entry is narrow"): `orch record hook`.

A live agent session calls it from its tool hooks (before and after every tool call) with ONE event as a JSON
line on stdin. It must be fast and must never get in the agent's way, so by default it ends with exit 0 and
says in one plain stderr line why nothing was recorded. What it never does:
- write a kind the hook may not write (record.hook_entry_filter: no run.state, ask, task.*, key.use, job,
  session.input) or any `via` but "hook";
- trust the caller for the run, the ticket, the harness or the time: the run and ticket come from ORCH_RUN /
  ORCH_TICKET and must name a live claim that belong together AND the calling process must be a descendant of
  that claim's process (the wrapper or the agent), so a process outside the run cannot write into it by
  setting the same variables (the pid must match the recorded start time, never just "not different"); a line
  naming another run is dropped;
- write when key hiding is not ready (no registered hider: nothing is written, never raw);
- read anything but the one run file (the writer's per-run strict read; no scan of other runs).
A hook line that cannot be written leaves a short trace: under the run (record.note_lost) only for a proven
caller, else in one global file without a run id (record.note_unattributed); none when there was no run.
The event id is the tool's own tool-call id (the agent's own field), put in `id` by the caller; the record
hashes an unsafe one once, the same way for hook and collector, so the two dedupe. Taken: an event-shaped
line (it has a `kind`), or the agent tool's own hook payload as its before/after-tool hook sends it (the
wiring: `record_hooks` in agents/reminder.json), mapped by that tool's collector (adapters.collector,
hook_line) to a step whose id is the payload's tool-call id. Files are made relative to the folder the run
works in (its copy, else the workspace).
--strict turns every "not recorded" into a refusal (exit 2) for scripts and tests.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from orch import record
from orch.errors import Refused
from orch.record_files import workspace_files

LOCK_WAIT = (
    1.0  # seconds: a busy run lock spools the line at once (a PreToolUse hook must not freeze the agent)
)
MAX_LINE = 8 * 1024 * 1024  # a larger payload is not read further; the line is still recorded, detail lost
_FIELDS = ("id", "kind", "text", "session", "agent", "parent", "coverage", "used", "outcome", "data")
_HARNESS = re.compile(r"[a-z][a-z0-9-]{0,31}")
_BAD = "The record entry is not valid; nothing was recorded."
_TOO_BIG = {"input": "x" * (1024**2 + 1), "output": ""}  # a detail over 1 MB: the writer marks detail_lost


class NotRecorded(Exception):
    """Nothing was written. `note` is the plain sentence for stderr; `reason` is the trace code (or None)."""

    def __init__(self, note: str, reason: str | None = None):
        super().__init__(note)
        self.note, self.reason = note, reason


def _ids(environ):
    run, ticket = environ.get("ORCH_RUN"), environ.get("ORCH_TICKET")
    return (run, ticket) if run and ticket else None


def _parents() -> dict[int, int] | None:
    """pid -> parent pid for this machine, or None when it cannot be read (then nothing can be proven)."""
    table: dict[int, int] = {}
    pid = os.getpid()
    if os.path.isdir("/proc/self"):
        for _ in range(64):
            try:
                with open(f"/proc/{pid}/stat", "rb") as f:
                    fields = f.read().rsplit(b")", 1)[1].split()
                parent = int(fields[1])
            except (OSError, ValueError, IndexError):
                return table or None
            table[pid] = parent
            if parent <= 1 or parent in table:
                break
            pid = parent
        return table
    if os.name == "nt":
        return None
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=5, check=True
        ).stdout
        for row in out.splitlines():
            a, b = row.split()
            table[int(a)] = int(b)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return table


def _ancestors() -> set[int] | None:
    table = _parents()
    if table is None:
        return None
    found, pid = {os.getpid()}, os.getpid()
    while pid in table and table[pid] > 0 and table[pid] not in found:
        pid = table[pid]
        found.add(pid)
    return found


def require_run(root, ids) -> dict:
    """ORCH_RUN + ORCH_TICKET must name a live claim (secretrun's check) and this process must be inside the
    claim's process tree (its wrapper pid or its agent pid is an ancestor, with the recorded start time).
    Returns the claim."""
    from orch import procs, runs, secretrun

    try:
        rec = secretrun.check_live_run(root, *ids)
    except Refused:
        raise NotRecorded("This run is not active, so nothing was recorded.", "not_active") from None
    mine = _ancestors()
    if mine is not None:
        for pid_key, started_key in (("pid", "pid_started"), ("agent_pid", "agent_pid_started")):
            pid = rec.get(pid_key)
            if isinstance(pid, int) and pid in mine:
                started = rec.get(started_key)
                now = procs.pid_started(pid) if started else None
                # only a positive match: a pid whose start time is unknown could be a reused one
                if started and now and runs.same_start(now, started):
                    return rec
        raise NotRecorded("This call is not from inside that run, so nothing was recorded.", "other_run")
    raise NotRecorded("Cannot tell where this call comes from, so nothing was recorded.", "not_provable")


def _parse(text: str) -> dict:
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        raise NotRecorded(_BAD, "invalid") from None
    if not isinstance(value, dict):
        raise NotRecorded(_BAD, "invalid")
    return value


def _from_tool(raw: dict, tool, root) -> dict:
    """An event-shaped line (it has a `kind`) as it is; else the agent tool's own hook payload as an event
    line whose id is the tool-call id, mapped by the collector of the tool this process runs under
    (adapters.collector: hook_line, the same mapping as for its log, so the two lines dedupe)."""
    if "kind" in raw:
        return raw
    from orch import adapters

    try:
        mapper = adapters.collector(tool, root) if isinstance(tool, str) else None
    except Refused:
        mapper = None
    if mapper is None:
        raise NotRecorded(_BAD, "invalid")
    try:
        line = mapper.hook_line(raw)
    except ValueError:
        raise NotRecorded(_BAD, "invalid") from None
    if line is None:
        raise NotRecorded("A helper is recorded from the agent's log; nothing was recorded here.")
    return line


def _minimal() -> dict:
    """The audit line of a payload too large to read: the fact that a tool call happened, detail lost."""
    return {
        "kind": "step",
        "text": "A tool call (its entry was too large to keep)",
        "used": {"kind": "tool", "name": "unknown", "action": None, "source": "harness", "version": None},
    }


def _event(raw: dict, ids, tool, root=None) -> tuple[dict, dict | None]:
    for key, mine in (("run", ids[0]), ("ticket", ids[1])):
        if key in raw and raw[key] != mine:
            raise NotRecorded("That entry belongs to another run; nothing was recorded.", "other_run")
    try:
        filtered = record.hook_entry_filter(raw)  # kind allowed, via forced to hook
    except record.RecordRefused:
        raise NotRecorded(
            "This kind of record is not allowed here; nothing was recorded.", "invalid"
        ) from None
    harness = tool if isinstance(tool, str) and _HARNESS.fullmatch(tool) else "generic"
    event = {
        "session": None,
        "agent": "main",
        "parent": None,
        "coverage": "full",
        "outcome": None,
        "text": "",
        **{k: filtered[k] for k in _FIELDS if k in filtered},
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),  # the caller's time is never kept
        "harness": harness,  # nor its harness: it is the tool this process runs under
        "v": 1,
        "run": ids[0],
        "ticket": ids[1],
        "via": "hook",
        "detail": None,
    }
    if filtered["kind"] != "step":
        event.setdefault("used", None)  # only a step names the thing it used
    files = filtered.get(
        "files"
    )  # display only (activity.md, Files): kept on a step, normalised like the collectors'
    if filtered["kind"] == "step" and isinstance(files, list):
        event["files"] = workspace_files(files, root)
    if event.get("id") is None:
        event.pop("id", None)  # the writer assigns h_<run>:<seq>
    payload = raw.get("payload")
    if payload is not None and not (isinstance(payload, dict) and {"input", "output"} <= payload.keys()):
        raise NotRecorded(_BAD, "invalid")
    return event, payload


def record_writer(root):
    """The writer every out-of-core origin of a run uses (this hook entry, the oneshot wrapper's collector,
    `orch job`): the one with a registered hider, else one built from this workspace's key store (secretrun's
    wiring); no hider = recording is off (RecordOff; never raw)."""
    try:
        return record.registered_writer(root)
    except record.RecordOff:
        pass
    from orch import secretrun

    try:
        return secretrun.record_writer(root)
    except (Refused, ValueError, TypeError):
        raise record.RecordOff("Recording is off until key hiding is ready.") from None


def hook(root, text: str, environ=None, *, too_large: bool = False, before_write=lambda: None) -> dict | None:
    """Record one event line; raises NotRecorded (or a RecordRefused) when nothing was written.
    before_write runs after the caller is proven and the line is read, right before anything is written (the
    hook's watchdog is cancelled there: it must never end the process in the middle of a write)."""
    environ = os.environ if environ is None else environ
    ids = _ids(environ)
    if ids is None:
        raise NotRecorded("Not inside an orch run; nothing was recorded.")
    # require_run, _parse and _event below never write; the first write is behind before_write
    try:
        claim = require_run(root, ids)
    except NotRecorded as e:  # the caller is not proven: the claimed run id is its word, so nothing under it
        if e.reason:
            before_write()
            record.note_unattributed(root, e.reason)
        raise
    try:
        from orch import tickets, worktrees

        # files are relative to the folder the run works in, as given and resolved (/tmp -> /private/tmp)
        folder = Path(worktrees.workdir_for(root, claim, ids[1]))
        work = [str(folder), str(folder.resolve())]
        tool = tickets.agent_tool()
        if too_large:
            event, payload = _event(_minimal(), ids, tool, work)
            payload = _TOO_BIG
        else:
            event, payload = _event(_from_tool(_parse(text), tool, root), ids, tool, work)
        before_write()
        try:
            writer = record_writer(root)
        except record.RecordOff:
            raise NotRecorded("Recording is off until key hiding is ready.", "hider_off") from None
        return writer.append(event, detail=payload, lock_wait=LOCK_WAIT)
    except NotRecorded as e:
        if e.reason:
            before_write()
            record.note_lost(root, ids[0], e.reason)
        raise
    except record.RecordInvalid:
        before_write()
        record.note_lost(root, ids[0], "invalid")
        raise


def cli(root, stream=None, strict: bool = False, before_write=lambda: None) -> None:
    """Exit 0 with one plain stderr line when nothing was recorded; with strict a Refused (exit 2) instead."""
    stream = sys.stdin if stream is None else stream
    try:
        text = stream.readline(MAX_LINE + 1)
        hook(root, text, too_large=len(text) > MAX_LINE, before_write=before_write)
        return
    except NotRecorded as e:
        note = e.note
    except record.RecordRefused as e:
        note = str(e) or "Nothing was recorded."
    except BaseException:  # never get in the agent's way, whatever went wrong (a SystemExit included)
        note = "Nothing was recorded."
    if strict:
        raise Refused(note)
    sys.stderr.write(f"orch: {note}\n")
