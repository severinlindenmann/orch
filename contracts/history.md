# Who a ticket's person fields show as (`orch.history`)

ONE rule, in one module (`workspace/src/orch/history.py`), decides how every person field of a ticket is shown to
people and agents. Every reader goes through it at the source; `workspace/tests/test_history_lint.py` fails when a
module reads a ticket's `history`, an evidence entry's `by`, any other person field (`answered_by`, `wont_by`,
`person`, `description_by`, the `by` of a step, ref or plan), or tests an entry's `by` for `human:` itself
(writers and readers of no author are listed there with their reason; a reader of person fields that takes the
shown ticket itself is listed too, and the lint checks that it calls `history.shown_*`).

## Fields

`history[].by` (and its text), `checklist[].evidence[].by`, `checklist[].by`, `checklist[].wont_by`,
`verdicts[].person`, `questions[].answered_by`, `refs[].by`, `plan.by`, `description_by`.

A value that is a plain agent label (`agent:` + `[a-z0-9._-]{1,40}` in ASCII, not `relay`, `phone`, `ph_`) needs no
proof. Every other value is shown as written only when this core proves it **here**; otherwise it is shown as
`agent:sync`, and a history text gets `(synced, not verified here) ` in front. The stored bytes are never changed.

## Proof

1. **Own objects.** Core has ONE history-append point (`tickets.add_history`; ticket creation goes through it too),
   ONE evidence-append point (`tickets.add_evidence`), the ref-add point (`tickets.ref_add`) and the step-start point
   (`tickets.check_start`: a step's "doing" mark, so its `by` stays attributed). Each marks the exact
   object it creates (`history.created`). `tickets._write`, the one write path, records the canonical digest
   (sha256 of canonical JSON of `[kind, object]`; a ref without `title`, `status`, `thumb`; a step only as
   `{id, state, by, at}`) of every marked object that is in the ticket it writes, in
   `.orch/run/own-lines/<ticket id>.json`
   (`{"schema": "orch.own-lines/2", "ticket", "lines", "evidence", "refs", "steps", "mac"}`, `steps` only once it
   holds a digest, `mac` = the core's local1 MAC over the file but `schema` and `mac`, human-proof.md "Local
   records"). The old file is NEVER diffed against the new one: an object core did not create
   in this process is never recorded, whatever the file's encoding or form. A store that cannot be written, read or
   verified proves nothing (fail closed).
2. **Decisions.** A current verdict (`verdicts[].person`, its line) and a Won't do this core's ledger vouches for
   (`wont_by`, the step's `by` only when it is that same value, its line) prove their own person fields. The history line a decision was signed with
   (`person`, `line` = digest of `{text, via}`, `at`) is matched ONCE: the one line by that person with exactly that
   digest, the writer's shape and the `at` closest to the decision's (within 5 s). Other copies are not the
   decision's.
3. **Answers.** `answered_by` is proven when a proven history line of that actor reads exactly
   `Answered <question id>: <answer>`. An answer ACTS on this machine (a relay:allow question) only when that line
   is in this machine's own store (`history.answer_proven`, any label, an agent's too); human-proof.md "Answers as
   authority".

The verdict checker and the Won't do ledger are read once per call (`shown_json` over many tickets shares them).

## When it applies

Only once sync is enabled for the workspace (`history.sync_enabled`): `.orch/.git` exists, or `.orch/run/sync/`, or
the enabled record in the guarded orch home (`sync-enabled/<sha256("path:" + real path)[:32]>.json` and
`sync-enabled/<sha256("ws:" + workspace id)[:32]>.json`, local1 MAC; either one counts), or a ticket shows sync's
traces (`ext.sync`, or a line by the reserved label `agent:sync`). The sync add-on calls `history.enable_sync` first
in every `repo.ensure`, before anything can refuse: it writes the record and, only for a workspace that never synced
(no state repository, no `run/sync` folder or file) and only when no ticket shows sync's traces, adopts the person
fields already in this machine's tickets as its own. Removing `.orch/.git` or `run/sync` never makes a workspace
trust every line again.

A workspace where sync was never enabled is not touched: `shown_ticket` returns the very same object and nothing is
read or written for it, so every output (ticket show and `--json`, list, chat, needs, prompts, phone view) is what
it was without this module (`test_history.py::test_sync_free_outputs_are_what_they_were`).

## Readers

`orch ticket show` and every `--json` output of the CLI (`_out` -> `shown_json` with the command's root; a command
that outputs a bare step, question or ref - `orch check ...`, `orch answer`, `orch ref add/remove/list` - shows it
through `history.shown_item` / `shown_ticket` first, since `shown_json` cannot tell it from other data), the
conflict message, `cli._who_added` (`history.evidence_author` on a shown ticket), core needs rows, run prompts
(fresh, resume; `root` required) and the news footer, `runs_live.resume_after_answer`, the phone view (full and
light), the relay's allow answers, the dashboard (`data.shown`: the core's rule; without the core every person
field is demoted, with the same agent-label rule) and its mobile/Chat views, automation and focus (they read orch's
CLI JSON, which is shown already). Each takes the shown ticket at its entry, not only for the history. `root` is
required: a CLI command without one looks it up (`history.here`).

## Chat lines

A history line with `chat_message: true` is a real Chat or group message. Since 21 Nov 2026 core writes two more
fields on every chat line (only in `tickets.add_history`, the one append point):

- `id`: the line's stable id, `m_` + 16 lowercase letters or digits (the form of a relay message id). When the
  message already has an id (a Chat text, a helper's Chat answer, a relay message) the line takes that one, so the
  message has one id everywhere; otherwise core makes a new one. Set once, never changed; later steps (a chat list,
  other workspaces in one chat) refer to a message by it.
- `by_name` (optional): the name the person typed for this message, one line, 1-60 characters after cleaning
  (control and invisible characters go, spaces collapse). It is shown as typed and marked "not signed in". It is
  NOT a person field: it proves nothing, `by` stays the actor and every rule above reads only `by`. A line shown
  as `agent:sync` (not proven here) is shown without its `by_name`.

Neither field is allowed on a line that is not a chat line (ticket.schema.json). Old lines have neither and stay
valid; readers never require them (example `examples/ticket/valid-chat-line-name-and-id.json` holds a new chat
line, an old chat line and an old line from before the flag).

## The reserved label

`agent:sync` (any case) is written only by core and the sync merge. `tickets.current_actor` refuses it as an actor,
a demoted line is never a run's "own" news, and it is never an asker.
