# The record: `orch.activity/1`

orch records once what agents do: every step, the skill, built-in tool, connection (MCP) and key it used, every helper and
job, and how it ended. Focus shows it live, the ticket page keeps it, Insights counts it. Every view reads it the same way:
through `orch record … --json` (add-ons never read the files).

Schema: `activity.schema.json` (one event, plus `$defs/detail_file`). Examples: `examples/activity/`, `examples/activity-detail/`.
Vectors: `vectors/activity-v1.json` (ids, detail file names, dedupe, retention, fail closed, the Codex mapping on real
captures, `files` shapes and normalisation). T0: `uv run --with jsonschema --with rfc3339-validator --with cryptography python contracts/validate.py activity`.
The core names no agent tool here: tool-specific mapping lives in the collectors and in agents.json (agent-adapter.schema.json).

## Where (owner decision R2)

```
.orch/record/                         LOCAL, in .orch/.gitignore ("record/") and the .git/info/exclude block. Never committed
  alerts/<YYYY-MM-DD>.jsonl          integrity alerts (orch.record-alert/1) and a person's changes (orch.record-change/1)
  alerts/hook-lost-<YYYY-MM-DD>.jsonl  hook entries of a proven caller that could not be written: {v, schema
                                      "orch.record-lost/1", at, run, reason: hider_off | invalid | too_large | other_run};
                                      the run's own wrapper adds collector_error (its collector failed on a turn, or the
                                      run file could not be read to number it; the run goes on; optional `error` = the
                                      exception's type name, never its message), hooks_off (the tool's settings in the
                                      agent's folder or the person's own switch its hooks off) and hooks_missing (a
                                      turn's log has tool calls, no hook line saying the same arrived); `orch job` adds
                                      job_activity (a job line was stored, its activity line was not);
                                      no content; 1 per run and reason per minute, 50 lines per run, then one "trimmed"
                                      line (run set), and a global "trimmed" line (run null) when the file passes 1 MB
  alerts/hook-lost-unattributed-<YYYY-MM-DD>.jsonl  the same for a caller NOT proven to be in the run (not_active |
                                      other_run | not_provable): run is null, never a run id the caller named; 1 per reason per minute
  pending/<run>/<time_uuid>.json     prepared writes waiting for the run lock; committed first under the lock. One
                                      that cannot be read, checked or committed is left in place with an alert
                                      (target folder) and skipped, never raised: it never stops the run's record
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
- `seq` = position in the run's chain (Authenticated record), 1, 2, 3 …, assigned by the writer. Never reused, never reordered.
- `run`, `session`, `agent` (`main` or `h_<n>`), `parent` (null for main) bind the event; `ticket` is the run's ticket.
- **Detail file name** (invariant I4): always 32 lowercase hex characters, `sha256(b"orch.detail/2\0" + run + b"\0" + kind +
  b"\0" + id + b"\0" + ticket)[:32]` (UTF-8; vectors `detail_names`). **An event with no ticket gets no detail file**: its
  `detail` stays null, it is not `detail_lost`, the line keeps its other fields (the detail schema requires `ticket`). No raw id ever
  becomes a file name, so case-insensitive file systems, separators and reserved names cannot make two events share a file.
  The ticket is part of the name, so two tickets never share a detail file, even with the same run, kind and id: a line of
  ticket B can only name a file made for B. The path is `detail/<run>/<file name>.json`. The file stores `id`, `kind` and
  `ticket`; a writer never overwrites a file whose stored `(run, kind, id, ticket)` differs. A reader recomputes the name
  from the stored `(run, kind, id, ticket)` and refuses a file whose name does not match (`swapped`); `--detail` also
  refuses (`tampered`) a file whose stored `ticket` or `id` is not the one of the line pointing at it (always compared: a
  line with no ticket never matches a stored `t_…`).
  Detail files made before the ticket-bound name (`orch.detail/1`) are not read (a read reports them `swapped`) and not
  migrated or deleted by delete-detail: the record store was not released before this rule (pre-release, no legacy rule).
- **Detail lost.** When a payload exists but cannot be stored (the file name is taken by another event, a write fails, or it
  exceeds the 1 MB limit), the line is still written with `detail: null` and `detail_lost: true`. A detail problem
  never drops the audit line. A finished step's detail is written once: a later line with the same key keeps the first file,
  except a log line after a hook line of that call (the log wins, Precedence and dedupe), which writes its own.

## Writing (one writer per run file)

- The run's own orch process (the oneshot wrapper or the live run's watcher) is the only writer of `runs/<run>.jsonl`.
  Hooks, collectors, the broker, `orch job` and the core hand their events to it (hook entry: a short-lived `orch record hook`
  call that appends under the per-run lock `runs/<run>.lock`, named with O_EXCL and
  held with a kernel lock, released in a `finally`). Each event is one line, one
  `write()` of at most 8 KB (text is cut, never the line split), so lines never mix.
- **The hook entry is narrow.** `orch record hook` (the only out-of-process way in) accepts only `step`,
  `helper.start` and `helper.end` (the kinds whose line can be provisional, Precedence and dedupe), and always writes
  `via: hook` whatever the caller sent. `denial` (it says how a call ended) and `usage` (numbers no log line checks)
  come only from the log and the core; `task.*`, `ask`, `run.state`, `key.use`, `job` and `session.input` are written
  only in-process by the core, the broker and `orch job` (vectors `hook_entry`). No other CLI path writes `via: hook`. The call is bound to the run: `ORCH_RUN` and `ORCH_TICKET` must name a live claim that belong
  together **and the calling process must be a descendant of the claim's process** (its wrapper pid or agent pid, start
  time checked), so a process outside the run cannot write into it by setting the same variables; a line naming another
  run is dropped; the caller's `at` and `harness` are never kept (time of the call; the tool this process runs under).
  Where the process tree cannot be read (**Windows today: the hook records nothing**, reason `not_provable`, until the
  token below or a Windows process-tree proof exists) nothing is written. Nested runs: the check accepts the claim's own
  pids anywhere among the caller's ancestors, so a call from a child run's tree can still name its parent run; telling
  them apart needs the token below. `orch record hook` always exits 0 with nothing on stdout and at most one stderr
  line (a tool's hook exit 2 would block the tool call) unless `--strict` (then 2): any `orch record [flags] hook
  [anything]` is taken before the parser, the Chat guard and the notices. The `orch` console script's own entry
  (`orch_entry:main`, stdlib only) checks this first, before orch is imported and before the update check: its
  watchdog starts before the import, and anything that still fails (an update in progress, an import of a broken
  install that raises or hangs, a SystemExit) ends with the same exit; `python -m orch` does the same. Only `--by`
  is known as a flag that takes a value: a global flag before `record` (`orch --json record hook`) or another flag
  with a value before `hook` is not this form and goes to the parser (which can exit 2). The hook wiring calls
  exactly `orch record hook` (optionally `--strict`): the root comes from `ORCH_ROOT` or the working folder only;
  other flags are ignored. The hook's watchdog (exit 0 after 4 s) is cancelled before the first write, so it
  never ends the process inside a write. *Follow-up:* the per-run hook file token
  (made at claim time) would replace the ancestry rule; it needs the claim code (runs.py).
  The event `id` is the agent tool's own tool-call id (Claude: `tool_use_id`, `toolu_…`) put there by the caller
  (the hook wiring of slice 1.8 must pass it; a hook line and the collector line with that id merge) (this entry takes
  event-shaped lines, not raw tool payloads); the writer hashes an unsafe one once, the same for hook and collector.
  A payload over 8 MB is not read further: a minimal `step` with `detail_lost: true` is written, never no line.
- **Reserved ids.** `<run>:<seq>` is the default id of collector lines (and of other origins); a hook line without an id
  gets `h_<run>:<seq>` instead, so a hook line can never take the id of a collector line still to come (dedupe would
  drop it; vectors `hook_default_id`). A hook-sent id in either namespace (`<run>:…`, `h_<run>:…`) is replaced by `x_` +
  32 hex (vectors `hook_namespace`); any other origin's `h_<run>:…` is replaced by `x_` + the first 32 hex of its
  sha256 (vectors `reserved_ids`), so only the writer's own default can be in that namespace.
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
  Repeated lines from the same origin keep the first written.
- **Hook lines are inside the agent's trust boundary.** The hook runs as a child of the agent, and the agent can run
  the same command itself with any payload and read its own tool-call ids (the process-tree proof only shows it
  comes from inside the run). So a hook line is the agent's word:
  - **The hook entry never says a call ended well.** On every path (the tool's payload or an event-shaped line) it
    writes a line with an outcome as **provisional**: `outcome` `{ok: null, error: null, ms: null}`, whatever the
    caller sent (a claimed `ok: true` included). Only a claimed **failure** is kept, since it only narrows trust:
    `{ok: false, error: <fixed code>, ms: null}`, the code `interrupted` or `tool_failed` (any other error the
    caller sent becomes `tool_failed`); the tool's own error text is never in the line, only in the detail file
    (hidden and cut like any output). Claude's `PostToolUseFailure` hook (`is_interrupt: true` → `interrupted`)
    is such a failure; its `PostToolUse` is provisional. Without a log (a live run) a successful call stays
    "finished, result unknown" and a failed one is recorded as failed (vectors `hook_entry`).
  - **The log line wins, started and finished alike.** For a key that a log line also has, the log line replaces the
    hook line (it is written, with its own detail file over the hook's, and readers keep it), and a hook line after
    any log line of that call (run, id, kind; started or finished) is dropped (vectors `dedupe`).
  - **Disagreement is kept, never hidden.** When a hook line of the call says something else than the log line
    (`used`, `text`, `files`, whether either is finished; or, both finished and the hook's not provisional, `ok` or
    `error`, where a hook's fixed failure code is never compared with the log's error text: a hook failure and the
    log's failure agree), both lines are kept and the log line carries `conflict: true`; the log line is the one to believe:
    counts take its line of the call, even a started one over a hook end (result unknown). A kept hook line and its
    `conflict` log line share one detail file name: when the log line has a detail, the file is the log's.
  - The writer removes the hook's detail file when the log line that replaced it has none of its own (lost or none),
    so the agent's payload never stays behind without a line pointing to it. Writing over a detail file is atomic
    (a temporary file in the same folder, then a rename): a reader sees the old file or the new one; a failed
    rename leaves the old file and marks the line `detail_lost`.
  The hook's detail keeps the tool's input with every text cut at 32 K characters (lists at 100 entries) and only an
  allow-list of plain result fields, each text cut the same way (never the tool's internal copies such as
  `originalFile` or `structuredPatch`). The agent can also switch the tool's hooks off (its folder's or the person's
  own tool settings); the oneshot wrapper then leaves a `hooks_off` or `hooks_missing` trace (Where), and the log still
  records every call. Both traces are hints: hooks the agent adds itself, a settings file changed and changed back
  between turns, or a started hook line forged to match the log are not detected; calls of a turn spooled behind a
  busy lock are not counted for `hooks_missing`.
- A finished line without a started line is fine. Readers apply the same idempotent rule (vectors `dedupe`).

## Kinds

| kind | via | used | data | Notes |
|---|---|---|---|---|
| `step` | hook, log | skill · tool · mcp | – | one tool call; `text` = "Read report-2025-11.pdf" |
| `task.start`, `task.done` | core | null | `check` (`c<n>`) | from the ticket |
| `ask` | core | null | `q` (`q<n>`) | a question on the ticket |
| `denial` | log, core | tool · mcp | – | `outcome.ok: false`, `error` = "Not allowed by this workspace" |
| `helper.start`, `helper.end` | hook, log | helper | – | `agent` = the helper `h_<n>`, `parent` = who started it |
| `run.state` | core | null | `state` | starting · working · waiting_you · idle · done · failed · stopped |
| `usage` | log | null | `used` 0..1, `window`, `status`, `tokens_in/out` | plan or token use |
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

## Files

A `step` (any via) may carry `files`: an array of 0..8 strings, the workspace files or folders the step named. Every entry
is a **workspace-relative POSIX path** (`src/app.py`): 1..260 characters, NFC, no leading `/`, no `..` segment, no
backslash, drive letter, scheme (`file:`) or UNC form, no start with `~` or `$`, no Unicode control or format character
(categories Cc, Cf, Zl, Zp: NUL, C1, bidi overrides and isolates, zero-width, line/paragraph separators: they spoof what a
person reads). The schema `$defs/file_path` lists the BMP characters; the writer's check (`record_files.file_ok`, the one
shared check) is the full rule and also checks NFC. Any other kind never carries `files` (the schema refuses it there). Vectors `files` (shape, what the writer
keeps) and `files_normalise` (producer normalisation).

- **Who fills it.** Collectors: the stream-json collector from the file-tool inputs (`file_path`, `notebook_path`,
  `path` of the read, edit, write, notebook-edit, find-files and search tools); the `item.*` collector from the paths
  of a `file_change` item. The hook entry takes `files` from the caller's line (the hook filter keeps it). Producers
  make every path relative to the run's workspace root (`.` segments and inner `..` resolved, NFC); a path outside the
  workspace, the root itself, or one without a root to compare an absolute path with is **dropped**, never recorded.
  Repeats are dropped, at most 8 are kept, and only the first 64 entries of a producer's list are looked at. A root
  that is `/` is refused (it would make every absolute path a workspace path). The caller of a collector passes the
  workspace as `ctx["workspace"]`, one root or a list (the root and its resolved form); this module does no I/O.
  Size budget: the writer keeps entries in order while each is at most 512 serialized bytes and all together at most
  2048; the rest are dropped. A line that is still over the 8192-byte cap loses `files`, then `data` (replaced by
  `{"cut": true}`), so the audit line is never dropped for its optional parts.
- **The writer re-checks.** After the value hider the writer checks every entry again: an entry with a bad shape is
  dropped, and so is an entry the hider (or the plain-text cleaner) would change (a path containing a stored key value is
  never stored, not even hidden). Drops are not counted or flagged; the audit line is never dropped for a bad entry. Only
  the first 8 valid entries are kept; `files` on another kind, or not an array, is removed. A path the plain-text
  cleaner changes (a name that looks like a key or token) is lost silently: acceptable, `files` is display only.
- **Display only.** `files` is never used for an access decision; an agent can name any workspace-relative path
  (Level 1, like `text`). Readers (`orch record tail | query --json`) return it as stored; the detail file is unchanged.

## Retention (owner decision R5)

`[record] keep_days = 90` (30 · 90 · 365) and `[record] max_mb = 2048` (512 · 1024 · 2048 · 4096). Pruning uses the
**effective** values (`config.record_keep_days` / `record_max_mb`): the lower of the file value and the person's settings
record (default record 90 / 2048; human-proof.md, Settings), so a file value alone never keeps more; a file value is
snapped down to the list with a floor of 30 / 512, so a file edit alone never makes pruning delete nearly everything. Raising either needs an
`insights.settings` proof bound to the new value (target `insights.keep_days=365`); lowering does not, and deletes nothing at once (the next pruning applies it).
Pruning runs when a run ends and once a day:
1. Before anything is deleted, the run is folded into `counts/<day>.json` (counts never depend on detail).
   Fold must be idempotent per run: retention may fold again after a run was skipped.
2. Runs that ended more than `keep_days` ago lose their detail folder and their run file (and `jobs/<run>/`).
3. While the record is over `max_mb`: delete the detail folder of the oldest ended run, then (when no detail is left) the
   oldest ended run file. A running run is never pruned.
4. Counts are kept until "Delete all records". "Delete detail for this ticket" (`orch record delete-detail <ticket>`, a
   person only: `record.delete_detail` proof, invariant H1) deletes the detail files that ticket's own lines point at and sets nothing else; events then show "details not available".
A run that is not ok or has pending lines is skipped; other runs proceed.
Pending runs report `status: unavailable, reason: pending` to retention. Under the run lock, read again
and verify the run still ended. The result retains the first non-ok status, reason, message and alert.
Vectors `retention` fix the order.

## Reading: `orch record tail | query | counts | settings | delete-detail`

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
- `orch record counts --json` → counts.md. `orch record propose` → proposal.md (check-up runs only).
- `orch record settings --json` (no proof; it writes nothing but a lower retention record, human-proof.md) → `{"keep_days": 90, "max_mb": 2048, "share_counts": true,
  "share_names": false, "record_mb": <int>, "detail_mb": <int>, "runs": <int>}`: the effective settings (human-proof.md,
  Settings), the size of `.orch/record/` and of `detail/` in MB (rounded up) and the number of run files, read through the
  hardened helpers (no record yet: 0). When the record cannot be read, the sizes and `runs` are `null` and the answer
  carries the read marker `status` (`unavailable` | `tampered`), `reason`, `message` (exit 0).
- **Delete detail.** `orch record delete-detail <ticket> --proof-stdin --json` → `{"deleted": n, "ticket": "t_…", "kept":
  k, "unreadable": u, "skipped": s}` (a person only: op `record.delete_detail`, target = the ticket id). The detail files the ticket's
  OWN lines point at go (`detail/<run>/<file name>.json` of a line with that `ticket` whose file name is the I4 name of
  that line's run, kind, id and ticket), and so do this ticket's own files that no line points at (orphans, e.g. a crash
  between the detail write and its line): a file in `detail/<run>/` whose stored `ticket` is this ticket and whose stored
  `(run, kind, id, ticket)` gives its own name. Lines of other tickets never veto it: by I4 their own files have other
  names, so a run shared with other tickets keeps their detail and a line planted elsewhere cannot block the deletion. A
  line of this ticket that points at a file whose name is not this ticket's own (planted or changed) is not followed:
  that file stays and is counted in `k` (never skipped silently). What is not safe is skipped at its own level, never a
  veto (anything with file access can plant a line and a file): a run that cannot be read (its run file, or its detail
  folder or lock a link, not a folder, unreadable) is skipped: its detail is not deleted, it is counted in `u`, and the
  CLI (stderr) and the page say so plainly ("N runs could not be read; their detail was not deleted"); a single file
  that is not safe (a link, FIFO or hardlink at its name, also one swapped in after it was found) stays, counted in `s`
  ("N detail files were changed outside orch; they were not deleted"), and the run's other files go. The files of one
  run are deleted under that run's lock; its detail folder goes only when `rmdir` finds it empty (a file written in
  between, or a skipped one, stays). `n` = the runs that lost detail in this call. Run files, lines and counts stay; the
  events then show "Details not available" (`--detail` answers `not_found`). Before anything is deleted the core appends
  one `orch.record-change/1` line (`$defs/record_change`: `{v, schema, at, change: "record.delete_detail", by: <the
  proven person>, ticket, deleted}`, no path, no content) to `alerts/<day>.jsonl`, so the deletion itself stays
  auditable; if that line cannot be written nothing is deleted (`not_available`). The line is not authenticated (an
  agent can append look-alike lines): it is a note, not evidence. Its `deleted` is what was going to go (the runs); the
  answer's `n` is what went (lower when a run was pruned or a file swapped in between). A failure in the middle (the
  run's lock busy, an I/O error) answers `not_available` ("Some details could not be deleted"), the rest goes with a
  new proof (and a new line).
- Refused (exit 2, `{"error", "code"}`), in this order, for `delete-detail`: an agent caller (agent tool in the
  environment, `--by agent:…`) before anything else, `needs_person`; a ticket that does not exist, `not_found` (accepted:
  the detail of a ticket deleted from disk goes with retention); no or an invalid proof (missing, expired, other
  target, other op, replayed, a `--by` other than the proof's), `needs_person`; the record or its `detail` folder itself
  unsafe (e.g. a symlink), `not_available` | `tampered`, with nothing deleted.

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
- Garbled or cut lines are counted and skipped. A replay of the same lines adds nothing: ids are the tool-call ids (passed raw; the writer
  hashes an unsafe one, so a hook line with the same raw id dedupes), else built from the line's own uuid or session id. Only a line
  with none of these (a `rate_limit_event` without uuid) gets `<run>:<seq>`; the wiring passes `seq_start` so a resumed process never
  reuses an id, and a replay with a different `seq_start` can duplicate such a usage line.

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
The same daily file also holds `orch.record-change/1` lines (a person's proven
change, e.g. Delete detail); readers tell the two apart by `schema`.

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
SHA-256 of `b"orch.id.hook/1\0" + hidden_id.encode("utf-8")`. For one hook/log
key the log line replaces the hook line and a later hook line is dropped; when
they disagree (`used`, `text`, `files`, or a non-provisional `ok`/`error`), both
lines remain and the log line has `conflict: true`. A provisional hook end
(`ok: null`) never disagrees on its outcome; a hook end with a fixed failure code
(`tool_failed`, `interrupted`) is compared on `ok` only (vectors `dedupe`).

Lock waits cover the 30-second stale window. A timed-out write is spooled in
`pending/<run>/` and drained in name-time order by the next append, under the
same run lock. The spool receipt has `pending: true` and `seq: null`; a default
id is omitted until the line is committed. A collector that numbers its own
`<run>:<n>` ids commits the spool first (under the lock) and then reads the run
file, so a turn written to the spool never shares an id with the next turn. `read_run` reports `status: ok`,
`reason: pending`, and `pending: n` while prepared writes remain. Readers show
this status alongside committed events.

POSIX uses `flock` on the lock fd for mutual exclusion, released by the kernel
on process death; Windows uses `msvcrt.locking` when available. Stale lock names
are removed only after acquiring the kernel lock and checking identity. Without
kernel locking, the holder refreshes mtime before slow steps and retention checks
lock identity again before deleting. Retention preflights `pending/<run>` under
the lock and skips runs with pending files without folding or deleting them.

Retention skips a run that is unavailable, tampered, or has pending lines: it folds and deletes
nothing for that run and keeps the alert; other runs proceed. Inside `detail/<run>/` only the
run's folder itself can make the run tampered: a single entry that is not safe (a planted link,
FIFO or hardlink) is alerted and stays, the rest of the run's detail and its lines go, so a
planted file never keeps a run's detail past retention. The result carries
the first non-ok status, reason, and message. Under each run lock, retention
reads again and checks the run still ended before folding or deleting.

Reading consumers display a tail line of type `unavailable` with cursor, run,
status, reason, and message, including `status: ok, reason: skipped` for invalid
lines. Query and counts include an `unavailable` list (empty when complete);
counts include `complete: false` when that list is nonempty. Errors use
`tampered`, `not_available`, or `not_found` (missing detail/run).

Windows re-lstat checks narrow but do not close the replacement race. Non-surrogate
OneDrive placeholders are allowed. Secrets shorter than the hider's minimum
are not hidden. File identity checks (above) do not authenticate content; the record MAC does
(next section). Tests compare the bundled schema with this contract to detect drift.

## Authenticated record (Gate G1 H1, issue #563)

Slice S1 defined the contract and the pure core (`workspace/src/orch/record_auth.py`, independent reference in
`validate.py`, vectors `record_auth` in `vectors/activity-v1.json`). Slice S2 adopts it in the writer
(`record.RecordWriter._commit`, the only place that seals a run line) and in the one read path
(`record._verified`, behind `read_run`, `run_lines` and every CLI view). Job streams, retention, alerts and
counts files follow in S3 and are not sealed yet.

**Invariant A1.** A record line counts (shown, deduped, counted, used for retention, run state or caps) only when it
carries this workspace's record MAC over its exact bytes, its run, its seq and its predecessor's MAC, AND it links into
the run's chain whose head is kept in the guarded home. Every other line is "changed outside orch": never shown as an
event, never counted, always reported as a loud marker with a count. One pure function decides it
(`record_auth.verify_run`). A verified `via: hook` line is still the agent's word (it proves only that orch's hook entry
wrote it); verified `log|core|broker|job` lines are orch-checked.

**Key.** `ikm = human.key` (32 bytes); `prk = HMAC-SHA256(salt "orch.record/1", ikm)`;
`rk = HMAC-SHA256(prk, "orch.record.mac/1\0" + ws + 0x01)`; `kid = sha256("orch.record.kid/1\0" + rk)` hex, first 8.
`ws` is the workspace local id. A derived subkey, never `human.key` itself, so no record MAC can pass as a
profile1/action1/verdict1/local1 MAC. It is never in argv, the environment, the workspace, a log, a spool file or an
error text.

**Sealed line.** The writer builds the event body (compact JSON in writer order, no `auth` key) and appends a fixed-length
suffix:
```
p    = MAC of the previous line of the chain; for seq 1: b64u(HMAC(rk, "orch.record.genesis/1\0" + ws + 0 + run))
msg  = "orch.record.line/1\0" + ws + 0 + run + 0 + str(seq) + 0 + p + 0 + body
m    = b64u(HMAC-SHA256(rk, msg))                                  # 43 characters
line = body[:-1] + ',"auth":{"k":"<kid>","p":"<p>","m":"<m>"}}' + "\n"       # the suffix is exactly 125 bytes
```
The canonical form is the exact bytes orch wrote: a reader cuts the last 125 bytes, appends `}` and has `body` back
byte-exact; no re-serialisation, so no float, Unicode or key-order ambiguity. Every event field is inside the MAC
(`via` and `kind` too, which is what stops a hook line from passing as `log`), plus workspace, run, seq and `p` out of
band. A body with an `auth` key, a duplicate key, another `run` or no integer `seq` is not verified. Compare MACs with a
constant-time compare. The 8192-byte line cap includes the suffix. `detail_hash` (32 lowercase hex = first 16 bytes of
sha256 of the detail file's exact bytes) is present iff `detail` is non-null and is inside the MAC, so a line
authenticates its detail file. Schema: `$defs/event_body` (what the writer validates and MACs), `$defs/sealed_event`
(the stored line); the root schema keeps `auth` and `detail_hash` optional so lines made before the MAC still validate.

**Chain and head.** Line `n` carries `p` = `m` of line `n-1`; seq comes from the chain, not from the physical line
number, so a planted junk line cannot shift later lines. The head (authority for rollback) is
`<guarded home>/keys/<ws>/record-heads/<run>.json`, 0600, written under the run lock after the line:
`{"schema": "orch.record-head/1", "run", "kid", "seq", "mac", "jobs": {"<job>": {"seq", "mac"}}, "rejected", "drained",
"drained_floor", "pruned", "hm"}` where `hm = b64u(HMAC(rk, "orch.record.head/1\0" + ws + 0 + canonical JSON of the head
without hm))` (sorted keys, compact). A crash between line and head leaves verified lines beyond the head; readers
accept them and the next commit moves the head. The head is bound to its run (`run` is inside `hm` and a reader requires
it to equal the run it reads, so one run's head copied over another's never verifies). A head with a wrong `hm`, `run`
or shape is treated as missing and alerted by the writer; a head of another `kid` (after a reset) is `old_key`: treated
as missing, no alert (`record_head_read` returns `(None, "old_key")`).

`verify_run` walks the lines. A line failing the suffix, key id, parse or MAC is `changed`. A genuine line must have
`seq == last_seq + 1` and `p == last_mac` (genesis for seq 1); a genuine line with `seq > last_seq + 1` resyncs there
with `removed += seq - last_seq - 1`; a genuine line with `seq <= last_seq`, or at the next seq with the wrong `p`
(replayed, duplicated, spliced from an older copy, moved behind its successor) is `changed` (a moved line that was
counted `removed` is un-counted). At the end `removed += max(0, head.seq - last_seq)` when the head's `kid` is ours.

| Case | What the reader sees |
|---|---|
| line edited in place | that line `changed`; the next genuine line resyncs: `removed: 1` |
| line inserted (any `via`) | `changed: 1`; every genuine line still shown |
| two lines swapped | one genuine line shown, the other `changed` (nothing `removed`) |
| middle line deleted | `removed: 1` |
| tail truncated, or run file deleted | `removed: head.seq - last_seq` |
| line of another run or workspace | `changed` (run and workspace are in the MAC) |
| older genuine copy restored | `removed` (the head is ahead) |
| no head, chain verifies from genesis | ok |

Result and reasons: `reason` is `content` when lines are shown and some line is changed, `removed` when only genuine
lines are gone, `unverified` when no line verifies and some have no `auth`, `old_key` when the only changed lines carry
another key id (see rotation). A line with another key id counts as `old_key` only while no line with the current key
id has verified yet (the old segment of a rotation always comes first and its MAC cannot be checked); after that it is a
planted line: `changed`, reason `content`. A run with verified lines plus problems stays readable; one with none is `tampered`.
Messages: content: "Some records of this run were changed outside orch. To be safe, orch does not show them. Nothing was
deleted."; removed: "Some records of this run were removed outside orch."; unverified: "orch cannot check these
records, so it does not show them."; old_key: "These records were made before orch's protection was reset. orch cannot
check them any more, so it does not show them."

**Key absent, rotation.** No `human.key`: the writer records nothing (`RecordOff`, fail closed, no degraded mode); readers
report `unverified`. A `reset_protection` rotation changes the `kid`: the next commit starts a new chain segment at
seq 1 with `p` = the genesis of the new key and rewrites the head (the old head has another key id: not an alert); the
old lines stay in the file before it and are `old_key`, never `removed`. Lines without `auth` are `changed`. No migration (pre-release).

**Spool and drain.** A spool entry `pending/<run>/<time_uuid>.json` carries `sm = b64u(HMAC(rk, "orch.record.spool/1\0" +
ws + 0 + run + 0 + name + 0 + canonical JSON of {event, payload, default_id}))`; the file name is bound. It is sealed
into the chain only when drained under the lock. An entry with a missing or wrong `sm`, a name already drained, or a
name older than `drained_floor` is never committed: it is deleted by exact path, counted in `head.rejected` and alerted.
The MACed object is exactly `{event, payload, default_id}`: an entry with any other key (`sm` aside) is refused.

**Job streams** (`jobs/<run>/<job>.jsonl`) use the same seal with domain `orch.record.job/1\0`, scope run + job, genesis
`orch.record.job.genesis/1` and the head entry `jobs.<job>`; `replace_last` re-seals the new last line with the same seq. A job line carries its `job` inside the MACed body (the
reader checks it equals the stream's job), as it carries `run`.

**Writer (S2).** Under the run lock, `_commit` takes the next `seq` and `p` from the LAST VERIFIED line of the
current key id in the file; only when the chain head (current key id, MAC ok) is ahead of it (the file was cut
short) does it continue at `head.seq + 1` with `p = head.mac`; with no verified line of the current key and no such
head it starts at seq 1 with the genesis. A head of another key id, a damaged head or a deleted head never restarts
a chain in the middle of a run. The line is sealed, written with one `write()`, then the head is written (a head
write that fails is alerted, not raised). No key, no recording (`RecordOff`, nothing written, not even a spool
entry). The key is made when a run is claimed (`humanproof.ensure_record_key`), never by a writer.

**Foreign key ids (LOW-A).** Lines with a key id other than the current one are held pending while no line of the
current key has verified. At the end they are `old_key` only when the rotation shape holds: the first verified line
of the current key is seq 1, or no line verifies and no head of the current key with `seq >= 1` exists. Otherwise
(the first verified line has `seq != 1`, a gap; or no line verifies but a current-key head says there were lines)
they are `changed`, reason `content`. After a verified line they are always `changed`.

**Legacy runs.** A run file made before orch sealed lines is a legacy run, decided in ONE place (the read status,
`ReadResult.legacy`): the guarded home, the workspace id and the key folder resolve cleanly, the head file is truly
absent, and no line of the file carries `auth`. Its lines are read as before (schema check, `seq` = line number),
shown, each marked `checked: false`, with the read reason `unchecked` and the text "These records were made before
orch checked them." (`record.UNCHECKED_TEXT`); they are never counted as orch-checked (counts exclude the run and
say `complete: false`), never used for permissions, retention or shared counts. Any other state is never legacy:
a run with a head or a sealed line is verified as a whole and its unsigned lines (stripped, prepended, appended) are
`changed`, reason `content`, and not shown; an unknown state of the guarded home (a missing or forged local id, a
key folder that is missing, linked, loose or unreadable) is `tampered`, reason `unverified`, for every run. A legacy
run that gets a new line becomes a sealed run: its old lines are then `changed` (no migration). Vectors
`record_auth.legacy`.

**Readers (S2).** `orch record tail` shows the events of the verified view with a computed `checked` (false for
`via: hook` and for every line of a legacy run, true otherwise; never stored), the cursor is the verified seq, and
one marker per change of `(reason, changed, removed)`. `query` and `counts` use the same view; any run with changed,
removed or unchecked lines makes `counts` `complete: false`. `run_model` has `complete` and `protected`: `protected`
is false for a run by a tool orch cannot give deny rules (codex, generic: the adapter's `deny.format` is `none`) and
whenever the tool is not known from an orch-written verified line (the core's `run.state`, never a hook line); those
runs show "Records from this helper can't be fully checked." (`record.UNPROTECTED_TEXT`). `--detail` takes the
`detail_hash` from the verified line that points at the file (never from the caller): a file with other bytes, or a
sealed line that has a detail pointer but no `detail_hash`, is refused as `swapped` ("Details changed outside orch.");
only a legacy run reads a detail with no hash.

### Known limit (Level 1)

The MAC turns "append a line" into "run code that loads orch's key". It does not stop:

- **Code run as the same user.** An agent that executes code importing orch, or that reads `human.key` by a path form
  the text-based deny rules miss (secrets.md), or that runs under an adapter whose deny format is `none` (codex,
  generic), can seal anything. Records from such helpers show a plain marker ("Records from this helper can't be fully
  checked.").
- **Level 2** is the key held by a separate process or OS user that seals on request. Not built.
- **Head deleted.** The head lives in the guarded home; deleting it (or leaving one of another key id) means "no
  head": a tail truncation of the run file is then not detected (the chain still verifies from genesis).
- Input injection into the collector (on Linux an agent can write into the harness's stdout pipe); such lines arrive
  through orch's real collector and are sealed as `log`.
- Alerts and counts files get their own per-file MAC in a later slice; `meta.json` stays unauthenticated (display only).
