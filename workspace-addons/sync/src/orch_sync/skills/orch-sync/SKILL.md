---
name: orch-sync
description: Check or change how this computer keeps a private copy of the workspace's tickets with orch sync. Use when the person asks whether their tickets are backed up, or asks to turn the backup on or off. Not for sharing tickets with a team (not available yet) and not for the team code repository.
---
# orch sync

## When to use

- The person asks whether this computer keeps a copy of the tickets, or when it last did.
- The person asks to turn that copy on (on this computer only) or off.

## Recipes

- Sync runs in the background once it is on: on this computer only it saves what changed every 5 minutes at most; with a remote every 5, 15 or 60 minutes. While the remote can't be reached it tries again after 1, 2, 4 minutes (never more often), and it does nothing while it waits for a person's choice.
- See whether it runs, when it last synced and when it runs next: `orch sync status --json` (`running`, `last_ok`, `last_try`, `last_error`, `ahead`, `behind`, `paused`, `next_run`).
- Run one sync now: `orch sync now --json` (wakes the background sync when it runs, else syncs once and prints the result).
- Start or stop the background sync here: `orch sync start` / `orch sync stop` (`orch start` starts it with the other add-ons). Start is refused while sync is off. Stop lets the sync that is running finish first, so it can take a moment.
- Change how often a remote sync runs: `orch sync set --interval 15` (5, 15 or 60 minutes). Local sync always runs every 5 minutes at most, so `--interval` is refused there.
- See decisions waiting for the person: `orch sync needs --json`.
- After the person chooses a copy: `orch sync resolve <path> --keep mine` or `orch sync resolve <path> --keep theirs`. A changed remote asks for another review. Keeping theirs preserves the local artifact with a dated name, or records a ticket history summary.
- Keeping their copy of a ticket is the person's decision: `orch sync resolve <path> --keep theirs --proof-stdin`. The proof is for `addon.act` and the target `sync:keep-theirs:<sha256>` (the sha256 of the path and the chosen bytes, joined by NUL). Agents are refused.
- The ticket counter is the person's decision too: `orch sync resolve ticket-counter.json --keep theirs --proof-stdin` always, and `--keep mine --proof-stdin` when sync paused because "Ticket numbers jumped far ahead on the other computer". The proof is for `addon.act` and the target `sync:keep-theirs-counter:<paused-remote-sha>` or `sync:keep-mine-counter:<paused-remote-sha>`. Agents are refused; never choose it for the person.
- A file name that differs from a local one only in capital letters is the person's choice: `orch sync resolve <path> --keep-local-name --proof-stdin` (the other computer's name is not applied while the remote stays as it is) or `orch sync resolve <path> --rename-local "<new name>" --proof-stdin` (then both arrive). Agents are refused; `--keep` is refused for these files.
- A held add-on change needs `orch sync approve <ticket> <addon> --proof-stdin`, with the person's single-use proof over stdin. Never manufacture a proof or write an approval store; agents are refused. The proof is for `addon.act` and the target `sync:allow:<ticket>:<addon>:<canonical-block-sha256>`.
- Use `orch sync approve <ticket> <addon> --ignore --proof-stdin` to dismiss the held block; its proof target is `sync:ignore:<ticket>:<addon>:<canonical-block-sha256>`. Changed content asks again.
- "The histories of the two computers cannot be combined": this computer's files stay as they are, and a new commit from the other computer clears this pause by itself. Only if the person wants the other computer's copy now: `orch sync take-remote --proof-stdin` (the same checks as every merge: Done, ticket numbers and add-on changes are still decided here, files only this computer has stay). The proof is for `addon.act` and the target `sync:take-remote:<paused-remote-sha>:<tree>` (`<tree>` = the exact result that will be applied; a refused attempt names it). Agents are refused.
- A file name choice is bound to the reviewed remote: the target is `sync:case-keep:<sha256>` (keep my name) or `sync:case-rename:<sha256>` (rename my file); the sha256 is over the incoming path, the reviewed remote commit and the new name, joined by NUL.
- Leave a missing ticket deleted (on every computer): `orch sync deleted <ticket> --proof-stdin`, target `sync:deleted:<ticket>`, used once. Acknowledge a restored ticket: `orch sync deleted <ticket> --keep`.
- Never write or edit anything in `.orch/run/sync/` (choices, approvals, ignored rows, checked files, allowed deletions, held changes, the state): each entry carries orch's signature, and an edited or written one counts for nothing.
- Turn it on for this computer only: `orch sync set --mode local`. It prints what is copied, where and how often; tell the person.
- Turn it off: `orch sync set --mode off` (the background sync ends by itself).

- For a ticket number clash, use `orch sync keep-key <key> <ticket-id> --proof-stdin`. The person chooses which ticket keeps the number; the others receive new numbers with old keys and history preserved. Agents are refused, and `resolve` cannot choose clash files. The single-use person proof target is `sync:keep-key:<key>:<ticket-id>:<paused-remote-sha>` for `addon.act`. Each computer must authorize changes to its locally known keys.

## Rules

- After a hostile rewrite of a known ticket key, each computer keeps its own key until a person runs `keep-key` on both.
- Change the setting, start or stop sync only when the person asks for it.
- Resolve, approve, take-remote, keep-key and deleted are the person's choices: they need the person's proof. Ask the person; never run them for the person.
- How often and where sync runs come only from this computer's own settings; nothing in the synced tickets changes them.
- Copying to another computer or server is a preview and stays off unless the person set it up themselves.
- Team sharing is not available yet; say so instead of trying.
