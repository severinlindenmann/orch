# The debug log: `orch.diag/1`

orch writes down, always and locally, what happened inside it: which command ran, which ticket change was applied
or refused and by which guard, which background step failed. It is the evidence a person or an agent reads when
something is stuck or wrong (`orch diag query` and the report, later steps). It holds **structure only**: names,
numbers, ids and places in the code. Never ticket text, never a conversation, never the value of a key.

Schema: `diag.schema.json` (one event). Examples: `examples/diag/`. Vectors: `vectors/diag-v1.json` (whole events and the
event-name rule). T0: `uv run --with jsonschema --with rfc3339-validator --with cryptography python contracts/validate.py diag`.
Writer: `workspace/src/orch/diag.py`, the only one. The core names no add-on or agent tool here.

## Where

```
.orch/diag/<YYYY-MM-DD>.<src>.<part>.jsonl     one event per line; src = who wrote it (cli, run, ...); part = 1, 2, ... when a
                                               file reaches 8 MB. LOCAL, listed in .orch/.gitignore ("diag/"). Never committed.
```

Folder 0700, files 0600 (POSIX). The log never follows a symlink: `.orch`, `.orch/diag` or a file being a link makes the
writer refuse (the line is counted as dropped). Files are opened `O_NOFOLLOW|O_APPEND`; one line is at most 4 KB, one `write()`.
Other files in the folder are never touched, not even by retention.

## The event

One JSON object per line, every field present (`null` when it has no value):

| field | meaning |
|---|---|
| `v` | `1` |
| `at` | UTC time, milliseconds (`2026-11-14T22:50:01.123Z`) |
| `mono_ms` | monotonic clock of the process: orders events of one process when the wall clock jumps |
| `seq` | per process, +1 per event. A gap means lost lines; a `diag.dropped` event says how many |
| `src` | which program wrote it (`cli`, `run`, `host`, ...) |
| `ver` | orch version |
| `lvl` | `debug` `info` `warn` `error` |
| `ev` | event name `area.thing_happened` (catalog below) |
| `trace` | `{trace_id, span_id, parent_span_id}`, W3C trace-context ids (below) |
| `ws` `ticket` `run` `job` | what the event belongs to (workspace id; the others from the call or `ORCH_TICKET` / `ORCH_RUN` / `ORCH_JOB`) |
| `code` | `module:function:line` of the call |
| `pid` `proc_start` | process id and its start (epoch ms): together they name one process, even when a pid is reused |
| `dur_ms` | duration of a span event, else `null` |
| `kv` | the details (content tiers below) |
| `err` | `null`, or `{type, fingerprint, frames}`: the exception class, a 16-hex fingerprint of the type and the code places (no line numbers), and up to 12 frames `module:function:line` |

An error event never carries the exception's message and never captures frame locals (a traceback with locals would hold
the key values the hider guards).

## Content tiers (this log is tier 0: structure only)

1. `kv` has at most 24 keys; a key is `[a-z][a-z0-9_]{0,39}`. A value is a scalar (string, number, boolean, `null`) or a list of at
   most 20 scalars. Objects, bytes and anything else are left out.
2. A string passes the workspace's key hider (`orch.hider`) **whole**, then is cut at 300 characters (a cut first could split a
   key value so the hider no longer finds it): every stored key value, in all its encodings, becomes `[hidden: <name>]`. Without a hider that can be built the line is not written (counted as `hider_off`).
3. A key whose name says it is secret (`secret token passw passphrase key auth cookie credential bearer signature proof`) holds
   `"[hidden]"` instead of any string or list.
4. Ticket titles, descriptions, comments, helper conversations and file contents never go in `kv`. Content is a later,
   opt-in part of a *report*, never of this log.

## Budgets and drops

- Retention: 7 days (by the date in the file name) and 200 MB per workspace; over the size, the oldest files go first. Checked
  at the first write of a process and at most once a minute after.
- Per source: at most 1200 events per minute per process and 60 MB per day; above that events are dropped.
- A dropped event is counted, never an error for the caller. The next line that can be written is first a
  `diag.dropped` event (`lvl` `warn`, `kv` = `count` and `n_<reason>`: `source_events source_bytes hider_off write no_folder invalid error`).

## Trace (W3C `traceparent`)

`00-<32 hex trace id>-<16 hex span id>-01`. One trace per CLI invocation and per dashboard HTTP request: an incoming
`traceparent` header (HTTP) or `TRACEPARENT` environment variable is joined when valid (all-zero ids are not), its span becomes
`parent_span_id`; otherwise a new trace starts. A child process gets `TRACEPARENT` in its environment (agent runs and
`orch run _wrap`), so its events share the trace id. `diag.span()` makes a child span and writes one event with `dur_ms`.

## Setting

`diag.enabled`, default **on**, per workspace on this computer: `orch config get|set diag.enabled on|off` and the settings answer
of the dashboard (`diag_enabled`). Off = no new lines; existing files stay until retention removes them.

## Event names (`^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$`)

