"""Which model a ticket's helper runs on: Opus for hard work, Sonnet for the rest (moved up when hard).

orch picks before every start while no person chose (ticket field `model`, by "orch"); a person's choice
stays until they set it back to auto. Only adapters with `model_args` get the model passed; the others
keep their own default. Never Fable (or any other model) by default: the pick is Sonnet or Opus.
"""

from __future__ import annotations

import re

MODELS = ("sonnet", "opus")
LABELS = {"sonnet": "Sonnet", "opus": "Opus"}
BY_ORCH = "orch"

# Hard work starts on Opus at once (owner 16 Nov, ORCH-82): design, security, relay or publish, a migration
# or rewrite, a crash, race or flaky test, or part of a bigger plan. Everything else starts on Sonnet, also
# when its size is unclear; the helper (or orch, after two failed checks) moves it up when it turns hard.
_HARD = re.compile(
    r"\b(design\w*|architect\w*|redesign\w*|security|secure|secret\w*|login|password\w*|auth|"
    r"authenticat\w*|authori[sz]\w*|encrypt\w*|decrypt\w*|crypto\w*|relay|publish\w*|migrat\w*|"
    r"rewrite|crash\w*|race|flaky|deadlock\w*|epic)\b",
    re.I,
)
# Signals for small, clear work (only for the plain reason shown with the pick).
_SMALL = re.compile(
    r"\b(typo\w*|wording|words?|rename|label|text|copy|spelling|tooltip|comment|readme|docs?|"
    r"one.file|one.line|small|tiny|tweak|colou?r|icon|bump|version|test\w*|check\w*|review\w*)\b",
    re.I,
)
UP_PREFIX = "Model moved up to Opus"


def _text(ticket: dict) -> str:
    return " ".join(str(ticket.get(k) or "") for k in ("title", "note", "description", "done_when")).strip()


def pick(ticket: dict) -> tuple[str, str]:
    """(model, why in plain words) from the ticket alone. Hard work goes to Opus, the rest to Sonnet."""
    hard = _HARD.search(_text(ticket))
    if hard:
        return "opus", f"it mentions {hard.group(0).lower()}"
    if ticket.get("parent") or ticket.get("ext") or ticket.get("epic"):
        return "opus", "it is part of a bigger plan"
    small = _SMALL.search(_text(ticket))
    if small:
        return "sonnet", f"a small change ({small.group(0).lower()})"
    return "sonnet", "nothing hard named yet; it moves up to Opus when it turns hard"


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
    """'Opus (picked by orch)' / 'Sonnet (chosen by Severin)', or None when nothing was picked yet."""
    m = chosen(ticket)
    if not m:
        return None
    who = "picked by orch" if m.get("by") == BY_ORCH else f"chosen by {_who(m.get('by'))}"
    return f"{LABELS[m['name']]} ({who})"


def _who(by: str | None) -> str:
    by = str(by or "a person")
    return by.split(":", 1)[1] if by.startswith("human:") else by
