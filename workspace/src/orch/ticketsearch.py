"""Ticket search and the waiting filters: one implementation for `orch ticket list --search/--waiting`
(and --blocked) and the dashboard's search (R4.3).

A search finds a ticket by its number ('58', '#58', 'ORCH-58', 'orch 58'), its id, or words in its title,
owner, note, description and tasks (case does not count). Waiting splits like the dashboard's groups: a
Waiting ticket with an open question or a start to allow waits on a person (`waiting`); one that waits only
for a time, another ticket, a pull request or the outside is `blocked`."""

from __future__ import annotations

import re

MAX_NEEDLE = 200


def needle(text: object) -> str:
    """The search words as matches() takes them: trimmed, lower case, at most 200 characters."""
    return str(text or "").strip().lower()[:MAX_NEEDLE]


def search_text(t: dict) -> str:
    """Every word a search looks in: title, owner, note, description and the task texts (lower case)."""
    parts = [t.get("title"), t.get("owner"), t.get("note"), t.get("description")]
    parts += [c.get("text") for c in t.get("checklist") or [] if isinstance(c, dict)]
    return "\n".join(str(p) for p in parts if isinstance(p, str)).lower()


def key_match(t: dict, words: str) -> bool:
    """'58', '#58' or 'ORCH-58' finds that ticket by its number (exact); 'orch58' and 'orch 58' too."""
    key = str(t.get("key") or "").lower()
    if not key:
        return False
    digits = words.lstrip("#")
    if digits.isdigit():
        return key.split("-")[-1] == str(int(digits))
    flat = lambda v: re.sub(r"[\s-]+", "", v)  # noqa: E731
    return key == words or flat(key) == flat(words)


def matches(row: dict, text: str, words: str) -> bool:
    """True when the ticket `row` (its search_text is `text`) fits the needle `words`; empty fits all."""
    if not words:
        return True
    if key_match(row, words) or row.get("id") == words:
        return True
    if not re.fullmatch(r"#?\d+", words) and words in str(row.get("key") or "").lower():
        return True
    return words in text


def _open_questions(t: dict) -> int:
    if isinstance(t.get("questions_open"), int):  # an index row carries the count
        return t["questions_open"]
    return sum(1 for q in t.get("questions") or [] if isinstance(q, dict) and q.get("answer") is None)


def blocked(t: dict) -> bool:
    """Waiting, not on a person: no open question and no start to allow (a time, a ticket, the outside)."""
    w = t.get("waiting_on") if isinstance(t.get("waiting_on"), dict) else {}
    return t.get("status") == "waiting" and not _open_questions(t) and w.get("start") is not True


def waiting(t: dict) -> bool:
    """Waiting on a person: an open question or a start to allow."""
    return t.get("status") == "waiting" and not blocked(t)


def pick(
    rows: list[dict], search: str = "", *, only_blocked: bool = False, only_waiting: bool = False
) -> list[dict]:
    """The rows that fit the search words and the waiting filter, in their order."""
    words = needle(search)
    return [
        t
        for t in rows
        if (not only_blocked or blocked(t))
        and (not only_waiting or waiting(t))
        and matches(t, search_text(t) if words else "", words)
    ]
