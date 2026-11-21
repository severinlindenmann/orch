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
- The person asks to turn something off or on here.
- The person asks who changed what on the Skills page.

## Recipes

    orch skills list                      # everything helpers get here, with ids (add --json for the page's data)
    orch skills off <id>                  # in the person's own terminal only, e.g. skill:orch:orch-hello
    orch skills on <id>
    orch skills history                   # who turned what off or on

Tell the person to use the switch on the Skills page; under a helper tool `on` and `off` are refused.

## Rules
- Off is for this workspace only and never deletes a file.
- orch's own and the admin's shared skills: orch stops linking them here (the files stay).
- This workspace's and this computer's skills, connected services and the rules file in your home: the helper
  tool's own per-folder switches in its local settings file (orch writes and removes only its own lines).
- A line "<tool> still sees it" means that tool has no such switch yet.
- The main orch skill, the workspace's instruction files and logins cannot be turned off here.
- Only a person turns things off or on; every change lands in the history with who did it.
