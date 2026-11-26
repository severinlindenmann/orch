"""Attention groups on Review (ORCH-2184, Focused review C; owner's words of 26 Nov): Quick look, Short
decision, Take your time. Plain rules on what orch already knows about a card, no AI call, no minutes.

- Take your time: a card that puts something live or asks the person to try it themselves, any card whose
  words name words or names, money, production, something that cannot be undone, logins or keys, or something
  others see (Away mode's own list, autoreview.AWAY_STAYS), or a long document.
- Quick look: only with a clear hint that it is small: the Reviewer proposes to accept it, a passed test
  result, or a one-tap question; and never with anything from the Take-your-time list.
- Short decision: everything else. A card orch cannot read plainly (unknown risk) is never a Quick look.

Groups only order the work. They never answer, accept or close anything: what passes by itself stays the
Reviewer setting (workflow.reviewer / reviewer_mode), and neither the Reviewer nor Away mode reads this
module.

`week(root)` counts, for the last 7 days, what tells whether quick answers were too quick: answers taken
back (undos), finished work sent back after it was accepted, and deadlines (`orch ask --due`) that passed
unanswered.
"""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path

GROUPS = {"quick": "Quick look", "short": "Short decision", "time": "Take your time"}
GROUP_ORDER = tuple(GROUPS)
DOC_WORDS_LONG = 300  # a document longer than this is not read in a glance
ROUND = 5  # cards in one round (owner, 26 Nov)

# why a card is in its group, in plain words (the card shows "In <group>: <why>.")
_WHY_HITS = {
    "words or names": "it is about words or names",
    "money": "costs money",
    "production": "goes live or out to others",
    "cannot be undone": "hard to take back",
    "logins or keys": "touches logins or keys",
    "outside-visible": "others can see it",
}
VAGUE = "a go-ahead without the steps"  # Away mode's hit for words that do not say what happens: never quick
_WHY_KIND = {"put_live": "it puts something live", "try_yourself": "you try it yourself"}


def _strings(v, depth: int = 0) -> list[str]:
    if depth > 6:
        return ["\x00"]  # too deep to read: never plain, so never a Quick look
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x, depth + 1)]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x, depth + 1)]
    return []


def _doc_words(card: dict) -> int:
    pv = card.get("preview") if isinstance(card.get("preview"), dict) else {}
    return sum(len(s.split()) for s in _strings(pv))


def group_of(item: dict) -> dict:
    """{group: quick|short|time, name, why} for one `orch review list` item (review.stack's row)."""
    from orch import autoreview

    item = item if isinstance(item, dict) else {}
    card = item.get("card") if isinstance(item.get("card"), dict) else {}
    kind = (item.get("card_kind") or {}).get("kind") if isinstance(item.get("card_kind"), dict) else None
    text = unicodedata.normalize(
        "NFKC",
        " ".join(
            _strings([item.get("text"), card, item.get("links"), item.get("facts"), item.get("if_wait")])
        ),
    )

    def out(group: str, why: str) -> dict:
        return {"group": group, "name": GROUPS[group], "why": why}

    if kind in _WHY_KIND:
        return out("time", _WHY_KIND[kind])
    hits = autoreview._away_hits(text)
    risky = [h for h in hits if h != VAGUE]
    if risky:
        return out("time", _WHY_HITS.get(risky[0], risky[0]))
    if kind == "document" and _doc_words(card) > DOC_WORDS_LONG:
        return out("time", "long to read")
    plain = bool(autoreview.PLAIN_TEXT.fullmatch(text)) and len(text) <= autoreview.AWAY_TEXT_MAX
    if plain and not hits and kind != "stuck":  # a vague go-ahead is not known to be small
        pr = item.get("proposal") if isinstance(item.get("proposal"), dict) else {}
        if pr.get("verdict") == "accept":
            return out("quick", "the Reviewer proposes to accept")
        if kind == "check_result" and _passed(card):
            return out("quick", "small and tested")
        if item.get("one_tap") is True:
            return out("quick", "one tap, and you can undo it")
    return out("short", "one clear question" if kind in ("question", "choice") else "needs a look")


def _passed(card: dict) -> bool:
    """A test result that says it passed: a done status and no red or warning chip."""
    pv = card.get("preview") if isinstance(card.get("preview"), dict) else {}
    st = pv.get("status") if isinstance(pv.get("status"), dict) else {}
    chips = [c for c in pv.get("chips") or [] if isinstance(c, dict)]
    if st and st.get("tone") not in (None, "done"):
        return False
    if any(c.get("tone") in ("bad", "warn") for c in chips):
        return False
    return bool(st) or bool(chips)


def tag(items: list[dict]) -> list[dict]:
    """Adds `attention` to every stack item (additive; old readers ignore it). Returns the same list."""
    for it in items:
        it["attention"] = group_of(it)
    return items


# ---------------------------------------------------------------- the weekly measure


def _at(s) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def week(root: Path, now: datetime | None = None) -> dict:
    """{since, undos, sent_back_later, missed_deadlines}: counts for the 7 days up to now.
    undos: history lines "Undone by you: ..." (an answer or accept of the Reviewer or Away mode taken back).
    sent_back_later: finished work opened again after it was done ("Status done -> ...").
    missed_deadlines: questions whose `due` passed in these 7 days before anyone answered."""
    from orch import autoreview, history, tickets

    now = (now or datetime.now(UTC)).astimezone(UTC)
    since = now - timedelta(days=7)
    undos = back = missed = 0
    for t in tickets.list_all(root):
        if not isinstance(t, dict):
            continue
        for h in history.lines(root, t):
            if not isinstance(h, dict):
                continue
            at = _at(h.get("at"))
            if at is None or not (since <= at <= now):
                continue
            text = str(h.get("text") or "")
            if text.startswith(autoreview.UNDONE_LINE):
                undos += 1
            elif text.startswith("Status done -> "):
                back += 1
        for q in t.get("questions") or []:
            if not isinstance(q, dict):
                continue
            due = _at(q.get("due"))
            if due is None or not (since <= due <= now):
                continue
            answered = _at(q.get("at")) if q.get("answer") is not None else None
            if answered is None or answered > due:
                missed += 1
    return {
        "since": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "undos": undos,
        "sent_back_later": back,
        "missed_deadlines": missed,
    }
