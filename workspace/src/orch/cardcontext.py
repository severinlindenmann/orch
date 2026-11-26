"""What a person said, quoted on a Review card ("You said on <day>: ..."), ORCH-2183 (Focused review B).

Owner rule (26 Nov, after the outside challenge): a card quotes a person ONLY from a stable reference the
helper names (`orch ask ... --said <ref>`); orch copies the words, the author and the day from the record
itself, so the helper never types a quote and cannot make one up. No reference, no quote (there is no "newest
words" guess).

References:
  m_<16>          a chat line of this ticket (its stable id, contracts/history.md "Chat lines")
  history:<at>    a history line of this ticket, by its time stamp (a comment a person left)
  rules:<n>       line n of the team rules file, `.orch/ask-when.md` (shown as "Team rule")

A reference to anything that is not a person's own words (an agent's line, a synced line not verified here, a
heading or an empty rule line) is refused. The copy keeps a version (sha256 of the full words) and the version
of what the decision is about (the ticket's description and Done when).

`check` says whether the quote still holds. Out of date when, after the quote:
  gone     the record is not there any more (words taken away, the rule line removed)
  changed  the record's words or author are not the ones quoted
  goal     the ticket's description or Done when changed
  newer    the same person wrote again on this ticket after the quoted line
A quote that is out of date is never answered for the person: the Reviewer and Away mode leave the question
to them (it asks again instead of only warning), and the card shows "This may be out of date" with no filled
answer.
Readers take history through `history.lines` (tests/test_history_lint.py).
"""

from __future__ import annotations

import getpass
import hashlib
import re
from datetime import datetime
from pathlib import Path

from orch import history
from orch.errors import Refused

WORDS_MAX = 160  # the card's quote is cut here, with "..."
RULES_FILE = "ask-when.md"
_CHAT_RE = re.compile(r"m_[a-z0-9]{16}")
_HIST_RE = re.compile(r"history:(\S{10,40})")
_RULE_RE = re.compile(r"rules:([1-9][0-9]{0,4})")
REASONS = ("gone", "changed", "goal", "newer")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def goal_version(ticket: dict) -> str:
    """The version of what a decision on this ticket is about: its description and Done when."""
    return _sha(f"{ticket.get('description') or ''}\n\x00\n{ticket.get('done_when') or ''}")


def _cut(words: str) -> str:
    words = " ".join(words.split())
    return words if len(words) <= WORDS_MAX else words[: WORDS_MAX - 3].rstrip() + "..."


def _rules_path(root: Path) -> Path:
    return root / ".orch" / RULES_FILE


def _rule_words(line: str) -> str:
    """A rule line as a person reads it: no list mark, heading or comment; "" when it is not a rule."""
    s = line.strip()
    if not s or s.startswith(("#", "<!--", "```")):
        return ""
    return re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", s).strip()


def _find(root: Path, ticket: dict, ref: str) -> dict | None:
    """The record a reference points to, as {src, by, at, words}; None when it is not there."""
    if _CHAT_RE.fullmatch(ref):
        for ln in history.lines(root, ticket):
            if isinstance(ln, dict) and ln.get("chat_message") is True and ln.get("id") == ref:
                return {"src": "chat", "line": ln}
        return None
    m = _HIST_RE.fullmatch(ref)
    if m:
        found = [
            ln for ln in history.lines(root, ticket) if isinstance(ln, dict) and ln.get("at") == m.group(1)
        ]
        people = [ln for ln in found if history.is_person_line(ln)]
        if len(people) == 1:  # two person lines with one time stamp: not a stable pointer
            return {"src": "history", "line": people[0]}
        return {"src": "history", "line": found[0]} if len(found) == 1 else None
    m = _RULE_RE.fullmatch(ref)
    if m:
        p = _rules_path(root)
        try:
            text = p.read_text(encoding="utf-8")
            mtime = p.stat().st_mtime
        except (OSError, UnicodeDecodeError):
            return None
        lines = text.splitlines()
        n = int(m.group(1))
        if n > len(lines):
            return None
        at = datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="seconds")
        return {"src": "rules", "by": "rules", "at": at, "words": _rule_words(lines[n - 1])}
    raise Refused(
        "--said takes a chat message id (m_...), history:<time of the person's line> or rules:<line in "
        ".orch/ask-when.md>. Find the id in orch ticket show <id> --json."
    )


