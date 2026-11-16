"""Which model a ticket's helper runs on: Sonnet for small, clear work, Opus for the rest.

orch picks before every start while no person chose (ticket field `model`, by "orch"); a person's choice
stays until they set it back to auto. Only adapters with `model_args` get the model passed; the others
keep their own default. Never Fable (or any other model) by default: the pick is Sonnet or Opus.
"""

from __future__ import annotations

import re

MODELS = ("sonnet", "opus")
LABELS = {"sonnet": "Sonnet", "opus": "Opus"}
BY_ORCH = "orch"

# Signals for hard work: design, security, several parts, or unclear what to do.
_HARD = re.compile(
    r"\b(design|architect\w*|security|secure|secret\w*|auth\w*|login|password|encrypt\w*|crypt\w*|"
    r"relay|publish|permission\w*|privacy|migrat\w*|refactor\w*|rewrite|redesign|plan|epic|concept|"
    r"investigat\w*|diagnos\w*|debug\w*|race|flaky|deadlock|performance|slow|crash\w*|"
    r"unclear|why|decide|decision|research|spec|protocol|sync|windows|ios|android|mobile|phone|"
    r"several|multiple|across|end.to.end|e2e|feature|new add-on|add-on)\b",
    re.I,
)
# Signals for small, clear work.
_SMALL = re.compile(
    r"\b(typo\w*|wording|word|words|rename|label|text|copy|spelling|tooltip|comment|readme|doc|docs|"
    r"one.file|one.line|small|tiny|tweak|colou?r|icon|bump|version)\b",
    re.I,
)
SHORT = 300  # characters of the person's text: longer means more than a small fix


def _text(ticket: dict) -> str:
    return " ".join(str(ticket.get(k) or "") for k in ("title", "note", "description", "done_when")).strip()


def pick(ticket: dict) -> tuple[str, str]:
    """(model, why in plain words) from the ticket alone. Unclear work goes to Opus."""
    text = _text(ticket)
    steps = [c for c in ticket.get("checklist") or [] if not c.get("wont_do")]
    hard = _HARD.search(text)
    if hard:
        return "opus", f"it mentions {hard.group(0).lower()}"
    if ticket.get("parent") or ticket.get("plan") or ticket.get("ext"):
        return "opus", "it is part of a bigger plan"
    if len(steps) > 4:
        return "opus", f"it has {len(steps)} steps"
    if len(text) > SHORT:
        return "opus", "the request is long"
    small = _SMALL.search(text)
    if small:
        return "sonnet", f"a small change ({small.group(0).lower()})"
    if steps and len(steps) <= 2:
        return "sonnet", "a short, clear task"
    return "opus", "not clear yet how big it is"


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
