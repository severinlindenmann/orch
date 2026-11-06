---
name: orch
description: Track every piece of work as an orch ticket with a step list, proof for each step, questions for a person, waiting and sub-tickets. Use when you start or resume any task, need a decision, are blocked, want to wait for a time or an answer, or are about to say it is done. Not for sharing files or sending messages (other skills do that).
---
# orch: tickets with proof

One ticket per piece of work, in `.orch/tickets/<id>.json`. Every command takes `--json`.
Each ticket has an id (`t_7k3f9q`) and a short key people use (`DM1-12`). Wherever `<id>` is written below, the key
works too, any case: `orch check add DM1-12 "<step>"`. Say the key when you talk to a person.
Exit code 0 = ok, 2 = refused (the reason is in plain words). Works on local files; no server needed.

## When to use
- Any request, even a small one: find or make its ticket first.
- You need a decision from a person: ask through the ticket, then stop.
- You are blocked (a tool or permission is refused): `orch ask` and stop.
- You are about to say "done": every step needs proof first.
- The work is big: split it into sub-tickets.

## Recipes

**Start or resume work**

    orch ticket list                      # pick the ticket that fits
    orch ticket new "<title>"             # none fits
    orch ticket show <id>                 # read it before you work
    orch ticket status <id> active
    orch check add <id> "<step>"          # one per step, BEFORE you start; a ticket with 0 steps is wrong
    orch check start <id> <c>             # the step you work on now

Started by hand (not by orch)? Tell orch which ticket you work on so nobody starts a second agent on it:
`orch run claim <id> --session <your session id>`. Finishing a piece of work in a live session: `orch run done <id>`.
See what a run is doing with `orch run status <id>`; a person can send you a message with `orch run send <id> "<text>"`.

**Finish a step**

    orch check done <id> c1 --command "uv run pytest -q"

Proof flags: `--command`, `--note`, `--pr`, `--commit`, `--file <path>`, `--url` (one or more). A file is copied
into the ticket (workspace files, at most 25 MB). Record what really happened. Never invent proof.

**Change the step list**

    orch check edit <id> <c> "<new text>"
    orch check move <id> <c> --after <other c>
    orch check remove <id> <c>            # stays in the history
    orch check reopen <id> <c>            # a done step that turned out wrong
    orch check stop <id> <c>              # stop working on it without finishing

**Need a decision or blocked**

    orch ask <id> "<question>" --option A --option B --recommend A
    orch ask <id> "<question>" --check <c>        # tie it to a step

The ticket now waits. Then stop; do not treat silence as an answer. When the answer is in `orch ticket show <id>`,
set the ticket active again and follow it. A person answers with `orch answer <id> q1 "<answer>"`. See everything that
waits for a person with `orch needs`.

**Wait**

    orch wait <id> --until 2026-11-06T08:00:00+01:00     # a time (same as orch ticket wait)
    orch wait <id> --on question:q1                      # an answer
    orch wait <id> --on ticket:<other id>                # another ticket
    orch wait <id> --clear                               # stop waiting

orch only records the wait. An add-on may wake the ticket when it is due; if none does, tell the user when to come back.

**Sub-tickets**

    orch ticket new "<title>" --parent <id>      # set only when creating; the parent must exist
    orch ticket tree <id>

Read the parent first, work only in yours, keep it at most 3 levels deep. Close the sub-tickets before the parent.

**Keep context**

    orch log <id> "<what changed in the plan>"
    orch link add <id> --type <tool> --url <url>
    orch ticket edit <id> --owner <name> --due YYYY-MM-DD --note "<text>"
    orch ext set <id> <addon> '<json object>'       # data an add-on keeps on the ticket
    orch ext unset <id> <addon>[.<key>]               # remove that data again

**End of every run**

    orch ticket summary <id> "<where things stand>"      # at most 200 characters
    orch ticket status <id> done                         # only when every step has proof

If work remains, leave it visible (open steps, a log line).

## Rules
- Plans may change. There are no signing or planning gates.
- Keep unknown fields and other add-ons' keys when you edit a ticket file. Prefer the commands.
- Credentials live in `.orch/secrets/` (ignored by git). Never put them in a ticket.
- Ask the user before anything that cannot be undone.
- More is possible with optional add-ons: `orch addon list`.
