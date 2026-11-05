"""orch init: set up the project folder. Safe to run again."""

from __future__ import annotations

from pathlib import Path

from orch import skills
from orch.errors import Refused


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


def choose_agent(root: Path, yes: bool = False, interactive: bool = False) -> str:
    """Which agent does the work here: asked once (found agents + Other); --yes takes the first found.
    Returns one plain line to show."""
    from orch import adapters, config

    cur = config.agent_name(root)
    if cur:
        try:
            adapters.load(cur, root)
            return f"Agent: {adapters.load(cur, root)['label']}."
        except Refused:
            pass  # the saved name no longer exists: ask again
    found = [r for r in adapters.detect() if r["found"]]
    if not found:
        if interactive and not yes:
            return _other(root)
        return "No agent found; set one later: orch config set workspace.agent <name>"
    if yes or not interactive:
        _save(root, found[0]["name"])
        return f"Agent: {found[0]['label']} (found first)."
    print("Which agent does the work?")
    for i, r in enumerate(found, 1):
        print(f"  {i}) {r['label']}  (found{', ' + r['version'] if r['version'] else ''})")
    print(f"  {len(found) + 1}) Other: type its command")
    ans = input("Pick [1]: ").strip() or "1"
    if ans.isdigit() and 1 <= int(ans) <= len(found):
        _save(root, found[int(ans) - 1]["name"])
        return f"Agent: {found[int(ans) - 1]['label']}."
    if ans == str(len(found) + 1):
        return _other(root)
    raise Refused(f"'{ans}' is not on the list. Run orch init again.")


def _save(root: Path, name: str) -> None:
    from orch import config

    config.set_key(root, "workspace", "agent", name)


def _other(root: Path) -> str:
    from orch import adapters, config

    name = input("Name for it [my-agent]: ").strip() or "my-agent"
    if not config.NAME_RE.match(name):
        raise Refused(f"'{name}' is not a name orch can use. Use lowercase letters, digits and '-'.")
    if name in adapters.builtin_names() or name in config.agent_entries(root):
        raise Refused(f"There is already an agent called '{name}'. Pick another name; nothing was changed.")
    cmd = input("Command (use {prompt} where the task goes): ").strip()
    if not cmd:
        return "No agent chosen; set one later: orch config set workspace.agent <name>"
    config.add_agent(root, name, cmd)
    _save(root, name)
    return f"Agent: {name} (starts fresh each run; it cannot continue a conversation)."
