# Who a ticket's person fields show as (`orch.history`)

ONE rule, in one module (`workspace/src/orch/history.py`), decides how every person field of a ticket is shown to
people and agents. Every reader goes through it at the source; `workspace/tests/test_history_lint.py` fails when a
module reads a ticket's `history`, an evidence entry's `by`, or tests an entry's `by` for `human:` itself
(writers and readers of no author are listed there with their reason).

## Fields

`history[].by` (and its text), `checklist[].evidence[].by`, `checklist[].by`, `checklist[].wont_by`,
`verdicts[].person`, `questions[].answered_by`, `refs[].by`, `plan.by`, `description_by`.

A value that is a plain agent label (`agent:` + `[a-z0-9._-]{1,40}` in ASCII, not `relay`, `phone`, `ph_`) needs no
proof. Every other value is shown as written only when this core proves it **here**; otherwise it is shown as
`agent:sync`, and a history text gets `(synced, not verified here) ` in front. The stored bytes are never changed.

## Proof

1. **Own objects.** Core has ONE history-append point (`tickets.add_history`; ticket creation goes through it too),
   ONE evidence-append point (`tickets.add_evidence`) and the ref-add point (`tickets.ref_add`). Each marks the exact
   object it creates (`history.created`). `tickets._write`, the one write path, records the canonical digest
   (sha256 of canonical JSON of `[kind, object]`; a ref without `title`, `status`, `thumb`) of every marked object
   that is in the ticket it writes, in `.orch/run/own-lines/<ticket id>.json`
   (`{"schema": "orch.own-lines/2", "ticket", "lines", "evidence", "refs", "mac"}`, `mac` = the core's local1 MAC,
   human-proof.md "Local records"). The old file is NEVER diffed against the new one: an object core did not create
   in this process is never recorded, whatever the file's encoding or form. A store that cannot be written, read or
   verified proves nothing (fail closed).
2. **Decisions.** A current verdict (`verdicts[].person`, its line) and a Won't do this core's ledger vouches for
   (`wont_by`, the step's `by`, its line) prove their own person fields. The history line a decision was signed with
   (`person`, `line` = digest of `{text, via}`, `at`) is matched ONCE: the one line by that person with exactly that
   digest, the writer's shape and the `at` closest to the decision's (within 5 s). Other copies are not the
   decision's.
3. **Answers.** `answered_by` is proven when a proven history line of that actor reads exactly
   `Answered <question id>: <answer>`.

The verdict checker and the Won't do ledger are read once per call (`shown_json` over many tickets shares them).

## When it applies

Only once sync is enabled for the workspace (`history.sync_enabled`): `.orch/.git` exists, or `.orch/run/sync/`, or
the enabled record in the guarded orch home (`sync-enabled/<sha256("path:" + real path)[:32]>.json` and
`sync-enabled/<sha256("ws:" + workspace id)[:32]>.json`, local1 MAC; either one counts), or a ticket shows sync's
traces (`ext.sync`, or a line by the reserved label `agent:sync`). The sync add-on calls `history.enable_sync` first
in every `repo.ensure`, before anything can refuse: it writes the record and, only for a workspace that never synced
(no state repository, no earlier step's state) and only when no ticket shows sync's traces, adopts the person
fields already in this machine's tickets as its own. Removing `.orch/.git` or `run/sync` never makes a workspace
trust every line again.

A workspace where sync was never enabled is not touched: `shown_ticket` returns the very same object and nothing is
read or written for it, so every output (ticket show and `--json`, list, chat, needs, prompts, phone view) is what
it was without this module (`test_history.py::test_sync_free_outputs_are_what_they_were`).

## Readers

`orch ticket show` and every `--json` output of the CLI (`_out` -> `shown_json` with the command's root), the
conflict message, `cli._who_added` (`history.evidence_author` on a shown ticket), core needs rows, run prompts
(fresh, resume) and the news footer, `runs_live._asker`, the phone view, the relay's allow answers, the dashboard
(`data.shown`: the core's rule; without the core every person field is demoted) and its mobile/Chat views,
automation and focus (they read orch's CLI JSON, which is shown already). `root` is required: a caller without one
looks it up (`history.here`).

## The reserved label

`agent:sync` (any case) is written only by core and the sync merge. `tickets.current_actor` refuses it as an actor,
a demoted line is never a run's "own" news, and it is never an asker.
