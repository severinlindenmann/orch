"""The helper tools this page can switch, from the core's tool data (agents/switches.json through
`adapters.folder_switches()`). The add-on names no tool itself: labels, files and keys all come from there."""

from __future__ import annotations

import os
from pathlib import Path


def all_tools() -> dict[str, dict]:
    try:
        from orch import adapters

        return adapters.folder_switches()
    except Exception:  # noqa: BLE001  an older core without the data: nothing can be switched
        return {}


def here(root: Path) -> dict[str, dict]:
    """{name: tool} of the tools used here (found or chosen); none found: the tool the data marks as default."""
    known = all_tools()
    try:
        from orch import skills

        found = [n for n in skills.detected_agents(root) if n in known]
    except Exception:  # noqa: BLE001
        found = []
    if not found:
        found = [n for n, t in known.items() if t["switches"].get("default")]
    return {n: known[n] for n in found}


def fill(text: str, home: Path, root: Path | None = None, tool: dict | None = None) -> str:
    """{home}, {folder}, {label} and {tool_home} in a data string."""
    out = text.replace("{home}", str(home))
    if root is not None:
        out = out.replace("{folder}", str(root))
    if tool is not None:
        out = out.replace("{label}", tool["label"])
        th = tool["switches"].get("tool_home")
        if isinstance(th, dict) and "{tool_home}" in out:
            env = os.environ.get(th.get("env") or "")
            out = out.replace("{tool_home}", env or fill(th.get("default", ""), home))
    return out
