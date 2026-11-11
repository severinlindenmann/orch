# Jobs: `orch.job/1`

Long work in any tool (an export, a training run, a scraper, a deploy) reports what it does with `orch job …`, by writing
lines to `$ORCH_EVENTS`, or by running through the generic wrapper `orch job run -- <command>`. Focus shows jobs in the tree,
the ticket's Work tab keeps them with their results.

Schema: `job-event.schema.json` (stored line; `$defs/input` = what a program may write). Examples: `examples/job-event/`
(each file is one job's stream), `examples/job-input/`. Vectors: `vectors/jobs-v1.json` (state changes, binding, caps, lost,
progress patterns). T0: `… contracts/validate.py jobs`.

## Reported, never checked

Everything a job says is **reported by the job**. Surfaces label it so ("reported by the job"); it is never shown as a passed
check, it cannot approve anything, answer a question, change a ticket's status or create a Needs-you card. An `end` with
`status: ok` only means the program said so. Proof for a ticket stays `orch check done` (the agent) and the person's verdict.

## Ids and binding

- `job` = `j_` + 6–32 lowercase letters/digits, made by orch at `start` (random), unique in the workspace.
- A job belongs to exactly one run and its ticket: inside an agent run (`ORCH_RUN` set) the run; otherwise orch makes a run
  for the job itself (`harness: none` in the record) on the ticket given with `--ticket` (required then). The binding is
  fixed at `start` and stored in `.orch/run/jobs/<job>.json` (`{job, run, ticket, pid, events_path, started_at}`, 0600).
- Every later event must name the same job and, when it names a run, the same run; otherwise it is refused (`other_run`).
- `seq` is set by orch (+1 per stored line of that job). Producers never send `seq`, `ticket` or `by`.

## States

```
(none) --start--> running --step|progress|artifact|metric|table|link|log--> running
running --end(status)--> ok | failed | cancelled          (final)
running --(orch only)--> lost                              (final)
```

