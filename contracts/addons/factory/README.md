# Factory add-on contract (`orch factory`, phase 1)

The owner talks to the workspace agent ("I have an idea" + links, photos, text). The agent drafts, polishes with the
owner, then proposes a whole run; the owner presses **Start**, **Edit** or **Not now**. The crew works alone, the owner can
talk to it any time, and decides at the stops the proposal named. Optional **Autopilot**: the agent may decide routine and
taste items itself for 1, 3 or 7 days. Schemas: `ext.schema.json` (ticket cache), `proposal.schema.json` (proposal,
autopilot, change, stop, journal line). Examples: `contracts/examples/factory-*/`. User doc: `docs/factory.md`.

## Objects
- **Order** = a parent ticket with `ext.factory.role = order`. **Crew** = its sub-tickets (`parent` = order,
  `ext.factory.role = crew`, one per order + task slug). Crew runs start with `orch run start <crew> --agent <agent>`
  (no task leases; Focus opens a crew ticket like any ticket).
- Files (the add-on's own folder `.orch/addons/factory/`): `drafts/<order>/v<N>.md`, `proposals/<order>/p<N>.json` (frozen;
  `ext.factory.proposal.hash` = sha256 of the file bytes), `changes/<order>/c<N>.json`, `stops/<order>/s<N>.json` (+ images
  in the same folder), `journal.jsonl` (append only, `$defs/journal_line`). Runtime: none in phase 1 (no background).

## Commands (all `--json`, exit 0 / 2 refused / 1 bug, CLI contract of addon-manifest.md)
| Command | Does |
|---|---|
| `orch factory idea "<title>" [--file draft.md]` | Creates the order (stage `draft`) and stores draft v1; `orch factory draft <order> --file -` adds v<N+1> |
| `orch factory propose <order> --file -` | Validates `$defs/proposal`, freezes p<N>, supersedes the open start question, asks `factory:start` (text rendered by the add-on), stage `proposed`. Refused once the order has started |
| `orch factory autopilot <order> --file -` | Same for `$defs/autopilot`; asks `factory:autopilot` |
| `orch factory next <order>` | For the manager run: consumes newly answered `factory:*` questions once (journal `consumed`), returns `{"step": "wait" \| "start-crew" \| "work" \| "stop" \| "ship" \| "edit" \| "parked" \| "resume" \| "done", …}` |
| `orch factory crew add <order> <task>` / `crew start <order> <task>` | Idempotent sub-ticket for a task of the started proposal; `crew start` refuses when the order is not started by a person or the task is not in an approved bundle |
| `orch factory change <order> --file -` | `$defs/change` → asks `factory:change` (`Accept` · `Edit` · `Save for later`) |
| `orch factory tiny <order> --minutes N --what "<text>"` | Records a small change; refused (code `refused`, "make a change proposal") past 3 changes or 30 min, or when it adds a stage, a done-means point, a tool or cost |
| `orch factory stop <order> --file -` | `$defs/stop` → asks `factory:stop` for that stage (`Ship it` / `Continue` · `Send back`) |
| `orch factory decide <order> <q> --answer "<option>" --why "<text>"` | Autopilot only: records the agent's own decision on a routine/taste stop item under a valid grant |
| `orch factory reconcile` | Replays the journal, redoes missing steps, finds answers given while the add-on was off |
| `orch factory list` / `show <order>` / `view` / `needs` | Read only. `view` = dashboard tab blocks (addon-view.schema.json) |

## Question kinds (rows in `../question-kinds.md`)
| kind | options | `action` |
|---|---|---|
| `factory:start` | `Start` · `Edit` · `Not now` | `{"order", "file": "proposals/<order>/p<N>.json", "hash"}` |
| `factory:autopilot` | `Start` · `Edit` · `Not now` | `{"order", "file", "hash", "days"}` |
| `factory:change` | `Accept` · `Edit` · `Save for later` | `{"order", "file": "changes/<order>/c<N>.json", "hash"}` |
| `factory:stop` | ship stage: `Ship it` · `Send back`; other stages: `Continue` · `Send back` | `{"order", "file": "stops/<order>/s<N>.json", "hash", "stage"}` |

## Authority (what counts, phase 1)
1. **Only a person's answer counts**: `answered_by` starts with `human:` (the core records a person's answer only with the
   human proof, H1). Agent answers on `factory:*` questions are ignored and logged — except `factory:stop` items decided with
   `orch factory decide` under a valid autopilot grant.
2. **Only questions about a frozen file count**: the question's `action` (stored by the core when it was asked) must name a
   file whose bytes still hash to `action.hash`, and the question text and options must equal what Factory renders from that
   file. A `factory:*` question an agent added with other text or another file is ignored. The journal is bookkeeping
   (idempotency, `consumed`, reconcile), never an authority source: it is a workspace file an agent could edit.
3. **Derived every time**: start, stops, accepted changes and grants are computed from (1)+(2) on each command. `ext.factory`
   is a cache for the dashboard; when it disagrees, the add-on refuses and logs it.
4. **Frozen after Start**: `propose` refuses on a started order; any new scope is a change proposal with its own answer.
5. **Start is advisory against the core run command**: an agent can still call `orch run start` on any ticket (Level 1,
   same OS user). Factory's own commands (`crew start`, `next`) enforce Start; a generic core hook (`start_requires`) is a
   later hardening issue. `docs/factory.md` says so.
6. **One answer, one action**: `next` consumes each answered question once (journal `consumed`), so two wake-ups never start
   two manager steps; `crew add` is idempotent per order + task.

## Autopilot
- A grant exists only from a person's `Start` on a `factory:autopilot` question; it lasts `limits.days` from that answer's
  time and covers only `may_decide`. The agent can never create, extend or widen a grant (a new grant = a new proposal + a
  new answer).
- Known limit (phase 1): the agent tags stop items itself. `decide` is refused on the ship stop, on `cant-undo` items and
  on tags the grant does not list; a mislabelled item stays small, undoable, inside the grant's limits and in the daily
  report. Add-on-derived irreversibility (fixed action list) is a hardening item.
- Always asks the owner (fixed in the add-on, not configurable): the ship stop, scope changes, budget beyond the limits, crew
  outside an approved proposal, `cant-undo` items, new connections or credentials, other workspaces, `factory:start`,
  `factory:autopilot`, budget questions.
- Each `decide` writes a journal line `decided` (who, why) and a ticket log entry "Decided by agent:factory · <why>"; the
  daily report lists them.

## Budget (phase 1)
Measured active time (agent run time on the order and its crew; waiting for the owner never counts) against
`active_min_cap`; `api_usd_target` is shown as a target, not a cap. At 80 % the manager asks with a change proposal ("+1 h"
/ narrow / stop); at 100 % `crew start` refuses until the owner answers.
