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
  alerts/<YYYY-MM-DD>.jsonl          integrity alerts (orch.record-alert/1)
  pending/<run>/<time_uuid>.json     prepared writes waiting for the run lock
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
  exceeds the 1 MB limit), the line is still written with `detail: null` and `detail_lost: true`. A detail problem
  never drops the audit line. A finished step's detail is written once: a later line with the same key keeps the first file.

## Writing (one writer per run file)

- The run's own orch process (the oneshot wrapper or the live run's watcher) is the only writer of `runs/<run>.jsonl`.
  Hooks, collectors, the broker, `orch job` and the core hand their events to it (hook entry: a short-lived `orch run event`
  call that appends under the per-run lock `runs/<run>.lock`, named with O_EXCL and
  held with a kernel lock, released in a `finally`). Each event is one line, one
  `write()` of at most 8 KB (text is cut, never the line split), so lines never mix.
- **The hook entry is narrow.** `orch run event` (the only out-of-process way in) accepts only `step`, `denial`,
  `helper.start`, `helper.end` and `usage`, and always writes `via: hook` whatever the caller sent. `task.*`, `ask`,
  `run.state`, `key.use`, `job` and `session.input` are written only in-process by the core, the broker and `orch job`
  (vectors `hook_entry`). *Implementing slice 1.7 must* also bind the call to the run (`ORCH_RUN` plus the run's per-run hook
  file token) and drop lines for another run.
- **Fail closed.** The writer takes a value hider as a required argument; there is no default and no pass-through. A hider is
  "registered" only when it was built from this workspace's key store in its **guarded orch home** (secrets.md, Where: a real
  workspace only with the account's default home, a test workspace only with a test home; any other pairing refuses). An empty or pass-through hider refuses; a store
  in an untrusted home never counts. Without a registered hider the writer refuses (`RecordRefused`, exit 2
  `Refused: recording is off until key hiding is ready.`) and nothing is written.
- **Test hider.** It lives only in the tests package (`workspace/tests/…`), is passed in by the test itself, and is never
  reachable from a CLI entry point; there is no environment switch for it. A CLI call never gets it, whatever variables
  are set (vectors `fail_closed`).
- The write order is preflight hiding and validation, run lock, strict run read, sequence/dedupe decision,
  meta creation, detail storage, then one line append on the same fd. No detail is written for a dropped line.
- The hider runs on every string of the event and of the detail file, and on error texts (secrets.md, Hiding).

## Precedence and dedupe

