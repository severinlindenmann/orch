# The record: `orch.activity/1`

orch records once what agents do: every step, the skill, built-in tool, connection (MCP) and key it used, every helper and
job, and how it ended. Focus shows it live, the ticket page keeps it, Insights counts it. Every view reads it the same way:
through `orch record … --json` (add-ons never read the files).

Schema: `activity.schema.json` (one event, plus `$defs/detail_file`). Examples: `examples/activity/`, `examples/activity-detail/`.
Vectors: `vectors/activity-v1.json` (ids, detail file names, dedupe, retention, fail closed, the Codex mapping on real
captures). T0: `uv run --with jsonschema --with rfc3339-validator --with cryptography python contracts/validate.py activity`.
The core names no agent tool here: tool-specific mapping lives in the collectors and in agents.json (agent-adapter.schema.json).

## Where (owner decision R2)

```
.orch/record/                         LOCAL, in .orch/.gitignore ("record/") and the .git/info/exclude block. Never committed
  meta.json                           {"schema": "orch.record/1", "since": "<time>", "keep_days": 90, "max_mb": 2048}
  runs/<run>.jsonl                    one file per run, one orch.activity/1 event per line
  detail/<run>/<file name>.json       full payload of one event ($defs/detail_file), at most 1 MB, key values hidden
  jobs/<run>/<job>.jsonl              orch.job/1 events of one job (job-events.md)
  counts/<YYYY-MM-DD>.json            daily counts (orch.counts/1 day file, counts.md), kept after detail is gone
  proposals/<id>.json                 check-up proposals (proposal.md)
  outbox-usage/<YYYY-MM-DD>.json      daily counts waiting for the relay (usage-counts.md)
```

Inside the workspace (not the orch home): if the workspace folder syncs to a cloud drive, the records sync too; Insights
settings says so. Folders are 0700, files 0600 (POSIX). The record never follows a symlink (`.orch/record` or any part of it
being a symlink → the writer refuses).

**Recording since.** `meta.json` `since` is set when the first event is written. Nothing is migrated from Focus's old step
log; Insights shows "Recording since Mon 16 Nov 2026".

## Ids

- `id` = the agent tool's own tool-call id when the source carries one (a hook payload and the tool's log carry the same id,
  which is what makes dedupe work). Otherwise `<run>:<seq>` (e.g. `r_8k2m01:12`). A collector that knows a tool-call id
  must use it; it must not invent one. A tool-call id with characters outside `[A-Za-z0-9_.:-]` (or longer than 160) is
  replaced by `x_` + the first 32 hex of its sha256, the same for hook and collector, so dedupe still works (vectors `ids`).
- `seq` = position in the run file, 1, 2, 3 …, assigned by the writer. Never reused, never reordered.
- `run`, `session`, `agent` (`main` or `h_<n>`), `parent` (null for main) bind the event; `ticket` is the run's ticket.
- **Detail file name** (invariant): always 32 lowercase hex characters, `sha256(b"orch.detail/1\0" + run + b"\0" + kind +
  b"\0" + id)[:32]` (UTF-8, vectors `detail_names`); no raw id ever becomes a file name, so case-insensitive file systems,
  separators and reserved names cannot make two events share a file. The path is `detail/<run>/<file name>.json`. The file
  stores `id` and `kind`; a writer never overwrites a file whose stored `(kind, id)` differs.
- **Detail lost.** When a payload exists but cannot be stored (the file name is taken by another event, a write fails, or it
  is too large even after cutting), the line is still written with `detail: null` and `detail_lost: true`. A detail problem
  never drops the audit line. A finished step's detail is written once: a later line with the same key keeps the first file.

## Writing (one writer per run file)

- The run's own orch process (the oneshot wrapper or the live run's watcher) is the only writer of `runs/<run>.jsonl`.
  Hooks, collectors, the broker, `orch job` and the core hand their events to it (hook entry: a short-lived `orch run event`
  call that appends under the per-run lock `runs/<run>.lock`, O_EXCL, released in a `finally`). Each event is one line, one
  `write()` of at most 8 KB (text is cut, never the line split), so lines never mix.
