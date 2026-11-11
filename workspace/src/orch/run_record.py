"""The oneshot wrapper's part of the record (contracts/activity.md): after each turn, the agent's stdout lines
go to the collector its adapter names (adapters.collector, by `oneshot.events`), and from there to the run's
record. The tool's own hooks (`record_hooks`, `orch record hook`) write the same tool calls as they happen,
with the same tool-call id, so a call both saw is one line. Hook lines come from inside the agent's trust
boundary: a hook's end line is provisional (`ok: null`) and the log's end line of that call replaces it.

Nothing is written when key hiding is not ready (the same writer as the hook: record_hook.record_writer; never
raw). Two traces under the run (record.note_lost) say when the hooks went quiet: `hooks_off` (the agent's
folder settings switch the tool's hooks off) and `hooks_missing` (the turn's log has tool calls, none of them
reached the record through a hook).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

_HARNESS = re.compile(r"[a-z][a-z0-9-]{0,31}")
_HELPER = re.compile(r"h_(\d+)")
LOCK_WAIT = 10.0  # seconds: a run lock held longer skips the turn's numbering read (a trace, never a hang)


def _so_far(root: Path, run: str) -> tuple[int, int]:
    """(highest number used, helpers started) of the run file as written (record.run_lines: raw, under the
    run lock): the highest seq and the highest n of a `<run>:<n>` id (a collector's id counter also counts
    lines dedupe dropped, so ids can run ahead of seqs), and the highest helper number the log gave. A later
    turn's collector never reuses an id or a helper number of an earlier one. Raises the record's refusal."""
    from orch import record

    prefix = re.compile(re.escape(run) + r":(\d{1,18})")
    seq = helpers = 0
    for e in record.run_lines(root, run, lock_wait=LOCK_WAIT):
        if type(e.get("seq")) is int:
            seq = max(seq, e["seq"])
        if isinstance(e.get("id"), str) and (m := prefix.fullmatch(e["id"])):
            seq = max(seq, int(m.group(1)))
        # only the log numbers helpers (a hook line could say any)
        if e.get("via") == "log" and (m := _HELPER.fullmatch(str(e.get("agent")))):
            helpers = max(helpers, int(m.group(1)))
    return seq, helpers


def collect_turn(root: Path, run: str, tid: str, name: str, work: Path, lines) -> dict | None:
    """One turn's stdout lines into the run's record; the collector's counts, or None when nothing was
    collected (orch cannot read this agent's output, recording is off until key hiding is ready, or the run
    file cannot be read as written: nothing is numbered from a view orch cannot trust). A refusal of the
    record itself while writing (tampered, unavailable) is raised: the caller decides (the run goes on)."""
    from orch import adapters, record, record_hook

    collector = adapters.collector(name, root)
    if collector is None:
        return None
    try:
        writer = record_hook.record_writer(root)
    except record.RecordOff:
        return None
    try:
        seq, helpers = _so_far(root, run)
    except record.RecordTampered:
        return None  # its integrity alert is left (record._report)
    except record.RecordRefused as e:  # busy past LOCK_WAIT, unavailable: the turn is skipped, with a trace
        record.note_lost(root, run, "collector_error", error=type(e).__name__)
        return None
    ctx = dict(
        run=run,
        ticket=tid,
        harness=name if _HARNESS.fullmatch(name) else "generic",  # as the hook writes it (ORCH_AGENT)
        at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        seq_start=seq,
        helper_start=helpers,
        workspace=[str(work), str(Path(work).resolve())],
        lock_wait=LOCK_WAIT,
    )
    stats = collector.collect(lines, writer, ctx)
    settings = (adapters.load(name, root).get("reminder") or {}).get("settings_file")
    hooks_disabled = getattr(collector, "hooks_disabled", None)
    if hooks_disabled is not None and isinstance(settings, str) and hooks_disabled(work, settings):
        record.note_lost(root, run, "hooks_off")
    elif stats.get("tool_calls") and not stats.get("hook_seen"):
        record.note_lost(root, run, "hooks_missing")
    return stats
