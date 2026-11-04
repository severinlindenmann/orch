---
name: orch
description: Track work, questions, and evidence with the orch CLI.
---
# Working with orch

Every piece of work is tracked as an orch ticket. Before you start, run `orch ticket list`; if none fits,
run `orch ticket new "<title>"`. Add checklist items and mark each done with evidence before you finish. Read the relay inbox at session
start (`orch relay inbox`) if relay is connected. This applies to every request, even a small one.

Read the relevant ticket at the start of a session and whenever you return to it:

    orch ticket show <id>

Keep the ticket current as work changes.

- Move it to active when starting or resuming: `orch ticket status <id> active`.
- Add checklist items for the work you discover: `orch check add <id> "<text>"`.
- Record plan changes with `orch log <id> "<text>"`.
- Keep useful context with `orch link add <id> --type <tool> --url <url>`.

All commands accept `--json`. Exit code 0 = ok, 2 = refused (the reason is in plain words).

# Evidence before done

A checklist item is done only when it has at least one evidence entry:

    orch check done <id> c1 --evidence '{"type":"pr","ref":"PR #88"}'

Evidence has a type and ref, with optional text. Types: pr, commit, file, url, command, note.
Record what actually happened. Never invent proof.

# Questions and pauses

Use `orch ask <id> "<question>" --option A --option B --recommend A` when you need a person's decision.
Offer options and a recommendation when useful. The question and the waiting state are saved; then pause.
Do not treat silence as an answer. When an answer arrives (`orch answer <id> q1 "<answer>"`), read the
ticket again, resume as active, and follow the recorded answer.

To sleep until a time: `orch wait <id> --until <time>`. To wait on something: `orch wait <id> --on question:q1`.

# Files and history

Tickets: `.orch/tickets/<id>.json`, schema `orch.ticket/1`.
Preserve unknown fields and other add-on keys. Keep history timestamps and the actor; no durations.
Plans may change. No signing or planning gates. Git is optional; local files are sufficient.
Keep credentials in `.orch/secrets/`, ignored by git.

# Finishing

Review the checklist and its evidence, record the outcome, then set the ticket status to done:
`orch ticket status <id> done`. If work remains, leave its actual state visible.