- **The hook entry is narrow.** `orch run event` (the only out-of-process way in) accepts only `step`, `denial`,
  `helper.start`, `helper.end` and `usage`, and always writes `via: hook` whatever the caller sent. `task.*`, `ask`,
  `run.state`, `key.use`, `job` and `session.input` are written only in-process by the core, the broker and `orch job`
  (vectors `hook_entry`). *Implementing slice 1.7 must* also bind the call to the run (`ORCH_RUN` plus the run's per-run hook
  file token) and drop lines for another run.
- **Fail closed.** The writer takes a value hider as a required argument; there is no default and no pass-through. A hider is
  "registered" only when it was built from this workspace's key store in its **guarded orch home** (secrets.md, Where: a real
  workspace only with the account's default home, a test workspace only with a test home; any other pairing refuses). An empty store
  in the trusted home is fine (no keys, nothing to hide, the generic secret patterns of `phone_view.redact` still run); a store
  in an untrusted home never counts. Without a registered hider the writer refuses (`RecordRefused`, exit 2
  `Refused: recording is off until key hiding is ready.`) and nothing is written.
- **Test hider.** It lives only in the tests package (`workspace/tests/…`), is passed in by the test itself, and is never
  reachable from a CLI entry point; there is no environment switch for it. A CLI call never gets it, whatever variables
  are set (vectors `fail_closed`).
- The hider runs on every string of the event and of the detail file, and on error texts (secrets.md, Hiding).

## Precedence and dedupe