Sources: **hooks** (instant, full payload), **log collectors** (read the tool's log or `--json` stream; fill gaps), the
**broker**, **jobs**, the **core**. Only hooks and collectors overlap.

- Dedupe key: `(run, id, kind, finished, via_class)`, where `finished` means a non-null outcome.
  `via_class` is `hl` only for hook and log; every other origin has its own key.
- **Hooks win when outcomes agree.** The hook replaces the meaning of a log line by appending a line;
  readers retain the hook. Repeated lines from the same origin keep the first written.
- When hook and log finished outcomes disagree in `ok` or `error`, both lines are kept. The later line
  carries `conflict: true`; repeated delivery of either origin is still deduped.
- A finished line without a started line is fine. Readers apply the same idempotent rule (vectors `dedupe`).

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
| `secret.change` | broker | null | `action` (`profile.set` · `profile.remove` · `profile.get_enable` · `profile.get_disable` · `profile.agents_enable` · `profile.agents_disable`), `profile`, `by` (`human:<name>` or `reset`) | a change of a key profile or its switches (secrets.md); never a value. Written best effort: a failing writer never blocks turning a switch off |
| `job` | job | null | `job`, `type`, `state` | one line per job event that changes what people see (job-events.md); the full stream is in `jobs/` |
| `session.input` | core | null | `by`, `from`, `since`, `ended`, `reason`, `keys` | one per take-over, written at hand-back (screen.md); the typed text is never stored |

Uses by a person or script outside any run (`orch secret ...` at a terminal) are written to the unattributed run of the day: run `r_outside_<yyyymmdd>`, ticket `t_outside` (secrets.md, Where a use is recorded).

A collector that cannot tell where a skill or connection comes from writes `source: harness` (the agent tool's own),
which is hidden at the admin like a workspace name (invariant P1, usage-counts.md); it never guesses `admin` or `builtin`.
Readers skip unknown `kind`s (they are never shown as steps or counted).

`coverage`: `full` when the source saw the whole step, `partial` when something is missing (the collector cannot see chat
text, output was cut, helpers are not visible). Capability flags per adapter (agents.json) say what a source can see;
`orch record counts` turns them into "unknown / not seen" (counts.md).

## Retention (owner decision R5)

`[record] keep_days = 90` (30 · 90 · 365) and `[record] max_mb = 2048`. Pruning runs when a run ends and once a day:
1. Before anything is deleted, the run is folded into `counts/<day>.json` (counts never depend on detail).
   Fold must be idempotent per run: retention may fold again after a run was skipped.
2. Runs that ended more than `keep_days` ago lose their detail folder and their run file (and `jobs/<run>/`).
3. While the record is over `max_mb`: delete the detail folder of the oldest ended run, then (when no detail is left) the
   oldest ended run file. A running run is never pruned.
4. Counts are kept until "Delete all records". "Delete detail for this ticket" (`orch record delete-detail <ticket>`, a
   person only: `record.delete_detail` proof, invariant H1) deletes the detail folders of that ticket's runs and sets nothing else; events then show "details not available".
A run that is not ok or has pending lines is skipped; other runs proceed.
Pending runs report `status: unavailable, reason: pending` to retention. Under the run lock, read again
and verify the run still ended. The result retains the first non-ok status, reason, message and alert.
Vectors `retention` fix the order.

## Reading: `orch record tail | query | counts | delete-detail`

- `orch record tail [--ticket T | --run R] [--since <cursor>] [--follow] --json` → NDJSON on stdout, one object per line:
  `{"type": "event", "cursor": "<c>", "event": {…}}`, `{"type": "ping", "cursor": "<c>", "at"}` every 15 s while following,
  `{"type": "error", "error": "<plain words>", "code"}` then exit 2. A cursor that names a run that is gone gives
  one `unavailable` marker for that run (`status: unavailable, reason: missing`) and the stream goes on; the old
  whole-cursor `reset` line is not used by the real command.
  Multi-run streams also emit `{"type": "unavailable", "cursor", "run", "status", "reason", "message"}`
  once per changed read status; invalid lines use `status: ok, reason: skipped`. Single-run failures use
  `tampered`, `not_available`, or `not_found` (missing) and exit 2.
  Without `--since` it starts at the first retained event; events of one run come in `seq` order, runs interleave by `at`.
  Readers already dedupe (above), so a reconnect with the last cursor never shows a step twice.
- Cursors are opaque strings `rc1.<base64url>` (no padding). Tail producers encode `{"r": {"<run>": <last seq>, …}}` (compact JSON, zlib-compressed); when that no longer fits, the runs whose events were all sent
  (oldest last event first) are left out with an `unavailable` marker (reason `trimmed`) and may be sent again after a
  reconnect (a duplicate, never a loss); when nothing can be left out the command ends with `too_large`. A run file
  shorter than its cursor entry is marked `rewound` and sent again from its start; a rewrite of the same length is not
  detected. A cursor belongs to the filter (`--ticket`, `--run`) it came from: another filter may send events again;
  consumers never look inside and keep the newest cursor they got. *Implementing slice 1.6 must* check every decoded run id
  and detail id against its pattern before it becomes a file path (a cursor `{"../x": 1}` → `invalid`).
- `orch record query [--ticket T] [--run R] [--kind K]… [--from <time>] [--to <time>] [--limit N] [--after <cursor>] --json`
  → a page `{"items": [event…], "next": "<cursor>" | null, "unavailable": [{run, status, reason, message}]}` (cli-answer.schema.json `page`), newest first, limit 1–500
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

### The `claude -p --output-format stream-json --verbose` stream (`claude-stream-json/1`)

Declared by `oneshot.events` of the adapter (agent-adapter.schema.json) with `capabilities.activity: live`. One JSON object per
line (captures: `workspace/tests/fixtures/w2b/claude/`). A tool call is a `tool_use` content block of an `assistant` line and its
result a `tool_result` block of a later `user` line; the pair is one started and one finished `step` with the same `id` = the tool-call
id (so a hook's line and this one dedupe). `is_error: true` → `outcome.ok: false`; input and result go to the detail file.
- `system/init` → `session` and `run.state working`; other `system` lines and unknown types → no event, counted by the collector.
- `Task`/`Agent` tool → `helper.start` / `helper.end` (agent `h_<n>`, `parent` = the starter); lines with `parent_tool_use_id` belong to that helper.
- `mcp__<server>__<tool>` → `used.kind` mcp (server, tool, source `harness`); `Skill` → kind skill (source `harness`); other tools → kind tool, source `builtin`.
- `assistant` text → `run.state working` with `data.say`; `thinking` → nothing; an unknown block type makes the next step `partial`.
- `rate_limit_event` → `usage` (`used`, `window`, `status`); `result` → one `denial` per `permission_denials` entry (id = its `tool_use_id`),
  `usage` (`tokens_in` = input + cache creation + cache read, `tokens_out`) and `run.state` idle (failed when `is_error`).
- Garbled or cut lines are counted and skipped; a replay of the same lines adds nothing (ids are the tool-call ids).

## Integrity

Every read and write uses one hardened open. From `.orch` down, directories may
not be links or name-surrogate reparse points. Files must be regular, have one
link, and belong to the current user on POSIX. Readers return an explicit
`ok`, `unavailable`, or `tampered` status; missing files are `unavailable/missing`.

| Reason | Meaning |
| --- | --- |
| link | A symbolic link was found |
| reparse | A redirecting Windows reparse point was found |
| hardlink | A file has more than one link |
| foreign_owner | A file or folder belongs to another user |
| not_regular | A file is not a regular file |
| not_dir | A folder is not a directory |
| swapped | A checked file or folder was replaced, or stored identity differs |
| missing | No record file exists |
| io | Records cannot currently be read |

The messages are exactly:

- Tampered: “Some records of this run were changed outside orch. To be safe, orch does not show them. Nothing was deleted.”
- I/O: “The records of this run cannot be read right now. Try again later.”
- Missing: “There are no records for this run.”
- Lost detail: “Details not available.”
- Skipped lines: “Some lines of this run could not be read and are not shown.”

Integrity alerts (`orch.record-alert/1`) live at
`.orch/record/alerts/<YYYY-MM-DD>.jsonl`. They contain no paths, user ids, or
record contents. Each process emits one per day, target, run, and reason. If
alert storage fails, the alert remains attached to the result or exception.

Writing validates and hides the event and both detail outcomes before taking
the run lock. A strict read of the run fd precedes meta, detail, and line writes;
the same fd is used to append. Dedupe happens before detail storage. A detail
collision, invalid JSON, excessive size, or I/O failure keeps the audit line
with `detail: null, detail_lost: true`. Hiding failures refuse the write.
Oversized event data becomes `{"cut": true}` for every kind. A torn final line
is separated by a newline; sequence numbers count all physical lines.

Only hook and log origins share dedupe keys. All other origins have separate
`(run, id, kind, finished, via)` keys. Hook ids in the writer/collector namespace
`r_[a-z0-9_]{6,32}:.*` become `x_` plus 32 lowercase hex characters of
SHA-256 of `b"orch.id.hook/1\0" + hidden_id.encode("utf-8")`. When hook and log
finished outcomes disagree in `ok` or `error`, both lines remain and the later
line has `conflict: true`.

Lock waits cover the 30-second stale window. A timed-out write is spooled in
`pending/<run>/` and drained in name-time order by the next append, under the
same run lock. The spool receipt has `pending: true` and `seq: null`; a default
id is omitted until the line is committed. `read_run` reports `status: ok`,
`reason: pending`, and `pending: n` while prepared writes remain. Readers show
this status alongside committed events.

POSIX uses `flock` on the lock fd for mutual exclusion, released by the kernel
on process death; Windows uses `msvcrt.locking` when available. Stale lock names
are removed only after acquiring the kernel lock and checking identity. Without
kernel locking, the holder refreshes mtime before slow steps and retention checks
lock identity again before deleting. Retention preflights `pending/<run>` under
the lock and skips runs with pending files without folding or deleting them.

Retention skips a run that is unavailable, tampered, or has pending lines: it folds and deletes
nothing for that run and keeps the alert; other runs proceed. The result carries
the first non-ok status, reason, and message. Under each run lock, retention
reads again and checks the run still ended before folding or deleting.

Reading consumers display a tail line of type `unavailable` with cursor, run,
status, reason, and message, including `status: ok, reason: skipped` for invalid
lines. Query and counts include an `unavailable` list (empty when complete);
counts include `complete: false` when that list is nonempty. Errors use
`tampered`, `not_available`, or `not_found` (missing detail/run).

Windows re-lstat checks narrow but do not close the replacement race. Non-surrogate
OneDrive placeholders are allowed. Secrets shorter than the hider's minimum
are not hidden. In-place edits by the same user are not detected: trust is based
on file identity, not content authentication. Tests compare the bundled schema
with this contract to detect drift.
