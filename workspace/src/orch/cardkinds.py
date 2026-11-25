"""The twelve kinds of Review card in four families (owner's pick R3 B, 25 Nov 2026), and the order the Review
list shows them in (R2 A: what holds up work first, then by what the person does).

orch picks the kind from what a card carries; a helper never names it (R5 A). The names are plain words
that fit any work (taxes, a campaign, a trip, code): a person in marketing reads the list a developer reads.

Families and kinds (`card_kind` on every `orch review list` item, additive):

- answer (you decide): question, choice
- look (you judge a result): before_after, pictures, document, changed_words, numbers, check_result
- click (only you may press it): put_live, run_it
- help (the work needs you in person): try_yourself, stuck

Lanes (the list's groups, in this order): holds_up (every answer and every stuck card: work waits on it now),
click, help, look, and proposed (in Reviewer mode "propose": what the Reviewer checked and proposes).
"""

from __future__ import annotations

import re

from orch.errors import Refused

FAMILIES = {
    "answer": "Decide",
    "look": "Look at the result",
    "click": "Only you can press it",
    "help": "Needs you in person",
}
KINDS = {  # kind -> (family, the name on the card)
    "question": ("answer", "Question"),
    "choice": ("answer", "Choice"),
    "before_after": ("look", "Before and after"),
    "pictures": ("look", "Pictures"),
    "document": ("look", "Document"),
    "changed_words": ("look", "Changed words"),
    "numbers": ("look", "Numbers"),
    "check_result": ("look", "Check result"),
    "put_live": ("click", "Put it live"),
    "run_it": ("click", "Run it"),
    "try_yourself": ("help", "Try it yourself"),
    "stuck": ("help", "Stuck"),
}
LANES = {  # lane -> the group's heading, in the order the list shows them
    "holds_up": "Holds up work now",
    "click": FAMILIES["click"],
    "help": FAMILIES["help"],
    "look": FAMILIES["look"],
    "proposed": "Checked by the Reviewer",
}
LANE_ORDER = tuple(LANES)
_PICTURE_FILES = ("img", "page")
_STUCK_QUESTION_KINDS = ("automation:failure",)


def _of_preview(pv) -> str | None:
    """The kind a card's preview shows, or None when it shows nothing a person looks at."""
    if not isinstance(pv, dict):
        return None
    t = pv.get("type")
    if t == "compare":
        return "before_after"
    if t in ("img", "page"):
        return "pictures"
    if t == "table":
        return "numbers"
    if t == "options":
        opts = pv.get("options") or []
        pics = pv.get("before") or any(isinstance(o, dict) and o.get("preview") for o in opts)
        return "choice" if pics else "question"
    if t == "doc":
        if pv.get("chart"):
            return "numbers"
        if pv.get("diff"):
            return "changed_words"
        if pv.get("status") or pv.get("flow"):
            return "check_result"
        return "document"
    return None


def _of_files(files) -> str | None:
    kinds = [f.get("type") for f in files or [] if isinstance(f, dict)]
    if any(k in _PICTURE_FILES for k in kinds):
        return "pictures"
    return "document" if kinds else None


def kind_of(card, *, question_kind: str | None = None, merge: bool = False) -> str:
    """The card's kind (one of KINDS). card: the stored or shown card; question_kind: the question's own kind
    (`orch ask --kind`); merge: the question carries a merge (a release only the person may make)."""
    card = card if isinstance(card, dict) else {}
    k = card.get("kind")
    if k == "stuck" or question_kind in _STUCK_QUESTION_KINDS:
        return "stuck"
    if k == "link" or merge:
        return "put_live"
    if k == "run":
        run = card.get("run") if isinstance(card.get("run"), dict) else {}
        return "run_it" if run.get("class") == "orch" else "try_yourself"
    if k == "choice":
        return (
            _of_preview(card.get("preview"))
            if (card.get("preview") or {}).get("type") == "options"
            else "choice"
        )
    if k == "check":
        got = _of_files(card.get("files"))
        if got:
            return got
        pv = card.get("preview") if isinstance(card.get("preview"), dict) else {}
        return "check_result" if pv.get("chips") or pv.get("status") else "document"
    got = _of_preview(card.get("preview")) or _of_files(card.get("files"))
    if got:
        return got
    return "question" if k == "draft" and not card.get("preview") else "document"


def look(card, *, question_kind: str | None = None, merge: bool = False, proposed: bool = False) -> dict:
    """{family, kind, name, lane}: what every surface shows and groups by."""
    kind = kind_of(card, question_kind=question_kind, merge=merge)
    family, name = KINDS[kind]
    lane = "proposed" if proposed else "holds_up" if family == "answer" or kind == "stuck" else family
    return {"family": family, "kind": kind, "name": name, "lane": lane}


def lane_rank(item: dict) -> int:
    """Where an `orch review list` item sorts (its lane's place); without a card_kind it goes first."""
    lane = (item.get("card_kind") or {}).get("lane") if isinstance(item, dict) else None
    return LANE_ORDER.index(lane) if lane in LANES else 0


# ---------------------------------------------------------------- what orch refuses to put on Review (R5 A)

QUESTION_WORDS_MAX = 40
_STATE_ONLY = re.compile(
    r"\b(?:is|are|was|has been|have been) (?:now |still |all )?"
    r"(?:paused|offline|stopped|down|done|finished|complete|ready|running|on hold)\b"
    r"|\bfor your information\b|\bfyi\b|\bno action (?:is )?needed\b|\bnothing to (?:do|decide)\b"
    r"|\bjust so you know\b|\bjust letting you know\b",
    re.I,
)


def refuse_bad_question(text: str, options: list[str], card: bool) -> None:
    """The refusals of `orch ask` (owner's pick R5 A, 25 Nov 2026), each with the next step: a question
    longer than one short sentence, and a report of a state with nothing to answer. A question without
    answers to pick gets the next step instead (ASK_HINT): a free answer in the person's own words stays
    possible (a tax number, an address), and existing helpers and add-ons ask such questions. A card brings
    its own answers, so only the length applies to it."""
    words = len((text or "").split())
    if words > QUESTION_WORDS_MAX:
        raise Refused(
            f"A question is one short sentence (at most {QUESTION_WORDS_MAX} words; this one has {words}). "
            "Put the steps or details in the ticket summary or a file on a card, and ask in one sentence."
        )
    if card:
        return
    if not options and "?" not in (text or "") and _STATE_ONLY.search(text or ""):
        raise Refused(
            "This reports a state; there is nothing to answer, so it is not a question. "
            'Write it in the ticket summary: orch ticket summary <id> "<what happened>".'
        )


ASK_HINT = (
    "Next: a question with 2 to 4 --option and a --recommend is answered in one tap"
    " on the computer and the phone."
)
