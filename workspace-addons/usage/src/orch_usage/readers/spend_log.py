"""Credit reader for the spend log the API credit scripts write: one JSON line per call, `{"t", "account", "usd"}`.

Source: `{"reader": "spend-log", "path": "<file>", "name": "<account name in the log>", "unnamed": true}`. `unnamed`:
lines without an account name count for this account too (the credit script's own default). A time without a zone is
this computer's time (the scripts write `time.strftime`). Read only; the file holds no key. Usage counts what the log says since the start of the limit's period; the provider's own figure may differ
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
    total, last = 0.0, None
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
        usd, t = row.get("usd"), _when(row.get("t"))
        if not isinstance(usd, (int, float)) or isinstance(usd, bool) or t is None:
            continue
        if start and t < start:
            continue
        total += float(usd)
        last = t if last is None or t > last else last
    as_of = last.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if last else None
    return CreditUse(spent=round(total, 4), since=since, as_of=as_of, estimated=True)