def _record(found: dict) -> dict:
    if found["src"] == "rules":
        return found
    ln = found["line"]
    return {
        "src": found["src"],
        "by": ln.get("by") if isinstance(ln.get("by"), str) else "",
        "at": ln.get("at") if isinstance(ln.get("at"), str) else "",
        "words": ln.get("text") if isinstance(ln.get("text"), str) else "",
        **({"name": ln["by_name"]} if isinstance(ln.get("by_name"), str) and ln.get("by_name") else {}),
    }


def quote(root: Path, ticket: dict, ref: str) -> dict:
    """The copy a question keeps for `--said <ref>`: {ref, src, by, name?, at, words, version, goal}.
    Refused when the reference is not there or not a person's own words."""
    ref = (ref or "").strip()
    found = _find(root, ticket, ref)
    key = ticket.get("key") or ticket.get("id")
    if found is None:
        raise Refused(
            f"{ref} is not one line of {key}: name a person's line of this ticket by its id or time "
            f"(orch ticket show {key} --json)."
        )
    rec = _record(found)
    if rec["src"] != "rules" and not history.is_person_line(rec):
        raise Refused(
            f"{ref} was written by {rec['by'] or 'nobody known'}, not a person: "
            "--said quotes only a person's own words."
        )
    if not rec["words"].strip():
        raise Refused(f"{ref} has no words to quote: name a line with the person's words.")
    out = {
        "ref": ref,
        "src": rec["src"],
        "by": rec["by"],
        "at": rec["at"],
        "words": _cut(rec["words"]),
        "version": _sha(rec["words"]),
        "goal": goal_version(ticket),
    }
    if rec.get("name"):
        out["name"] = rec["name"]
    return out


def check(root: Path, ticket: dict, said) -> str | None:
    """Why a kept quote is out of date (one of REASONS), or None when it still holds."""
    if not isinstance(said, dict) or not isinstance(said.get("ref"), str):
        return "gone"
    try:
        found = _find(root, ticket, said["ref"])
    except Refused:
        return "gone"
    if found is None:
        return "gone"
    rec = _record(found)
    if (
        rec["src"] != said.get("src")
        or rec["by"] != said.get("by")
        or _sha(rec["words"]) != said.get("version")
    ):
        return "changed"
    if goal_version(ticket) != said.get("goal"):
        return "goal"
    if rec["src"] != "rules":  # history is in time order: a later line of the same person
        at = str(said.get("at") or "")
        for ln in history.lines(root, ticket):
            if isinstance(ln, dict) and ln.get("by") == said["by"] and history.is_person_line(ln):
                if str(ln.get("at") or "") > at:
                    return "newer"
    return None


def stale(root: Path, ticket: dict, q) -> str | None:
    """Why a question's quote is out of date, else None; a question without a quote is never stale."""
    said = q.get("said") if isinstance(q, dict) else None
    return check(root, ticket, said) if said is not None else None


def _me(root: Path) -> str:
    from orch import whoami

    name = None
    try:
        name = whoami.current(root)
    except Exception:  # who is chosen is only a label: never break the list over it
        name = None
    if not name:
        try:
            name = getpass.getuser()
        except Exception:
            name = ""
    return "human:" + re.sub(r"[^A-Za-z0-9_.@ -]", "_", name)[:64] if name else ""


def shown(root: Path, ticket: dict, q) -> dict | None:
    """What the card shows of a question's quote, for `orch review list --json`:
    {who: you|person|rule, name, at, words (left out when out of date by gone/changed), src, ref, stale}."""
    said = q.get("said") if isinstance(q, dict) else None
    if not isinstance(said, dict):
        return None
    why = check(root, ticket, said)
    by = str(said.get("by") or "")
    if said.get("src") == "rules":
        who, name = "rule", "Team rules"
    elif by and by == _me(root):
        who, name = "you", ""
    else:
        from orch import people

        who = "person"
        name = str(said.get("name") or "") or people.show(root, by).removeprefix("human:")
    out = {
        "who": who,
        "name": name[:60],
        "at": str(said.get("at") or ""),
        "src": str(said.get("src") or ""),
        "ref": str(said.get("ref") or ""),
        "stale": why,
    }
    if why not in ("gone", "changed"):  # words taken away or changed are never shown as theirs
        out["words"] = str(said.get("words") or "")[: WORDS_MAX + 3]
    return out
