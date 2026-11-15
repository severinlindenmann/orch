"""The check-up reads: only whitelisted, shape-checked fields of `orch checkup list|show --json` leave this server
(workspace and agent text is data; the page inserts it as text nodes). Anything unexpected drops the row."""

from __future__ import annotations

import re

from .actions import CHECKUP_STATES, HASH, PROPOSAL
from .settings import TID

KINDS = ("skill.fix", "skill.new", "key.ask_admin", "connection.fix", "note")
TEST_STATES = ("not_run", "passed", "failed", "error")
TARGET_KINDS = ("skill", "connection", "key")
SOURCES = ("harness", "admin", "workspace", "builtin", "marketplace", "new")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
TIME = re.compile(r"\d{4}-\d\d-\d\dT[0-9:.]+Z")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
SHOWN_STATES = tuple(
    s for s in CHECKUP_STATES if s != "rejected"
)  # a dismissed proposal is gone from the page


def _text(value, limit):
    return CONTROL.sub(" ", value)[:limit] if isinstance(value, str) else None


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10**7 else None


def _tests(value):
    if not isinstance(value, dict) or value.get("state") not in TEST_STATES:
        return {"state": "not_run", "cases_passed": 0, "cases": 0}
    return {"state": value["state"], "cases_passed": _count(value.get("cases_passed")) or 0,
            "cases": _count(value.get("cases")) or 0}  # fmt: skip


def _proposal(row):
    if not isinstance(row, dict):
        return None
    pid, target = row.get("id"), row.get("target")
    title, plain = _text(row.get("title"), 200), _text(row.get("plain"), 1000)
    if not (isinstance(pid, str) and PROPOSAL.fullmatch(pid) and title and plain):
        return None
    if row.get("kind") not in KINDS or row.get("status") not in SHOWN_STATES or not isinstance(target, dict):
        return None
    name, source = target.get("name"), target.get("source")
    if target.get("kind") not in TARGET_KINDS or source not in SOURCES:
        return None
    if not (isinstance(name, str) and NAME.fullmatch(name)):
        return None
    return {"id": pid, "kind": row["kind"], "title": title, "plain": plain, "likely": row.get("likely") is True,
            "status": row["status"], "tests": _tests(row.get("tests")),
            "target": {"kind": target["kind"], "name": name, "source": source}}  # fmt: skip


def _last(value):
    if not isinstance(value, dict):
        return None
    at, ticket = value.get("at"), value.get("ticket")
    if not (isinstance(at, str) and TIME.fullmatch(at) and isinstance(ticket, str) and TID.fullmatch(ticket)):
        return None
    return {"ticket": ticket, "at": at, "runs": _count(value.get("runs")), "tickets": _count(value.get("tickets")),
            "found": _count(value.get("found"))}  # fmt: skip


def build_checkup(raw) -> dict:
    """The card's data. `available` False = the core could not be read or has no check-up: the page hides the card."""
    if not isinstance(raw, dict) or not isinstance(raw.get("proposals"), list):
        return {"available": False}
    rows = [p for p in map(_proposal, raw["proposals"][:200]) if p]
    return {"available": True, "last": _last(raw.get("last")), "running": raw.get("running") is True,
            "weekly": raw.get("weekly") if raw.get("weekly") in ("on", "off") else "unavailable",
            "proposals": rows}  # fmt: skip


def _diff_row(row):
    if not isinstance(row, dict):
        return None
    path, after, before = _text(row.get("path"), 200), row.get("after"), row.get("before_text")
    if not path or not (after is None or isinstance(after, str)):
        return None
    if not (before is None or isinstance(before, str)):
        return None
    return {"path": path, "before_text": before[:65536] if before is not None else None,
            "after": after[:65536] if after is not None else None}  # fmt: skip


def build_show(raw) -> dict | None:
    """One proposal with the file change for the Accept sheet; None when it can not be read."""
    prop = _proposal(raw)
    if prop is None:
        return None
    rows = raw.get("diff") if isinstance(raw.get("diff"), list) else []
    diff = [d for d in map(_diff_row, rows[:20]) if d]
    digest = raw.get("hash")
    return {**prop, "diff": diff, "hashed": isinstance(digest, str) and bool(HASH.fullmatch(digest))}
