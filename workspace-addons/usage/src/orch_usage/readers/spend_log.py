"""Credit reader for the spend log the API credit scripts write: one JSON line per call, `{"t", "account", "usd"}`.

orch's own helper runs on an API key write the same lines with an `"id"` (one per helper step, keystart.py): the
last line of an id counts, so a step is counted once, and `"usd": null` means its spend is unknown (written before
the step, replaced by the reported dollars after it). Unknown steps are never counted as 0: the note says how many.

Source: `{"reader": "spend-log", "path": "<file>", "name": "<account name in the log>", "unnamed": true}`. `unnamed`:
lines without an account name count for this account too (the credit script's own default). A time without a zone is
this computer's time (the scripts write `time.strftime`). Read only; the file holds no key. Usage counts what the log
says since the start of the limit's period; the provider's own figure may differ
(marked as estimated).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from . import CreditUse

MAX_BYTES = 20 * 1024 * 1024


def _when(text) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        t = datetime.fromisoformat(text)
    except ValueError:
        return None
    return t if t.tzinfo else t.astimezone()  # no zone: this computer's time, as the scripts write it


def read(source: dict, since: str | None) -> CreditUse:
    path = Path(str(source.get("path") or "")).expanduser()
    name = source.get("name")
    unnamed = source.get("unnamed") is True
    if not source.get("path") or not path.is_file():
        return CreditUse(spent=None, since=since, note="The spend log is not there.")
    try:
        if path.stat().st_size > MAX_BYTES:
            return CreditUse(spent=None, since=since, note="The spend log is too big to read.")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return CreditUse(spent=None, since=since, note="The spend log could not be read.")
    start = _when(since)
    rows, by_id = [], {}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        acct = row.get("account")
        if name is not None and acct != name and not (acct is None and unnamed):
            continue
        rid = row.get("id")
        if isinstance(rid, str) and rid:
            by_id[rid] = row  # the last line of a step counts
        else:
            rows.append(row)
    total, last, unknown = 0.0, None, 0
    for row in rows + list(by_id.values()):
        usd, t = row.get("usd"), _when(row.get("t"))
        if t is None or (start and t < start):
            continue
        if usd is None and isinstance(row.get("id"), str):
            unknown += 1
            continue
        if not isinstance(usd, (int, float)) or isinstance(usd, bool):
            continue
        total += float(usd)
        last = t if last is None or t > last else last
    as_of = last.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if last else None
    note = None
    if unknown:
        note = f"{unknown} helper step{'s' if unknown != 1 else ''} did not report {'their' if unknown != 1 else 'its'} spend (unknown)"
    if unknown and last is None:  # nothing known in dollars: unknown, never 0
        return CreditUse(spent=None, since=since, estimated=True, note=note)
    return CreditUse(spent=round(total, 4), since=since, as_of=as_of, estimated=True, note=note)
