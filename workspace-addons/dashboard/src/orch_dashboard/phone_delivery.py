"""Question delivery from local relay records; no relay requests or recipient data in output."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


def _text(root: Path, relative: str) -> str:
    p = root
    try:
        for part in (".orch", *relative.split("/")):
            p = p / part
            if p.is_symlink():
                return ""
        if not p.is_file():  # no pipes or devices (a read could block)
            return ""
        with p.open("rb") as f:
            return f.read(1_000_000).decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""


def _object(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError):
        return {}
    return value if isinstance(value, dict) else {}


def _delivered(value) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        return None
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return None
    return value


def mark(root: Path, tickets: list[dict]) -> None:
    """Join sent message IDs to questions-sent; queued messages carry their own question IDs.

    A local message is evidence of sending, not of delivery. Only its delivered_at is a receipt.
    The sent log currently omits receipts, so those messages have delivered=None.
    """
    asked = _object(_text(root, "secrets/questions-sent.json"))
    records = [
        _object(line) for line in _text(root, "run/relay/sent.jsonl").splitlines()
    ]
    queued = root / ".orch" / "outbox"
    if not (root / ".orch").is_symlink() and not queued.is_symlink():
        try:
            for p in queued.glob("m_*.json"):
                msg = _object(_text(root, f"outbox/{p.name}"))
                if msg.get("schema") == "orch.msg/1" and msg.get("id") == p.stem:
                    msg.pop("delivered_at", None)  # only the relay's own receipt counts
                    records.append(msg)
        except OSError:
            pass
    found: dict[tuple[str, str], str | None] = {}
    for msg in records:
        if msg.get("type") != "question" or msg.get("to") != "phones":
            continue
        mid = msg.get("id")
        if not isinstance(mid, str):
            continue
        mapping = asked.get(mid)
        body = msg.get("body")
        if isinstance(body, dict):
            tid, qid = msg.get("ticket"), body.get("question_id")
        elif isinstance(mapping, dict) and mapping.get("to") == "phones":
            tid, qid = mapping.get("ticket"), mapping.get("question_id")
        else:
            continue
        if not isinstance(tid, str) or not isinstance(qid, str):
            continue
        key = tid, qid
        found[key] = _delivered(msg.get("delivered_at")) or found.get(key)
    for ticket in tickets:
        for question in ticket.get("questions") or []:
            if not isinstance(question, dict):
                continue
            qid = question.get("id")
            key = (ticket["id"], qid) if isinstance(qid, str) else None
            question["sent_to_phone"] = key in found
            question["delivered"] = found.get(key)
