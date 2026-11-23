"""A helper's turn ends with questions for the person in its reply, but none is on the ticket (ORCH-1760).

A question that sits only in the chat reply is not seen: the person reads the ticket, the Review cards and the
phone, and the ticket keeps saying Working. This module answers one thing: does this last reply ask the
person something while the ticket has no open question? The end-of-turn hook (workcheck.stop_notice) then
sends the helper back once to put it on the ticket with `orch ask`; a tool without a blocking end-of-turn
hook gets one history line instead (runs.wrap).

Pure reading: it never writes, never raises out of `nudge`, and reads at most a bounded tail of a transcript.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path

TRANSCRIPT_TAIL = 512 * 1024  # bytes read from the end of a transcript file
MAX_TEXT = 20000  # characters of a reply that are looked at
MAX_SHOWN = 3  # questions quoted in the nudge

_FENCE = re.compile(r"```.*?(```|\Z)", re.S)
_INLINE = re.compile(r"`[^`\n]*`")
_QUOTE = re.compile(r"^\s*>.*$", re.M)
_URL = re.compile(r"\bhttps?://\S+")
# a sentence ends at ".", "!" or "?" followed by a space (so "0.5h" inside stays one sentence)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_MARKER = re.compile(r"^(?:[-*+]|\d{1,3}[.)])\s+")
# a polite closing line with nothing to decide ("Anything else?")
_CLOSER = re.compile(r"^(is there )?anything else( (I can do|you need))?( for you)?\?$", re.I)
_ANSWER = re.compile(r"^(because|the answer|simple:|short answer)\b", re.I)


def questions(text: str | None) -> list[str]:
    """The questions a reply asks, in order: sentences that end in "?", outside code, quotes and links."""
    if not isinstance(text, str) or not text.strip():
        return []
    t = text[:MAX_TEXT]
    t = _FENCE.sub("\n", t)
    t = _INLINE.sub(" ", t)
    t = _QUOTE.sub("", t)
    t = _URL.sub(" ", t)
    out = []
    for row in t.splitlines():
        row = row.strip()
        if row.startswith("#") or (row.startswith("**") and row.endswith("**")):
            continue  # a heading ("## What's next?") is not a question to the person
        sents = [" ".join(x.strip().strip("*_").split()) for x in _SENTENCE.split(_MARKER.sub("", row))]
        for i, q in enumerate(sents):
            if len(q) < 6 or not q.endswith("?") or _CLOSER.match(q):
                continue
            if i + 1 < len(sents) and _ANSWER.match(sents[i + 1]):
                continue  # "Why does it matter? Because ...": the helper answers it itself
            out.append(q[:300])
    return out


def open_questions(ticket: dict) -> list[str]:
    """Every question or card on the ticket that nobody answered or took back yet (of any kind)."""
    return [
        str(q.get("id"))
        for q in ticket.get("questions") or []
        if isinstance(q, dict) and q.get("answer") is None and not q.get("taken_back")
    ]


def line(key: str, asked: list[str]) -> str:
    """The nudge: how many questions, the first few quoted, and the command that puts them on the ticket."""
    n = len(asked)
    shown = "; ".join(f'"{q[:120]}"' for q in asked[:MAX_SHOWN]) + (" ..." if n > MAX_SHOWN else "")
    what = "a question" if n == 1 else f"{n} questions"
    return (
        f"orch: your reply asks the person {what} ({shown}), but none is open on ticket {key}. "
        "A question only in the reply is not seen. Put each one on the ticket: "
        f'orch ask {key} "<question>" --option A --option B --recommend A, then end the turn. '
        "If it was not meant for the person, end the turn as it is."
    )


def history_text(n: int) -> str:
    """The history line for a tool that cannot be sent back at the end of its turn."""
    what = "a question that is" if n == 1 else f"{n} questions that are"
    return (
        f"The helper's last reply asked {what} not on the ticket: read its reply or ask it to use orch ask."
    )


def nudge(root: Path, tid: str, text: str | None) -> tuple[str, list[str]] | None:
    """(ticket key, questions) when the reply asks the person something and the ticket has nothing open and
    is still being worked on; else None. Never raises."""
    try:
        asked = questions(text)
        if not asked:
            return None
        from orch import tickets

        t = tickets.load(root, tid)
        if t.get("status") not in ("open", "active", "ready"):
            return None  # waiting (something is asked), in Review, done or dropped: nothing to nudge
        if open_questions(t):
            return None
        return str(t.get("key") or tid), asked
    except Exception:  # noqa: BLE001 - a hook never gets in the agent's way
        return None


def last_reply_from_transcript(path: str | None) -> str | None:
    """The text of the last assistant message in the tool's transcript (JSONL, `assistant` rows), read
    from a bounded tail."""
    if not isinstance(path, str) or not os.path.isabs(path):
        return None
    p = Path(path)
    try:
        if p.is_symlink() or not p.is_file():
            return None
        size = p.stat().st_size
        with p.open("rb") as f:
            f.seek(max(0, size - TRANSCRIPT_TAIL))
            raw = f.read(TRANSCRIPT_TAIL).decode("utf-8", "replace")
    except OSError:
        return None
    for row in reversed(raw.splitlines()):
        try:
            d = json.loads(row)
        except ValueError:
            continue
        if not isinstance(d, dict) or d.get("type") != "assistant":
            continue
        content = (d.get("message") or {}).get("content")
        if isinstance(content, str):
            return content
        texts = [c.get("text") for c in content or [] if isinstance(c, dict) and c.get("type") == "text"]
        texts = [x for x in texts if isinstance(x, str) and x.strip()]
        if texts:
            return "\n".join(texts)
    return None


def last_reply_from_stream(out: str | None) -> str | None:
    """The last agent message in a one-step run's JSON lines (an `item.completed` agent_message, or a
    `result` line); None when there is none."""
    if not isinstance(out, str):
        return None
    for row in reversed(out.strip().splitlines()[-2000:]):
        row = row.strip()
        if not row.startswith("{"):
            continue
        with contextlib.suppress(ValueError):
            d = json.loads(row)
            if not isinstance(d, dict):
                continue
            item = d.get("item") if isinstance(d.get("item"), dict) else None
            if d.get("type") == "item.completed" and item and item.get("type") == "agent_message":
                if isinstance(item.get("text"), str):
                    return item["text"]
            if d.get("type") == "result" and isinstance(d.get("result"), str):
                return d["result"]
    return None
