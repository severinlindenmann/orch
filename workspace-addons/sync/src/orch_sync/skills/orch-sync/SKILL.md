---
name: orch-sync
description: Check or change how this computer keeps a private copy of the workspace's tickets with orch sync. Use when the person asks whether their tickets are backed up, or asks to turn the backup on or off. Not for sharing tickets with a team (not available yet) and not for the team code repository.
---
# orch sync

## When to use

- The person asks whether this computer keeps a copy of the tickets, or when it last did.
- The person asks to turn that copy on (on this computer only) or off.

## Recipes

- Run one check now: `orch sync now --json`.
- See decisions waiting for the person: `orch sync needs --json`.
- After the person chooses a copy: `orch sync resolve <path> --keep mine` or `orch sync resolve <path> --keep theirs`. A changed remote asks for another review. Keeping theirs preserves the local artifact with a dated name, or records a ticket history summary.
- A held add-on change needs `orch sync approve <ticket> <addon> --proof-stdin`, with the person's single-use proof over stdin. Never manufacture a proof or write an approval store; agents are refused. The proof is for `addon.act` and the target `sync:<ticket>:<addon>:<canonical-block-sha256>`.
- Use `orch sync approve <ticket> <addon> --ignore` to dismiss the held block; changed content asks again.
- Acknowledge a restored ticket: `orch sync deleted <ticket> --keep`.
- See the settings and the last result: `orch sync status --json`.
- Turn it on for this computer only, every 15 minutes: `orch sync set --mode local --interval 15`.
- Turn it off: `orch sync set --mode off`.

## Rules

- Change the setting only when the person asks for it.
- Copying to another computer or server is a preview and stays off unless the person set it up themselves.
- Team sharing is not available yet; say so instead of trying.
