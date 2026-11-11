---
name: orch-sync
description: Check or change how this computer keeps a private copy of the workspace's tickets with orch sync. Use when the person asks whether their tickets are backed up, or asks to turn the backup on or off. Not for sharing tickets with a team (not available yet) and not for the team code repository.
---
# orch sync

## When to use

- The person asks whether this computer keeps a copy of the tickets, or when it last did.
- The person asks to turn that copy on (on this computer only) or off.

## Recipes

- See the settings and the last result: `orch sync status --json`.
- Turn it on for this computer only, every 15 minutes: `orch sync set --mode local --interval 15`.
- Turn it off: `orch sync set --mode off`.

## Rules

- Change the setting only when the person asks for it.
- Copying to another computer or server is a preview and stays off unless the person set it up themselves.
- Team sharing is not available yet; say so instead of trying.
