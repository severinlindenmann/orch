# Counts: `orch record counts --json` (`orch.counts/1`)

The one API Insights, the check-up and the daily upload read. Counts live in the core (a rebuildable index over the record),
never in an add-on.

Schema: `counts.schema.json` (`$defs/answer`, `day_file`, `item`). Examples: `examples/counts/`, `examples/counts-day/`.
Vectors: `vectors/counts-v1.json` `denominators`. T0: `… contracts/validate.py counts`.

## Command

`orch record counts [--days N | --from YYYY-MM-DD --to YYYY-MM-DD] [--ticket T] [--kind K]… --json` → `$defs/answer`
(default the last 30 days, UTC days). Read-only, may be called by anyone (add-ons, agents, the check-up). No text from any
run is in the answer: names, numbers, times and hashes only.

## Rebuildable index

Built from `.orch/record/counts/<day>.json` (days whose run files were pruned, activity.md Retention) plus the run files
still there; a cache may be kept in `.orch/record/counts/index.json`, but deleting it changes nothing. A run is counted on
the UTC day it started.

## Denominators and "unknown / not seen"

Every run writes, in its `run.state starting` event, `data.sees`: the kinds its agent tool can report (skill, tool, mcp,
key, helper, job), from the adapter's capability flags. For each item:
- `runs.used` = runs that used it; `runs.of` = runs in the window that could have seen it (`kind` in `sees`, and never
  fewer than `used`); `runs.unseen` = the other runs, whose tool cannot report it. Screens say "5 of 23 runs", and when
  `unseen` > 0 add "4 runs can't tell".
- `seen` = `yes` (used at least once), `not_seen` (in the inventory, could have been seen, never used: "Not used in 30 days"),
  `unknown` (no run in the window could have seen it: "Can't tell yet"). Never show `unknown` as zero.
- `ok` / `failed` / `refused` / `unknown` split the uses; `refused` = denials and key refusals. A key handed to a command is
  one use of the key, never an API call count. Errors are not proof that a skill is bad: `tickets` joins ticket outcomes
  (done, sent back, open) for the check-up to weigh.
- `versions` = per content hash (inventory.md), so a changed skill starts a new line ("since the change: 4 of 4 ok").
- Items come from the record **and** the inventory, so unused things are listed (`seen: not_seen` or `unknown`).

`coverage`: runs whose steps were all `full` vs runs with any `partial` step. `since` = recording since. `sharing` = the state
of the daily upload (usage-counts.md): `on`, `off` (this workspace), `off_by_admin`, `not_connected`; `names`; `last_sent`;
`queued`.

Reference: `cnt_items` in validate.py; vectors `denominators` (three runs, one tool that cannot report skills, inventory
items never used, a connection no run could see).

Record counts include `unavailable: [{run, status, reason, message}]` and
`complete: boolean`. The list is always present, empty when all inputs were
read. If any run is unavailable or tampered, `complete` is false and that run
is listed with the plain-language record message (activity.md, Integrity).
