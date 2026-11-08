"""The message box: a line goes through `orch run send <ticket>`; core pastes it into a live session when it is idle,
or delivers it with the next one-shot turn. This module only words what happened, in plain words."""

from __future__ import annotations


def note(result: dict | None, running: bool, live: bool, asking: bool = False) -> str:
    """One short line for the person, from core's answer to `orch run send`."""
    result = result or {}
    if result.get("delivered"):
        return "Sent."
    if asking:
        return "Answer the question — Claude continues right after."
    if running:
        return "Goes in after this step."
    return "Saved for the next run."