- Anything before `start` → refused `not_started`; a second `start` → `already_started`; anything after a final state →
  refused `ended` (not stored; counted in the job's `dropped`).
- Steps: `waiting → running → done | failed | skipped`; `waiting → done|failed|skipped` is fine; a finished step cannot go
  back (`step_finished`). A new step id may appear at any time while running.
- `progress`: `done` ≤ `total` when `total` is set (else refused `invalid`); a later `done` may go down (a retry).
- **lost** (written by orch, `by: orch`): while running, when no event came for `quiet_minutes` (default 10, from `start`, at
  most 240), when the reporting process is gone (pid with its recorded start time, `orch job run` only), or when the run
  ended. Checked on every event of the run and by the run's watcher once a minute. A late event after `lost` is refused `ended`.

## Caps

| What | Cap | Beyond the cap |
|---|---|---|
| Events per job | 2000 | refused `cap`; one stored `log` line "More events were left out." (`capped: true`, set by orch) the first time; one `end` is still accepted so a job can finish |
| Jobs per run | 200 | `start` refused `cap` |
| One input line | 8 KB | refused `too_large` |
| Stored stream per job | 5 MB | as events per job |
| `log` text | 500 characters | cut, not refused |
| `progress` stored | 1 per second per job | later ones in the same second replace it (only the last is kept) |

Refusals never stop the program: `orch job …` exits 2 with plain words (`Refused: this job has already ended.`), lines from
`$ORCH_EVENTS` are dropped and counted.

## Commands (`orch job …`, all `--json`)

The job id comes from `--job <id>` or `ORCH_JOB`. Output: the stored event (`--json`), or nothing.

| Command | Event |
|---|---|
| `orch job start --title "<t>" [--ticket T] [--quiet-minutes N]` | `start`; prints `{"job": "j_…"}` |
| `orch job step <name> --label "<l>" [--state running]` | `step` |
| `orch job progress --done N [--total M] [--unit files] [--text "<t>"]` | `progress` |
| `orch job artifact <path> [--label "<l>"]` | `artifact` (path inside the workspace, file must exist) |
| `orch job metric <name> <number> [--unit ms]` | `metric` |
| `orch job table --table '<blocks table>'` | `table` (blocks.schema.json `$defs/table`; `--json` is the global output flag, so the table has its own flag, `-` reads stdin) |
| `orch job link <https url> --label "<l>"` | `link` |
| `orch job log "<text>" [--err]` | `log` |
| `orch job end --status ok\|failed\|cancelled [--summary "<s>"]` | `end` |
| `orch job done\|fail [--summary "<s>"] [--exit N]` | `end` with `status: ok` / `failed` (shorthand) |
| `orch job result --table '<blocks table>'` | the same as `table` (a job's result is a blocks table) |
| `orch job list [--run R] [--ticket T]`, `orch job show <job>` | read back (below) |
| `orch job run [--title "<t>"] [--ticket T] -- <command…>` | generic wrapper (below) |

Writing needs a live run: `ORCH_RUN` + `ORCH_TICKET` must name a live claim and the caller must sit inside that claim's
process tree (the proof of `orch record hook`), else refused `not_active` (nothing stored); without a run `no_run`; without a
registered value hider `hider_off`. Every string of an entry (and every table key) passes the value hider before anything is
stored; an entry that is invalid after hiding is refused (`invalid`, plain words), never stored raw. A field the schema does not
name for that `type` is `invalid`; `by`, `seq`, `ticket`, `pid`, `command` and type `lost` from a program are `not_allowed`.
A job whose id belongs to another run is `other_run`.
**One writer per job:** `start` makes a random 128-bit write token and returns it once (`{"job": "j_…", "token": "…"}`); only
its sha256 is stored (`token_hash` in the `start` line). Every later write must present it (`ORCH_JOB_TOKEN` or `--token`),
compared in constant time; a missing or wrong token is refused `token` and the token is never echoed or recorded, so another
process of the same run cannot write into a sibling job by guessing its id. Reads need no token. A job started inside an agent run is bound by its first stored line
(`.orch/record/jobs/<run>/<job>.jsonl` names run and job; ticket and run are stored in every line), so no separate binding
file is needed until `orch job run` (which needs `pid`, `events_path`) is built.

Reads: `orch job list --json` -> `{"status":"ok","jobs":[{job, run, ticket, title, state, events, started_at, last_at,
progress, reported_by:"job"}]}`; a stream that cannot be read is an explicit row (`status: tampered|unavailable`, `reason`,
`message`), never left out. `orch job show <job> --json` -> `{"status":"ok","job":{…},"events":[…]}` or a refusal with code
`tampered` / `not_available` / `not_found`. Streams changed outside orch (a line that is not this job's, out of order, a
link) are `tampered`.

## `$ORCH_EVENTS` and `orch job run`

`orch job run -- <command>` writes `start` (title = `--title` or the command's base name, `command`, `pid`), runs the
command (no shell), and sets for it `ORCH_JOB=<job>` and `ORCH_EVENTS=<path>` (`.orch/run/jobs/<job>.events`, a new 0600
file). The program may append `$defs/input` lines (one JSON object per line) there; orch reads them as they come, fills
`v`, `job`, `run`, `ticket`, `seq`, `at`, checks them and stores them. stdout and stderr of the program pass through the
value hider and are shown as usual; the last 200 lines also become `log` events. **Progress pattern**: a line whose whole
text matches `^\s*(\d+)\s*/\s*(\d+)\b` (12/40) or `^\s*(\d{1,3}(?:\.\d+)?)\s*%` (45%) becomes a `progress` event (vectors
`progress_pattern`). When the command exits, orch writes `end` (`ok` for exit 0, `cancelled` for a signal it sent, else
`failed`, `exit` = the code) unless the program already sent one. Ctrl-C / `orch run stop` → the program gets SIGTERM, then
SIGKILL after 10 s, and `end cancelled`. orch signals only the process it started itself, through the handle `orch job run`
keeps (pid + start time); `pid` and `command` in `$ORCH_EVENTS` input are refused.

A program started any other way may still write to `$ORCH_EVENTS` when it inherits it; without it, it calls `orch job …`
with `ORCH_JOB`.

## In the record and on screens

- Stored stream: `.orch/record/jobs/<run>/<job>.jsonl` (activity.md, retention as the run). One `job` activity event per
  `start`, `step`, `artifact`, `metric`, `table`, `link`, `end`, `lost`, and at most one `progress` per 5 s.
- The job view (Focus, Work tab, phone) is one blocks document `from: job` built the same way everywhere: `summary` from the
  `end` summary (or "Running" / "Lost: no news for 10 minutes"), `steps` from the steps, `progress` from the last progress,
  one `stat` per metric name (last value), each `table`, one `file` per artifact, one `link` per link, `log` with the last 50
  log lines. A failed job shows only its red row in the list (owner decision J4).
