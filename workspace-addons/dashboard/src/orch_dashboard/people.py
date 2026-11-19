"""Who is using this dashboard ("You: Anna"). The record lives in orch core (orch.people) since `orch init`
asks the name too; this module keeps the dashboard's import path."""

from __future__ import annotations

from orch.people import MAX_PEOPLE, BadName, choose, clean_name, current, load

__all__ = ["MAX_PEOPLE", "BadName", "choose", "clean_name", "current", "load"]
