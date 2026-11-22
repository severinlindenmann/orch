---
name: orch-skills
description: Use when the person asks which skills, instruction files, connected services or logins the helpers get in this workspace, why a helper does not see a skill, or asks to turn one off or on here. Off is for this workspace only and never deletes anything. Not for writing or editing a skill (do that in its files) and not for usage counts (that is Insights).
metadata:
  owner: "orch"
  status: "active"
---
# orch skills

The Skills page (and `orch skills list`) shows everything a helper gets in this workspace, in four kinds: skills,
instructions, connected services and logins, each from one place: comes with orch, this workspace, shared by the
admin, or this computer. The person turns things off and on there; its clicks run these commands.

## When to use
- The person asks what helpers get here, or why a helper does not see a skill.
- The person asks to turn something off or on here, to delete a skill, to get a deleted one back, or to start a new one.

## Recipes

**See what helpers get** (ids such as `skill:orch:orch-hello`)

    orch skills list
    orch skills history

**Turn off, turn on, delete, restore, new**: tell the person to use the Skills page (a switch per row; Delete at
the bottom of a skill's side panel; the Bin tab with Restore; the New skill button), or to run these in their own
terminal. Only a person can: under a helper tool they are refused.

    orch skills off <id>
    orch skills on <id>
    orch skills delete <id>
    orch skills bin
    orch skills restore <bin id>
    orch skills new <name>

Every change lands in `orch skills history` with who did it.

## Rules
- Off is for this workspace only and never deletes anything. orch's own and the admin's shared skills: orch stops
  linking them here (the files stay). This workspace's and this computer's skills, connected services and the rules
  file in your home: the helper tool's own per-folder switches (orch writes and removes only its own lines).
- A line "<tool> still sees it" means that tool has no such switch yet.
- Delete moves a skill into a bin (a computer skill is kept outside the workspace and goes from every workspace).
  Nothing is purged by itself. Restore never replaces a skill that has the same name now.
- New skill makes `.agents/skills/<name>/SKILL.md` with the standard header, status draft.
- The main orch skill, the workspace's instruction files and logins cannot be turned off here.
