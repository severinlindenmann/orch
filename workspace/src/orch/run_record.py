"""The oneshot wrapper's part of the record (contracts/activity.md): after each turn, the agent's stdout lines
go to the collector its adapter names (adapters.collector, by `oneshot.events`), and from there to the run's
record. The tool's own hooks (`record_hooks`, `orch record hook`) write the same tool calls as they happen,
with the same tool-call id, so a call both saw is one line (the hook's; dedupe drops the collector's).

Nothing is written when key hiding is not ready (the same writer as the hook: record_hook._writer; never raw).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

_HARNESS = re.compile(r"[a-z][a-z0-9-]{0,31}")
_HELPER = re.compile(r"h_(\d+)")


def _so_far(root: Path, run: str) -> tuple[int, int]:
    """(last seq, helpers started) of the run's record so far: a later turn's collector never reuses an id
    `<run>:<seq>` or a helper number of an earlier one."""
    from orch import record

    got = record.read_run(root, run, seen_by="writer")
    if got.status != "ok":
        return 0, 0
    seq = max((e["seq"] for e in got.value), default=0)
    helpers = [int(m.group(1)) for e in got.value if (m := _HELPER.fullmatch(str(e.get("agent"))))]
    return seq, max(helpers, default=0)


def collect_turn(root: Path, run: str, tid: str, name: str, work: Path, lines) -> dict | None:
    """One turn's stdout lines into the run's record; the collector's counts, or None when nothing was
    collected (orch cannot read this agent's output, or recording is off until key hiding is ready). A refusal
    of the record itself (tampered, unavailable) is raised: the caller decides (the wrapper goes on)."""
    from orch import adapters, record, record_hook

    collector = adapters.collector(name, root)
    if collector is None:
        return None
    try:
        writer = record_hook._writer(root)
    except record.RecordOff:
        return None
    seq, helpers = _so_far(root, run)
    ctx = dict(
        run=run,
        ticket=tid,
        harness=name if _HARNESS.fullmatch(name) else "generic",  # as the hook writes it (ORCH_AGENT)
        at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        seq_start=seq,
        helper_start=helpers,
        workspace=[str(work), str(Path(work).resolve())],
    )
    return collector.collect(lines, writer, ctx)