| `ev` | `kv` |
|---|---|
| `cli.command` | span of one command: `command`, `sub` (a plain second word) |
| `dashboard.request` | `method`, `path` (no query string) |
| `ticket.op_applied` | `actor`, `op`, `status_from`, `status_to`, `revision_from`, `revision_to`, `written` |
| `ticket.op_refused` | `actor`, `op`, `guard` (`closed_ticket`, `conflict`, or the refusal's class), `status`, `expected_revision`, `actual_revision` |
| `relay.send_failed` | `what`, `reason` (the exception class), `why` (its message, cut at 300, key values hidden) |
| `run.live_submit` | `what` (a live run's input hand-over step; `ticket` and `run` are the event fields) |
| `copies.clean` | `line` (one step of the clean-up of separate copies) |
| `diag.report_pruned` | `ref`, `why` (a report or incident folder removed for the budget) |
| `diag.incident` | `reason`, `ref` (an incident was frozen; `ticket`, `run` are the event fields) |
| `diag.disabled` | `actor` (written just before a person switches the log off; an agent cannot) |
| `diag.dropped` | `count`, `n_<reason>` |
| `diag.report_failed` | (error event; `err` has the class) the dashboard could not make a report |
| `diag.report_made` | `ref`, `scope` (`ticket`, `add-on` or `workspace`), `content`, `page` (a page snapshot was added); written when the dashboard makes a report |
| `diag.delete_requested` | `actor`, `what` (`reports` or `notes`; written before a person's verified delete) |
| `diag.reports_deleted` | `count` (Settings > Delete all) |
| `diag.notes_deleted` | `files` (Settings > Delete notes; the first line of the new log) |
| `ui.error` | `kind` (`error` or `rejection`), `what` (the error class or name, cut), `file`, `line`, `col` (script file name, no query) |
| `ui.console_error` | `what` (first argument's type, never its text), `n` (arguments) |
| `ui.fetch` | `route` (path without query, ids folded to `:id`), `method`, `status`, `ms`, `outcome` (`ok`, `error`, `cancelled`, `failed`) |
| `ui.action` | `id` (the button's `data-action`), `route` |
| `ui.route` | `from`, `to` (the page hash with ids folded to `:id`) |
| `ui.state` | `client_rev`, `server_rev` (revision hashes, 12 chars), `cache_age_ms` (`X-State-Age-Ms` of the last state read) |
| `ui.env` | `w`, `h`, `zoom`, `browser`, `assets` (the dashboard version the page loaded), `touch`; once per page load |

The page (the dashboard window and the same-origin add-on frames in it) sends `ui.*` events in batches to `POST /api/diag`
(`src` `ui`, same budgets). Only the names above are accepted; never a request body, response body, header, cookie, text
the person typed or a console message. Dashboard routes carry the request's `traceparent` header (the answer repeats it),
so a click, its request and the helper's work share one trace id.

New events add a row here and keep their `kv` keys stable; readers skip names they do not know.

The log is not product output. What stays as it is: a run's output log (`.orch/run/logs/<ticket>-<run>.log`) and the
security logs (dev-proof, protection reset). The opt-in `ORCH_TRACE_FALLBACKS` temp file stays too: a developer guard that has no workspace, and the debug log
resolves the orch home itself (it must not be called from inside that resolution).


## Reading it: `orch diag inspect | query | report` (read-only)

Nothing in `orch diag` changes a ticket, run, claim, lock or the record, and nothing repairs: no collector calls
`runs.settle_orphan` or any helper that fixes things as a side effect (a test hashes `.orch/` before and after).
`report` writes only into `.orch/diag/reports/`. Nothing uploads anything.

- `inspect [--ticket T] [--run R] [--json]`: collectors (tickets, runs, services, queues, locks, env, disk, diag; 5 s and
  256 KB each, `{collected_at, revision?, data, gaps[]}`) plus the checks, now. Structure only.
- `query [--ticket T] [--run R] [--ev 'ticket.*'] [--lvl warn] [--around HH:MM --window 2m] [--since 2h] [--limit N]
  [--page TOKEN]`: the debug log plus the activity record (ids, kind and time only), oldest first, at most 500 per page;
  `next` is the token for the following page. A record that could not be read fully says so in `unavailable`.
- Checks (`orch/diag_checks/<name>.py`, `{name, verdict: problem|ok|cannot_check, fact, evidence[]}`):
  `run_gone_ticket_working`, `dead_lock_holder` (pid AND process start time), `no_heartbeat` ("progress unknown", never
  "hung"), `waiting_for_permission`, `ticket_op_refused` (3 times), `hook_lines_missing`, `relay_unreachable`,
  `clock_skew`, `disk_low`, `diag_dropped`.
- `report [--ticket T] [--addon A] [--since 2h] [--note ...] [--expected ...] [--content|--no-content]` writes
  `reports/r-<MMDD-HHMM>-<scope>/`: `SUMMARY.md` (< 20 KB, read first: note, window, checks, top errors, last 50 lines,
  gaps), `manifest.json` (`orch.diag-report/1`), `checks.json`, `timeline.jsonl` (sources merged by time, each source in
  its own seq order), `errors.json` (by fingerprint), `state/*.json`, `logs/<src>.jsonl` (cut to the window),
  `record/<run>.jsonl` (normalized events), `content/` only with content on (default on: that ticket's text and
  helper excerpts). The window starts at the scoped run's start, else the ticket's last successful change.
  Every file passes the key hider; without a hider no report is made.
- Incidents (`reports/i-...`): the same layout, structure only, 15-minute window, frozen BEFORE a recovery runs (in front of
  `settle_orphan` and the start-failure path), on a crash of a command, on a check turning `problem`, and when the same
  delivery failure happens 3 times. One per fingerprint per 15 minutes, at most 20 and 50 MB. Reports and incidents count
  against the 200 MB budget; the oldest go first (`diag.report_pruned`).
