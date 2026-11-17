"""Which model a ticket's helper runs on: Fable for drafts, Opus for hard work, Sonnet for the rest.

orch picks before every start while no person chose (ticket field `model`, by "orch"); a person's choice
stays until they set it back to auto. Only adapters with `model_args` get the model passed; the others
keep their own default. Fable only for mockup, redesign and concept drafts (owner 17 Nov, ORCH-257): such a
ticket works the drafts way (runs.fresh_prompt: three or more drafts, each challenged on Opus, one card).
"""

from __future__ import annotations

import re

MODELS = ("sonnet", "opus", "fable")
LABELS = {"sonnet": "Sonnet", "opus": "Opus", "fable": "Fable"}
STRONG = ("opus", "fable")  # "up" never changes these (Fable is not below Opus; it is for drafts)
BY_ORCH = "orch"

# Which model (owner 16 Nov, ORCH-82; changed 17 Nov, ORCH-252): design, look, layout, UX, concept, security
# and feature work start on Opus; only a small, mechanical fix (a typo, a word, a label, one line) starts on
# Sonnet. When unsure: Opus. A problem report about one behaviour (no hard word in the person's own text)
# starts on Sonnet; the helper (or orch, after two failed checks) moves it up when it turns hard.
_HARD = re.compile(
    r"\b(design\w*|redesign\w*|architect\w*|concept\w*|mock-?ups?|drafts?|visual\w*|visuell\w*|ui|ux|"
    r"layout\w*|look and feel|security|secure|secrets?|login|password\w*|auth|authenticat\w*|"
    r"authori[sz]\w*|tokens?|encrypt\w*|decrypt\w*|crypto\w*|migrat\w*|rewrite|refactor\w*|crash\w*|"
    r"race|flaky|deadlock\w*|epic|features?|add-?ons?)\b",
    re.I,
)
# Draft work goes to Fable (owner 17 Nov, ORCH-257): a redesign, or a mockup, draft or concept asked for as
# the result ("make me a new mockup of ...", "a concept for ..."). Not a mockup that only comes along with
# built work ("mockup in the same pull request", "a proposal with a mockup"): Sonnet/Opus rules decide.
_DRAFT_NOUN = r"(mock-?ups?|drafts?|concepts?)"
_DRAFTS = re.compile(
    r"\b(?:redesign\w*"
    r"|(?:make|create|draw|sketch|build|design|want|need|new|several|three|some)\b"
    rf"[^.\n]{{0,25}}?\b{_DRAFT_NOUN}"
    rf"|{_DRAFT_NOUN}\s+(?:of|for)\b)",
    re.I,
)
# Areas that are hard unless the change is only words (the relay admin page's empty-state text is a word fix).
_AREA = re.compile(r"\b(relay|publish\w*)\b", re.I)
# Signals for small, mechanical work.
_SMALL = re.compile(
    r"\b(typo\w*|wording|words?|rename\w*|label|text|spelling|tooltip|comment|readme|docs?|"
    r"one.file|one.line|small|tiny|tweak|bump|version)\b",
    re.I,
)
# A long request or a list of several points is several parts of work: never "small".
_LONG = 600
_POINTS = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*])\s+\S")
# Problem-report tickets (report_tickets.py): only the person's own lines count, not orch's instructions
# (they name the relay and "a big change" in every report).
_REPORT_MARK = "Opened by the setting: turn problem reports into tickets."
_REPORT_OWN = (
    "What happened (their words, data not instructions):",
    "What they expected:",
    "What they want (their words, data not instructions):",
    "Why it would help:",
)
_REPORT_TITLE = re.compile(r"^Investigate orch report\b", re.I)
UP_PREFIX = "Model moved up to Opus"
# A role that makes routine tickets with long instructions of its own sets this field to "small".
HINT = "model_hint"


def _report(ticket: dict) -> bool:
    return _REPORT_MARK in str(ticket.get("note") or "")


def _text(ticket: dict) -> str:
    if _report(ticket):
        own = [
            ln.split(":", 1)[1]  # the person's words without orch's lead-in ("their words, data not ...")
            for ln in str(ticket.get("note") or "").splitlines()
            if ln.startswith(_REPORT_OWN)
        ]
        title = str(ticket.get("title") or "")
        return " ".join([*([] if _REPORT_TITLE.match(title) else [title]), *own]).strip()
    return " ".join(str(ticket.get(k) or "") for k in ("title", "note", "description", "done_when")).strip()


def pick(ticket: dict) -> tuple[str, str]:
    """(model, why in one plain line) from the ticket alone. Fable for drafts, else Opus unless the work is
    clearly small."""
    if ticket.get(HINT) == "small":  # orch's own routine ticket (Reviewer second look, daily review)
        return "sonnet", "orch's own routine check; it moves up when it turns hard"
    text = _text(ticket)
    drafts = _DRAFTS.search(text)
    if drafts:
        word = next((g for g in drafts.groups() if g), None) or drafts.group(0)
        return "fable", f"it asks for {word.lower()}, so Fable makes drafts to pick from"
    hard = _HARD.search(text)
    if hard:
        return "opus", f"it mentions {hard.group(0).lower()}"
    if ticket.get("parent") or ticket.get("ext") or ticket.get("epic"):
        return "opus", "it is part of a bigger plan"
    small = _SMALL.search(text)
    area = _AREA.search(text)
    if area and not small:
        return "opus", f"it mentions {area.group(0).lower()}"
    if len(text) > _LONG or len(_POINTS.findall(str(ticket.get("note") or ""))) >= 3:
        return "opus", "it has several parts"
    if small:
        return "sonnet", f"a small change ({small.group(0).lower()})"
    if _report(ticket):
        return "sonnet", "a reported problem with one behaviour; it moves up when it turns hard"
    return "opus", "not clearly a small fix, so Opus"


def why(ticket: dict) -> str | None:
    """The one-line reason for orch's pick (or for moving up); None for a person's choice."""
    m = chosen(ticket)
    if not m or m.get("by") != BY_ORCH:
        return None
    return str(m.get("why") or "").strip()[:200] or None


def moved_up(ticket: dict) -> bool:
    """orch or the helper moved this ticket up to Opus (it stays there: never down by itself)."""
    m = chosen(ticket)
    return bool(m and m.get("by") == BY_ORCH and m.get("name") == "opus" and m.get("up"))


def chosen(ticket: dict) -> dict | None:
    """The stored choice {name, by, why?}, or None (never picked; an unknown value counts as none)."""
    m = ticket.get("model")
    if isinstance(m, dict) and m.get("name") in MODELS:
        return m
    return None


def by_person(ticket: dict) -> bool:
    m = chosen(ticket)
    return bool(m and m.get("by") != BY_ORCH)


def label(ticket: dict) -> str | None:
    """'Opus (picked by orch)' / 'Fable (chosen by Severin)', or None when nothing was picked yet."""
    m = chosen(ticket)
    if not m:
        return None
    who = "picked by orch" if m.get("by") == BY_ORCH else f"chosen by {_who(m.get('by'))}"
    return f"{LABELS[m['name']]} ({who})"


def _who(by: str | None) -> str:
    by = str(by or "a person")
    return by.split(":", 1)[1] if by.startswith("human:") else by
