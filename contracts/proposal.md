# Check-up proposals and versions (`orch.proposal/1`)

"Analyse with an agent" in Insights starts a **Workspace check-up** ticket. The agent reads the record, the counts and the
chats read-only and writes proposals: fix a skill, a new skill (the same steps in several tickets), ask the admin about a key
or connection. Proposals are tested on past tickets in isolation and applied only with the person's OK (owner decision I6).

Schema: `proposal.schema.json`. Examples: `examples/proposal/`. Vectors: `vectors/proposal-v1.json` (status changes,
version checks, what a check-up run may call). T0: `… contracts/validate.py proposal`.

## The check-up run (invariant P1: deny by default)

- The core starts it with run record `profile: "checkup"` (run.schema.json), set by the core from the ticket it created
  for the check-up, never from an environment variable or a flag.
- **Layer 1, the agent tool's own permission settings** (the adapter's read-only profile in agents.json): an exact allowlist
  of whole shell commands of the form `orch <command> [<sub>] …` with no shell syntax (`; & | $ ` ` ( ) < > \ * ? ~ { }` or a
  line break): `orch record query|tail|counts|propose`, `orch ticket list|show`, `orch conn list`, `orch log <own ticket>`,
  `orch check … <own ticket>`. **Every other shell command is denied**, so `env -u ORCH_RUN orch …`, `cat`, `curl` and
  scripts do not run; the agent tool's web, fetch and connection tools are off. The draft goes to `orch record propose` on
  stdin. Reference `checkup_allowed`, vectors `checkup_commands`.
- **Layer 2, the core:** `orch record propose` is refused unless the caller's run record says `profile: "checkup"`; `orch
  secret` refuses inside such a run; no connections are passed to the agent.
- Check-up is offered only for adapters whose capability flags say they support an exact command allowlist; otherwise
  "Analyse with an agent" is not shown.
- **Honest limit (Level 1):** the allowlist is enforced by the agent tool's permission system, not by the OS. A bug in that
  tool, or an agent that finds a way around it, reaches the shell with the person's rights. No OS sandbox is planned.
- Chats and records are untrusted data, never instructions (the skill text says so). Check-up runs are excluded from later
  check-ups and from Insights counts (counts skip runs with `profile: "checkup"`).
- Scope and cost: "Look at: last 30 days · all tickets", "How deep: Quick / Thorough" (no model names), cost hint.

## What the agent sends, what the core sets

`orch record propose --json` reads a **draft** (`$defs/draft`: `kind`, `title`, `plain`, `likely`, `evidence`, `target {kind,
name}`, `change {files: [{path, after}]}`) on stdin. A draft carrying any other field is refused. The core sets `id`,
`checkup`, `created_at`, `target.source` and `target.version` (from the inventory), each file's `before` hash,
`change_sha256`, `status: proposed`, `tests: not_run`, `decided: null`, `applied: null` (reference `proposal_from_draft`,
vectors `from_draft`). `skill.new` is refused when the name exists in any source or starts with `orch` (it would win by
precedence over an admin or built-in skill).

## Proposals

`kind`: `skill.fix` (files of an existing skill), `skill.new` (a new skill folder in `.agents/skills/`), `key.ask_admin`,
`connection.fix`, `note`. Only the two skill kinds carry `change.files`, always inside the skill folder; a proposal never
carries a key, a connection config or another path. `plain` is the change in plain words (shown on Accept); `likely: true`
marks a guess about a cause the broker cannot see. `evidence` points at tickets/runs/events.

## Versions

`target.version` = the skill's content hash (inventory.md) when the proposal was made; each `change.files[].before` = sha256
of that file then (null = new file). `applied` records `version_before` and `version_after`; before applying, the core keeps
a copy of the touched files in `.orch/record/proposals/<id>/before/`.

## Status

```
proposed --tests passed--> tested --accept--> accepted --rollback--> rolled_back
proposed|tested --reject--> rejected      tested --send to admin--> sent_to_admin (admin skills)
any open state --skill changed meanwhile--> stale
```

- **The diff is bound.** When the tests run, the core records `change_sha256` in the trusted orch home
  (`<orch home>/keys/<ws>/proposals.json`, the workspace copy can be edited). The Accept screen shows the **full diff** (every
  file, before and after), not only `plain`, and the page mints the `checkup.accept` proof for target
  `<id>@<change_sha256 hex>`. Accept recomputes the hash of the stored change and refuses (`changed`) when it differs from the
  recorded one or from the proof's target (vectors `steps`: file swapped after the test, proof for another diff).
- `accept` (`checkup.accept` proof, human-proof.md): only from `tested` with `tests.state = passed`, only when the target's
  current version equals `target.version` (else `stale`), never for an admin-shared skill (`target.source = admin`: only "Send
  to admin", `checkup.send_to_admin` proof). Applies the files in one step (new files + rename), writes `decided`,
  `applied`, and the skill's new version starts a new line in Insights ("since the change").
- `rollback` (`checkup.rollback` proof): only from `accepted` and only when the current version equals
  `applied.version_after` (else refused `conflict`: someone changed it since); restores the kept files. *Implementing slice 3.4 must* write files with O_NOFOLLOW and check that every
  realpath stays inside the skill folder (no symlink out).
- Tests on past tickets run isolated (a copy of the workspace without keys and connections, outside services faked); a
  failed or errored test blocks Accept (the person sees the cases).
Reference: `proposal_step` in validate.py.
