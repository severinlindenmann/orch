"""orch init: set up the project folder. Safe to run again."""

from __future__ import annotations

from pathlib import Path

from orch import skills


def init(root: Path) -> list[str]:
    """Returns plain-words lines about what is in place."""
    (root / ".orch" / "tickets").mkdir(parents=True, exist_ok=True)
    src = skills.packaged_skills_dir() / "orch"
    skills.install_skill(root, "orch", src)
    skills.set_block(root, "orch", skills.read_block(src, "orch"))
    skills.link_claude_skills(root)
    skills.ensure_claude_md(root)
    skills.ensure_gitignore(root)
    return [
        "Skill       .agents/skills/orch/SKILL.md",
        "AGENTS.md   orch entry",
        "Claude      .claude/skills -> .agents/skills, CLAUDE.md reads AGENTS.md",
        "Gitignore   .orch/secrets/ and other local files",
        "Tickets     .orch/tickets/",
    ]
