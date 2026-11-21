"""Who is using this dashboard ("You: Anna"). The record lives in orch core (orch.people) since `orch init`
asks the name too; this module keeps the dashboard's import path. orch is read on first use, never at import
(the dashboard's other core reads do the same), so the page server starts without orch on its import path."""

from __future__ import annotations

_NAMES = ["MAX_PEOPLE", "BadName", "choose", "clean_name", "current", "load"]


def __getattr__(name: str):
    if name in _NAMES:
        from orch import people

        return getattr(people, name)
    raise AttributeError(name)