Sources: **hooks** (instant, full payload), **log collectors** (read the tool's log or `--json` stream; fill gaps), the
**broker**, **jobs**, the **core**. Only hooks and collectors overlap.

- Dedupe key: `(run, id, kind, finished)` where `finished` = `outcome` is not null. So a step is at most two lines: started
  (`outcome: null`) and finished.
- **Hooks win.** When a line with the same key exists, the writer drops the new one, except that a `hook` line replaces the
  meaning of an earlier `log` line: the writer appends it and readers keep, per key, the line with the highest precedence
  (`hook`, `broker`, `job`, `core` = 2, `log` = 1), ties → the first written.
- A finished line without a started line is fine (collectors that only see the end).
- Readers apply the same rule (it is idempotent), so a crash between two writers never shows a step twice (vectors `dedupe`).

## Kinds

| kind | via | used | data | Notes |
|---|---|---|---|---|
| `step` | hook, log | skill · tool · mcp | – | one tool call; `text` = "Read report-2025-11.pdf" |
| `task.start`, `task.done` | core | null | `check` (`c<n>`) | from the ticket |
| `ask` | core | null | `q` (`q<n>`) | a question on the ticket |
| `denial` | hook, log, core | tool · mcp | – | `outcome.ok: false`, `error` = "Not allowed by this workspace" |
| `helper.start`, `helper.end` | hook, log | helper | – | `agent` = the helper `h_<n>`, `parent` = who started it |
| `run.state` | core | null | `state` | starting · working · waiting_you · idle · done · failed · stopped |
| `usage` | hook, log | null | `used` 0..1, `window`, `status`, `tokens_in/out` | plan or token use |
| `key.use` | broker | key (`action` = env · file · exec · get) | `profile`, `command`, `skill`, `refused`? | one per key per broker call, never the value (secrets.md) |
| `job` | job | null | `job`, `type`, `state` | one line per job event that changes what people see (job-events.md); the full stream is in `jobs/` |
| `session.input` | core | null | `by`, `from`, `since`, `ended`, `reason`, `keys` | one per take-over, written at hand-back (screen.md); the typed text is never stored |

A collector that cannot tell where a skill or connection comes from writes `source: harness` (the agent tool's own),
which is hidden at the admin like a workspace name (invariant P1, usage-counts.md); it never guesses `admin` or `builtin`.
Readers skip unknown `kind`s (they are never shown as steps or counted).

`coverage`: `full` when the source saw the whole step, `partial` when something is missing (the collector cannot see chat
text, output was cut, helpers are not visible). Capability flags per adapter (agents.json) say what a source can see;
`orch record counts` turns them into "unknown / not seen" (counts.md).

## Retention (owner decision R5)

`[record] keep_days = 90` (30 · 90 · 365) and `[record] max_mb = 2048`. Pruning runs when a run ends and once a day:
1. Before anything is deleted, the run is folded into `counts/<day>.json` (counts never depend on detail).
2. Runs that ended more than `keep_days` ago lose their detail folder and their run file (and `jobs/<run>/`).
3. While the record is over `max_mb`: delete the detail folder of the oldest ended run, then (when no detail is left) the
   oldest ended run file. A running run is never pruned.
4. Counts are kept until "Delete all records". "Delete detail for this ticket" (`orch record delete-detail <ticket>`, a
   person only: `record.delete_detail` proof, invariant H1) deletes the detail folders of that ticket's runs and sets nothing else; events then show "details not available".
Vectors `retention` fix the order.

## Reading: `orch record tail | query | counts | delete-detail`

- `orch record tail [--ticket T | --run R] [--since <cursor>] [--follow] --json` → NDJSON on stdout, one object per line:
  `{"type": "event", "cursor": "<c>", "event": {…}}`, `{"type": "ping", "cursor": "<c>", "at"}` every 15 s while following,
  `{"type": "reset", "cursor": "<c>", "reason": "pruned" | "deleted"}` when the cursor points at data that is gone (start
  over from the returned cursor), `{"type": "error", "error": "<plain words>", "code"}` then exit 2.
  Without `--since` it starts at the first retained event; events of one run come in `seq` order, runs interleave by `at`.
  Readers already dedupe (above), so a reconnect with the last cursor never shows a step twice.
- Cursors are opaque strings `rc1.<base64url>` (no padding). Producers encode `{"<run>": <last seq>, …}` as compact JSON;
  consumers never look inside and keep the newest cursor they got. *Implementing slice 1.6 must* check every decoded run id
  and detail id against its pattern before it becomes a file path (a cursor `{"../x": 1}` → `invalid`).
- `orch record query [--ticket T] [--run R] [--kind K]… [--from <time>] [--to <time>] [--limit N] [--after <cursor>] --json`
  → a page `{"items": [event…], "next": "<cursor>" | null}` (cli-answer.schema.json `page`), newest first, limit 1–500
  (default 100). `--detail <id> --run R` → one detail file.
- `orch record counts --json` → counts.md. `orch record propose` → proposal.md (check-up runs only). `orch record delete-detail <ticket> --json` → `{"deleted": n}` (person only).
- Refused (exit 2, `{"error", "code"}`) for `delete-detail` without a valid proof (human-proof.md), for a ticket that does not exist, and when the
  record folder is unsafe (symlink).

## Mapping from a JSON event stream (one-shot collectors)

The collector of an adapter with a machine-readable stream (agent-adapter `stream_args`) maps lines to events. The reference
mapping for the `item.*` stream shape (thread.started, turn.started, item.started, item.completed, turn.completed) is fixed in
`vectors/activity-v1.json` `stream_mapping`, built on real captures (`workspace/tests/fixtures/w2b/codex/`):
- `thread.started` → the run's `session` (no event); `turn.started` → `run.state working`.
- `item.started` command_execution → `step` (started, `used` = tool `Run command`, source `builtin`). Item ids restart in
  every process, so `id` = `<run>:<turn>:<item id>` (`turn` = number of `turn.started` lines so far in this run, from 1).
  `item.completed` command_execution → the finished `step` (`ok` = `exit_code == 0`, `error` = "Exit code <n>: <first
  output line, ≤ 200>" when it failed; the command and full output go to the detail file, `text` = the command without the
  shell wrapper, ≤ 200).
- Other item types: `file_change` → step, tool `Edit`; `mcp_tool_call` → step, `used.kind` mcp with server and tool name;
  `web_search` → step, tool `Web search`; `reasoning`, `todo_list` → no event.
- `item.completed` agent_message → `run.state working` with `data.say` = the message, one line, ≤ 200 characters (Focus's
  "Now" line); `text` = the same; the full message goes to its detail file.
- `item.completed` error → never a failed step and never an event; it is kept in the detail of the run's first step
  (local setup warnings such as the hook-trust notice appear in every real capture and must be tolerated).
- `turn.completed` → `usage` (`tokens_in`, `tokens_out`, `used` 0 when unknown) and `run.state idle`.
- Unknown item types → skipped, `coverage` of the run's next step becomes `partial`.
