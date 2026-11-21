---
name: orch-skills
description: Use when the person asks which skills, instruction files, connected services or logins the helpers get in this workspace, why a helper does not see a skill, whether a connected service needs a sign-in, or asks to turn one off or on here or to remove a skill the admin shares. Off is for this workspace only. Not for writing or editing a skill (do that in its files) and not for usage counts (that is Insights).
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
- The person asks to turn something off or on here, or to remove a skill the admin shares.
- The person asks whether a connected service is signed in.

## Recipes

    orch skills list                      # everything, with ids (e.g. skill:orch:orch-hello) and what needs a look
    orch skills off <id>                  # the person, in their own terminal (or the switch on the page)
    orch skills on <id>
    orch skills remove skill:admin:<name> # a shared skill out of this workspace; relay updates skip it
    orch skills restore skill:admin:<name>
    orch skills check service:<where>:<name>   # ask the helper tool once which services need a sign-in
    orch skills history                   # who changed what

## Rules
- Only a person turns things off or on, removes or brings back: under a helper tool these commands are refused.
  Tell the person to use the Skills page.
- orch's own and the admin's shared skills: off means orch stops linking them here (the files stay).
- Other skills, services and your rules file: the helper tool's own per-folder switches (orch writes and removes
  only its own lines). "still sees it" on a row means that tool has no such switch; the panel says why.
- Logins are key profiles: off means helpers may use it only through its own command (or not at all). The switch
  counts for this workspace only.
- The sign-in itself happens in the helper tool (`/mcp`); orch only shows the state.
- The main orch skill and the workspace's instruction files cannot be turned off here.
