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
- **Ask** = a small sub-ticket of the order (`parent` = order, `ext.factory.role = ask`, `stop`, `ws`) that carries one
  stop to another workspace for its view (#816 part A). **Hand-over** = a crew sub-ticket whose task is in the started
  proposal's `handovers[]`; it is delegated to that workspace instead of run here (`ext.factory.handover`, #816 part B).
- Files (the add-on's own folder `.orch/addons/factory/`): `drafts/<order>/v<N>.md`, `proposals/<order>/p<N>.json` (frozen;
  `ext.factory.proposal.hash` = sha256 of the file bytes), `changes/<order>/c<N>.json`, `stops/<order>/s<N>.json` (+ images
  in the same folder), `journal.jsonl` (append only, `$defs/journal_line`). Runtime: none in phase 1 (no background).

## Commands (all `--json`, exit 0 / 2 refused / 1 bug, CLI contract of addon-manifest.md)
| Command | Does |
|---|---|
| `orch factory idea "<title>" [--file draft.md]` / `idea --ticket <id> [--file …]` | Creates the order (stage `draft`) and stores draft v1 — or turns an existing ticket (open, ready, waiting or active; not a sub-ticket) into the order, its note becoming draft v1 (e.g. the ticket the owner made from Chat); idempotent. `orch factory draft <order> --file -` adds v<N+1> |
| `orch factory act idea --by human:<name> --json -- "<text>"` | The page's idea box, run by the dashboard for the person's click (`addon.act`, manifest `[acts.idea]`, `who = "people"`): one order (note = a short start text under 200 characters: a Factory order, draft with `orch factory draft`, ask, wait, don't build; title = the first words, at most 80 characters; draft v1 = the text, one line, at most 500 characters), every write recorded `--by` that person, then `orch run start <order> --by <person>` so the agent writes the first real draft. `{"order", "started", "text"}`; `started: false` when no agent could start (the idea is still saved). Refused without a `human:` actor: agents use `idea` as themselves |
| `orch factory propose <order> --file -` | Validates `$defs/proposal`, freezes p<N>, supersedes the open start question, asks `factory:start` (text rendered by the add-on), stage `proposed`. Refused once the order has started |
| `orch factory autopilot <order> --file -` | Same for `$defs/autopilot`; asks `factory:autopilot` |
| `orch factory next <order>` | For the manager run: consumes newly answered `factory:*` questions once (journal `consumed`), returns `{"step": "wait" \| "start-crew" \| "work" \| "stop" \| "ship" \| "edit" \| "parked" \| "resume" \| "done", …}` |
| `orch factory crew add <order> <task>` / `crew start <order> <task>` | Idempotent sub-ticket for a task of the started proposal; `crew start` refuses when the order is not started by a person or the task is not in an approved bundle |
| `orch factory ask <order> <stop> <ws> [--item N]… [--no-pictures] --by human:<name>` / `act ask` | #816 A. The person's click (`[acts.ask]`, `who = "people"`, target `<order>:s<N>:<ws>:<items>`, items = comma list of 0-based stop item indexes or `-` for none): makes the ask sub-ticket ("Your view: <order title> · <stop label>", summary = the fixed line "<order title> · <stop label>: what would you change before this ships?", checklist = the ticked item titles), `orch relay group add <ask> <ws>`, `orch relay group share --click` for each picture of the ticked items (secret scan; a hit refuses the whole ask before anything is sent), `orch ask` an information question on the ask ticket + `orch relay group ask`. Refused: stop not open, `ws` not reachable for groups, an open ask of the same stop to the same workspace. Journal `asked`; order history "Asked <name> for a view on <stop label>". Answering the stop closes its ask sub-tickets |
| `orch factory change <order> --file -` | `$defs/change` → asks `factory:change` (`Accept` · `Edit` · `Save for later`) |
| `orch factory tiny <order> --minutes N --what "<text>"` | Records a small change; refused (code `refused`, "make a change proposal") past 3 changes or 30 min, or when it adds a stage, a done-means point, a tool or cost |
| `orch factory stop <order> --file -` | `$defs/stop` → asks `factory:stop` for that stage (`Ship it` / `Continue` · `Send back`) |
| `orch factory decide <order> <q> --answer "<option>" --why "<text>"` | Autopilot only: records the agent's own decision on a routine/taste stop item under a valid grant |
| `orch factory reconcile` | Replays the journal, redoes missing steps, finds answers given while the add-on was off |
| `orch factory start` / `stop` / `status` | The Factory watcher (manifest `background = true`, `runs_agents = true`; core's `orch start` calls `start`). `start` → `{"running": true, "pid"}`, `stop` → `{"stopped": bool}` (`stop` without an order; `stop <order> --file` is the stop stage above), `status` → `{"running": bool, "pid"?}`, exit 1 when not running. Pid record in `.orch/run/factory/`, signalled only after start time and command-line check |
| `orch factory watch [--once]` | The watcher loop (every 20 s); `--once` = one pass, prints `{"woken": [{"order", "why"}]}`. Wakes the manager with `orch run start <order> --by agent:factory` when (a) a person answered a Factory question `next` has not consumed, (b) a crew sub-ticket of a started order became done/failed, (c) a live autopilot grant covers an open routine/taste stop; never for an agent answer, never twice for one id, never while a run is live. Seen state in `.orch/addons/factory/watch.json`; one history line "Factory woke the manager: <why>" |
| `orch factory list` / `show <order>` / `view` / `needs` | Read only. `view` = dashboard tab blocks (addon-view.schema.json) |

## Asking another workspace (#816 A)
- What leaves the machine is only the ask sub-ticket's group card (title, the fixed line, the ticked item titles, its one
  information question) and the ticked items' pictures. The order's summary, tasks, crew logs, budget and chat never leave
  (R3.3). The secret scan runs when the page's dialog opens (`/api/order/<id>/stop/<n>/scan`) and again at send.
- Replies: the member's answer on the ask question (`answered_by` `agent:<ws>` = their helper, or a person's group text in
  the ask ticket's history) is untrusted text, shown cleaned on the stop (at most 3 lines + more). It never counts as a
  stop answer: the stop question is a different question of a different ticket.
- `decide` (autopilot) refuses a stop that has an ask: the person decides.

## Handing a task to another workspace (#816 B)
- `propose` refuses: a `workspace` that is not a `ws_` id in the relay workspace list with
  delegate allowed, a `task` not in `tasks`, a `sends.files` path that breaks the schema pattern (relative, forward slashes, no leading `/` or `~`, no `..`, no dot segment, no backslash, colon or control character) or is missing; on top of the schema the add-on checks each path strictly in Python (`store.handover_file_ok`: allowlist of letters, digits incl. umlauts, space and `_ . / ( ) -`, no comma or semicolon, no newline, no space at a path or segment edge, no double space), since a JSON-schema `$` can match before a trailing newline. The Start question lists the receiving workspace and every file exactly as it is shared (the render refuses a path it would have to clean or cut; `Handover: <task> → <ws> (they get: …)`); the person's Start is bound to the frozen proposal's hash, so a file added later makes the order `tampered`. There is no cap on the
  share of time (owner, 15 Nov) beyond the schema's 2 hand-overs; `minutes` is shown, never counted in `active_min_cap`.
- `crew start` for a hand-over task runs `orch relay delegate <ws> "<title>" --text <brief> --check <done-means>…
  --ticket <crew> --group` and `orch relay group share --click <crew> <file>` for each `sends.files` (Start was the
  person's click for them, owner Q6). The share goes through the core's group share, so its path rule (inside the
  workspace, no symlink escape, no dotfiles, VCS or config folders) and the shared secret scan apply; a hit refuses the
  crew start. No add-on path checker instead of `orch run start`. The crew ticket is the owner.
- State comes from the relay task status (`ext.factory.handover.state` is a cache): on `done` the result is evidence on
  the crew task and the crew ticket is done (watcher rule b). Watcher rule (d): a hand-over `denied` or `failed` wakes
  the manager once per task and reason; it then files a `factory:change` with `takes_back: <hand-over task slug>`
  (the Start text of the change reads "Do it here instead: <title> · +N min"; freeze refuses a slug that is not a
  hand-over of the started proposal). On Accept the other workspace gets a group text "No longer needed" (core has no
  way to drop an undelivered delegate from the outbox yet) and the task runs here; never a second copy without the
  person's Accept.
- Before the delegate goes out, every `sends.files` file is scanned with `orch secret scan`; a hit refuses the crew
  start and nothing is sent. The core's group share scans again at share time.

## Question kinds (rows in `../question-kinds.md`)
| kind | options | `action` |
|---|---|---|
| `factory:start` | `Start` · `Edit` · `Not now` | `{"order", "file": "proposals/<order>/p<N>.json", "hash"}` |
| `factory:autopilot` | `Start` · `Edit` · `Not now` | `{"order", "file", "hash", "days"}` |
| `factory:change` | `Accept` · `Edit` · `Save for later` | `{"order", "file": "changes/<order>/c<N>.json", "hash"}` |
| `factory:stop` | ship stage: `Ship it` · `Send back`; other stages: `Continue` · `Send back` | `{"order", "file": "stops/<order>/s<N>.json", "hash", "stage"}` |

## Notes
- Autopilot grants are workspace-wide: a valid grant covers the routine/taste stops of any person-started run order here.
- Owner-visible text fields are refused at freeze time when longer than the render cap (120 characters; stop `before` /
  `after` 80, `recommend` 40), so what the owner reads is never cut.

## Authority (what counts, phase 1)
1. **Only a person's answer counts**: `answered_by` starts with `human:` (the answer a person gives in the dashboard,
   Focus, the CLI or the phone). Agent answers on `factory:*` questions are ignored and logged — except `factory:stop` items decided with
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
- **Irreversibility is derived by the add-on** (`irreversible.py`, #681): an item whose words name a final action from a
  fixed list (send/e-mail, publish/post to, deploy/go live/launch, delete/erase/wipe/purge/overwrite, pay/charge/refund/
  purchase, merge/push to main or production, force-push, revoke, rotate a key or secret, cancel a subscription or
  contract, sign a contract) is `cant-undo` whatever the agent tagged: `orch factory stop` refuses it until it is tagged
  `cant-undo`, and `decide` treats it (and every ship-stage item) as `cant-undo` even in an older frozen file. The list
  only raises a tag, never lowers it, and is a floor: a paraphrase it does not know is still the agent's tag. `decide` is also refused on tags the grant does not list.
- Always asks the owner (fixed in the add-on, not configurable): the ship stop, scope changes, budget beyond the limits, crew
  outside an approved proposal, `cant-undo` items, new connections or credentials, other workspaces, `factory:start`,
  `factory:autopilot`, budget questions.
- Each `decide` writes a journal line `decided` (who, why) and a ticket log entry "Decided by agent:factory · <why>"; the
  daily report lists them.

## Journal
`journal.jsonl` stays unauthenticated bookkeeping (#681 decision): `.orch/addons/` is never synced (sync's
NEVER_SYNCED), and any key Factory could hold is readable by a same-user agent, so a MAC would add no protection;
authority never takes a person from the journal, only from core's answers and frozen file hashes.

## Budget
Measured active time against `active_min_cap` (#681): `measure.py` reads core's activity record (`orch record query
--ticket <t> --json`, paged) for the order and its crew tickets and adds, per run, the gaps between events, each at most
5 minutes, so a session waiting at its prompt (for the owner or for nothing) adds at most 5 minutes. `orch factory next`
and `crew start` measure; the result is cached in `ext.factory.budget.active_min_used` for the page. When the record
can't be read the cache stays for the page, but `crew start` refuses (time used unknown). `crew start` refuses at 100 % of the measured time until the owner answers a change
proposal. `api_usd_target` stays a target, not a cap (no usage-event contract for money yet), and the autopilot's
per-day limits stay targets too.

## Start gate (core `start_requires`, #681)
`crew add` makes each crew ticket with `orch ticket new … --start-requires <order>:<question>=<answer>`: the order's
`factory:start` question with `Start`, or, for a task an accepted change added, that `factory:change` question with
`Accept`. Core then refuses `orch run start` and `orch run claim` on the crew ticket (any caller, an agent's own direct
call too) until that question carries that answer from a person (`answered_by: human:…`). The field is set at creation
only (not patchable); core knows nothing about Factory. Factory counts a sub-ticket as crew only when its gate is exactly the
one its task needs (a sub-ticket an agent made with Factory's crew data but no gate is ignored). Known limit (light,
inside the workspace): tickets are synced, and core trusts a synced ticket's `answered_by` and fields like any other
reader (core-wide note, not Factory's).

## Page (phase 2a, read only)
The watcher process also serves the Factory page on `127.0.0.1:<port>` (`orch factory status --json` gives `url`;
manifest `[page] path = "/"`). The dashboard embeds it as `#addon/factory/<path>` through its `/addon/factory/` proxy
(`X-Forwarded-Prefix`), same pattern and fences as Insights: Host/Origin checks, GET only, no human key, CSP
`default-src 'self'`, kit CSS/JS from `orch_ui` (fallback: the dashboard's copy). Decisions are never made on this page
(phase 2b): inside the dashboard, a decision button posts `{type: "orch.question", ticket, question}` (the order's open
question `open.q`) to the parent window; the dashboard accepts it only from the embedded shipped add-on iframe of its own
origin, opens its own native question card for that ticket's question in a dialog (text and options come from the
dashboard's data, the person presses the option there, as on the ticket page), then posts
`{type: "orch.question.done", ticket, question}` back and the page refreshes. Outside the dashboard (or with no open
question) the button stays a link `target="_top"` to `/#ticket/<order>`. The Factory server stays read only. An open page re-reads `/api/home` every 15 s while visible and redraws only when it changed and the person is not
typing or waiting for an answer (every API answer is read fresh from the workspace; nothing is cached).

**Idea box (one click).** Inside the dashboard, *Start with this idea* posts `{type: "orch.idea", id, text}` (`id` = 8–32
lowercase letters/digits, a random request id) to the parent. The dashboard accepts it only from the embedded shipped
add-on iframe of its own origin (not in a shared copy), makes the text one plain line (no control, bidi or zero-width
characters, no leading dash, at most 500 characters) and runs its own op `addon.act {addon: <shown add-on>, verb: "idea",
target: text}` — an op that needs the page's session, so it is always the person's click, never an agent's scripted
request or a foreign frame's. It answers `{type: "orch.idea.done", id, order}` (the page opens `#/order/<order>/draft/1`)
or `{type: "orch.idea.failed", id, error}`; one idea at a time. On failure (or no answer in 30 s, or outside the dashboard)
the page keeps the text and offers *Send it to your helper in Chat instead* (`orch.say`, the old hand-off).

**Plan the run / Ask for changes (drafts).** A draft no agent works on (`phase: "draft"`, `working: false`; order summaries
also carry `draft_v`, the newest version) shows *Plan the run* and *Ask for changes* on the draft page, on the order page and
under *Drafts waiting for you* on Factory home. A draft waits only when `agent_draft` is true: the newest version is the agent's (an idea-box order, `ext.factory.idea_box`,
starts with the person's words as v1, so it needs v2 or later; an order an agent filed counts from v1). `working` is core's
Working status, except for a draft: there it is false
when no run is on the ticket, or when its LIVE session's turn ended (`orch run status` claim `live.state` `idle` or
`attention`), so the draft waits for you right after the helper's turn; the message then goes into that same session. Inside the dashboard they post `{type: "orch.send", id, ticket, text}` (text: `Now plan
the run: …` or `Change the draft: <the person's words>`, at most 1000 characters typed). The dashboard accepts it only from the
embedded shipped add-on iframe of its own origin and only for a ticket that carries that add-on's data (`ext.<add-on>`),
keeps line breaks but drops control, bidi and zero-width characters (at most 2000 characters), sends the text with its own
op `run.send` (the person's message, proven like writing to the agent on the ticket page) and, only when orch reports nothing on
the ticket (`send_result.state` is `none`), `run.start` (a live session takes the words itself: no second start). The dashboard's `/api/act` reply to `run.send` carries `send_result: {id, delivered, state}` (what orch did); the
dashboard answers done only when orch delivered the words (`delivered` > 0) or queued them (an `id`), else failed. It
answers `{type: "orch.send.done", id, ticket, delivered, queued, started}` (the page says *Sent* or *Saved*) or `{type: "orch.send.failed", id, error}`;
one at a time. Outside the dashboard the page shows a link to the ticket instead.

| GET | Answer (JSON) |
|---|---|
| `/api/home` | `{"generated_at", "orders": [order summary], "autopilot": {"on", "until", "decided_today"} \| null, "watcher": true}`; an order summary also has `working` and `draft_v` |
| `/api/order/<id>` | order summary + `proposal` (frozen data of the started or newest proposal), `drafts` `[{"v", "at"}]`, `crew` `[{"ticket", "title", "role", "agent", "status"}]`, `changes` `[{"n", "title", "adds_min", "state": "open"\|"accepted"\|"edit"\|"later"}]`, `tiny` `[{"what", "minutes"}]`, `stops` `[{"n", "stage", "data", "state", "answer", "by"}]`, `activity` `[{"at", "text"}]` (Factory lines of the order history) |
| `/api/order/<id>/draft/<v>` | `{"v", "text"}` (markdown as plain text; the page renders it as text) |
| `/api/order/<id>/file/<name>` | an image of a stop round (`png`, `jpg`, `webp`, `gif` only, from `stops/<id>/`; no other path) |
| `/api/reach` | `[{"ws", "name", "description"}]`: connected workspaces that may get group messages (empty when the relay is off; the page then shows no Ask button) |
| `/api/order/<id>/stop/<n>/scan` | `{"items": [{"i", "title", "files": [{"name", "ok", "why"?}]}]}`: the secret scan of the stop's pictures, run when the ask dialog opens |
| `/api/autopilot` | `{"grants": [{"order", "until", "may", "limits"}], "decisions": [{"order", "q", "answer", "why", "at"}]}` |

Order summary: `{"id", "title", "kind": "run"\|"autopilot", "phase": "draft"\|"proposed"\|"started"\|"edit"\|"parked"\|"shipped"\|"cancelled", "stage", "line": [{"stage", "stop", "state"}], "budget": {"used", "cap", "warn"}, "eta", "due", "open": {"q", "kind", "text", "options"} \| null, "owner_min"}` — every field derived through `flow.derive` (never `ext.factory`). #816: `stops[]` also carry `asks: [{"ws_name", "at", "state": "queued"|"delivered"|"answered"|"failed"|"closed", "replies": [{"text", "at", "by": "person"|"helper", "name"?}]}]`; `crew[]` rows carry `with: {"name", "state"}` for a hand-over task. `line[].label` comes from the frozen proposal; `open.data` carries the frozen stop/change data for stop and change questions. `phase` may also be `broken` (the add-on refused the order's files as tampered; the summary then has `problem`).
Also: `/api/home` `watcher` is `true` only while a verified watcher runs (else `false`); grants carry `live`; a draft answer
may carry `truncated: true` (over 256 KB); any answer may carry `stale: true` (a slow build gave the last good answer); with no
earlier answer a slow or failed build is `503 {"error", "stale": true}`.
Page routes (hash inside the page): `#/` home · `#/order/<id>` · `#/order/<id>/proposal` · `#/order/<id>/stop/<n>` ·
`#/order/<id>/draft/<v>` · `#/autopilot`.
