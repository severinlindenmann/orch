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
- Keeping their copy of a ticket is the person's decision: `orch sync resolve <path> --keep theirs`. Ask the person first.
- The ticket counter is the person's decision too: `orch sync resolve ticket-counter.json --keep theirs` always, and `--keep mine` when sync paused because "Ticket numbers jumped far ahead on the other computer". Never choose it for the person.
- A file name that differs from a local one only in capital letters is the person's choice: `orch sync resolve <path> --keep-local-name` (the other computer's name is not applied while the remote stays as it is) or `orch sync resolve <path> --rename-local "<new name>"` (then both arrive). `--keep` is refused for these files.
- A held add-on change waits for the person: `orch sync approve <ticket> <addon>` lets its value in. Never write the files in `.orch/run/sync/` yourself.
- Use `orch sync approve <ticket> <addon> --ignore` to dismiss the held change. A changed value asks again.
- "The histories of the two computers cannot be combined": this computer's files stay as they are, and a new commit from the other computer clears this pause by itself. Only if the person wants the other computer's copy now: `orch sync take-remote` (the same checks as every merge: ticket numbers and add-on changes are still decided here, files only this computer has stay).
- Leave a missing ticket deleted (on every computer): `orch sync deleted <ticket>`. Acknowledge a restored ticket: `orch sync deleted <ticket> --keep`.
- Never write or edit anything in `.orch/run/sync/` (choices, ignored rows, checked files, allowed deletions, held changes, the state): sync keeps these itself.
- Turn it on for this computer only: `orch sync set --mode local`. It prints what is copied, where and how often; tell the person.
- Turn it off: `orch sync set --mode off` (the background sync ends by itself).
- Choosing or changing where the copy goes (another computer or server) is the person's choice, made in the dashboard (Settings, General, Sync). On the command line: `orch sync set --remote <address>`. A public address (anyone can read it) is never used on that choice: the person chooses it separately (`--public`). Never choose an address for the person. Writing an address into `.orch/run/sync/settings.json` does nothing: sync uses only the address that was chosen, and otherwise stops with "Sync found an address you did not choose and did not use it. Choose where to sync in Settings." (ask the person to choose where to sync in the dashboard).

- For a ticket number clash, use `orch sync keep-key <key> <ticket-id>`. The person chooses which ticket keeps the number; the others receive new numbers with old keys and history preserved. `resolve` cannot choose clash files. Each computer chooses for its locally known keys.
- "Move your orch files out of the team repository?" (a Needs row): the workspace's team repository keeps the orch files, so sync does not start (`orch sync set` says "needs-move"). The person answers it with Move in the dashboard (the core's `orch private move`): it takes the orch files out of the team repository's index (nothing is committed, the files stay here; the person commits the removal, older history keeps its copies) and then sync starts on its own. Not now hides the row for a day. Do not run `orch private move` for the person.

## Rules

- After a hostile rewrite of a known ticket key, each computer keeps its own key until a person runs `keep-key` on both.
- Change the setting, start or stop sync only when the person asks for it.
- Resolve, approve, take-remote, keep-key, deleted, Move and choosing the remote address are the person's choices. Ask the person; do not run them on your own.
- How often and where sync runs come only from this computer's own settings; nothing in the synced tickets changes them.
- Copying to another computer or server is a preview and stays off unless the person set it up themselves.
- Team sharing is not available yet; say so instead of trying.
