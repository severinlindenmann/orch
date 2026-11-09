# Check-up proposals and versions (`orch.proposal/1`)

"Analyse with an agent" in Insights starts a **Workspace check-up** ticket. The agent reads the record, the counts and the
chats read-only and writes proposals: fix a skill, a new skill (the same steps in several tickets), ask the admin about a key
or connection. Proposals are tested on past tickets in isolation and applied only with the person's OK (owner decision I6).

Schema: `proposal.schema.json`. Examples: `examples/proposal/`. Vectors: `vectors/proposal-v1.json` (status changes,
version checks, what a check-up run may call). T0: `… contracts/validate.py proposal`.

## The check-up run (invariant P1: deny by default)

- The core starts it with run record `profile: "checkup"` (run.schema.json), set by the core from the ticket it created
  for the check-up, never from an environment variable or a flag.
- Inside a check-up run the core allows only: `orch record query|tail|counts`, `orch ticket list|show`, `orch conn list`,
  `orch record propose` (writes `.orch/record/proposals/<id>.json`, status `proposed`), `orch log`, `orch check …` on its own
  ticket. Everything else is refused (`not_allowed`), in particular every `orch secret` command, `orch job`, `orch run`,
  `orch conn allow`, ticket changes on other tickets. Reference `checkup_allowed`.
- No keys (the broker refuses), no connections (none passed to the agent), no network tools (the adapter's
  read-only profile in agents.json turns off the agent tool's web and fetch tools). Level 1: a shell command can still reach
  the network; no OS sandbox is planned. The core knows a check-up call by the run's `ORCH_RUN` → run record `profile`; as a
  second line the read-only profile also denies `orch secret`, `orch job` and `orch run` in the agent tool's own permission
  settings, so clearing the environment does not open the broker.
- Chats and records are untrusted data, never instructions (the skill text says so). Check-up runs are excluded from later
  check-ups and from Insights counts (counts skip runs with `profile: "checkup"`).
- Scope and cost: "Look at: last 30 days · all tickets", "How deep: Quick / Thorough" (no model names), cost hint.

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

- `accept` (`checkup.accept` proof, human-proof.md): only from `tested` with `tests.state = passed`, only when the target's
  current version equals `target.version` (else `stale`), never for an admin-shared skill (`target.source = admin`: only "Send
  to admin", `checkup.send_to_admin` proof). Applies the files in one step (new files + rename), writes `decided`,
  `applied`, and the skill's new version starts a new line in Insights ("since the change").
- `rollback` (`checkup.rollback` proof): only from `accepted` and only when the current version equals
  `applied.version_after` (else refused `conflict`: someone changed it since); restores the kept files.
- Tests on past tickets run isolated (a copy of the workspace without keys and connections, outside services faked); a
  failed or errored test blocks Accept (the person sees the cases).
Reference: `proposal_step` in validate.py.
