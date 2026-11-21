"""What the Skills add-on knows about each helper tool, in one place (the rule: tool names live only in adapters.py
and agents.json). The rest of the add-on asks this module and names no tool itself.

Today one tool has per-folder switches orch can write (its local settings file in the workspace); the other tools
are listed so the page can say what each of them still sees.
"""

from __future__ import annotations

from pathlib import Path

TOOLS = {"claude": "Claude", "codex": "Codex"}  # tool id -> the word on the page
SWITCHING = "claude"  # the tool whose own per-folder switches orch writes
READS_SHARED_FOLDER = "codex"  # reads .agents/skills itself, so a shared folder stays visible to it when off
SETTINGS = Path(".claude") / "settings.local.json"  # the switching tool's local settings in the workspace
SETTINGS_SHOWN = ".claude/settings.local.json"
SKILL_DIRS = (Path(".agents") / "skills", Path(".claude") / "skills")  # where helpers find this workspace's skills
INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "CLAUDE.local.md", "AGENTS.local.md")
HOME_RULES = (".claude", "CLAUDE.md")  # the person's own rules for every project, under their home
HOME_RULES_SHOWN = "~/.claude/CLAUDE.md"
HOME_RULES_TEXT = "Your own rules for Claude, read in every folder on this computer."
RULES_EXCLUDES = "claudeMdExcludes"  # the settings key that leaves a rules file out
HAND = f"Turned off by hand in {SETTINGS_SHOWN}"


def switching_label() -> str:
    return TOOLS[SWITCHING]
