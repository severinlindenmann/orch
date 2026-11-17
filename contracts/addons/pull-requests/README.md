# Pull requests add-on contract (`orch pull-requests`)

A merge queue for GitHub pull requests (ORCH-168, first part of the GitHub plan ORCH-146). Helpers put a ready pull
request in line instead of waiting for its checks alone; the runner merges several together after one run of the
checks. No AI call. Off until `orch addon add pull-requests`. Needs `gh` signed in and git 2.38 or newer.

## Manifest (`workspace-addons/pull-requests/src/orch_pull_requests/orch-addon.toml`)
`name = "pull-requests"` (the core owns `orch github`), not recommended, `background = true` (the Merge when green
watcher; the queue runner itself starts on `queue add` and ends when the queue is empty), no dashboard page yet,
`gitignore = [".orch/addons/pull-requests/"]`, `ticket_ext` and `[ticket_fields]` (section "Pull requests") =
`ext.schema.json` (this folder; the package ships a byte-identical copy). Not `ticket_ext_inert`: the switch starts
merges, so sync holds a changed block until a person allows it.

## Commands
- `orch pull-requests queue add <url> [--ticket ID] [--wait] [--max-wait MIN] [--json]`: put it at the end of the
  line (never twice). Refused when a person merges it with a Merge card on that ticket. `--wait`: exit 0 = merged,
  1 = left the queue (the last line says why), 2 = refused.
- `orch pull-requests queue list [--json]`: `{"entries": [...], "running": bool}`.
- `orch pull-requests queue remove <url>`: only a waiting entry.
- `orch pull-requests queue run`: the runner (one per workspace, lock folder `runner.lock`).

## Queue file `.orch/addons/pull-requests/queue.json`
`{"entries": [{url, repo, number, ticket, by, added, state, why, [base, title, closes, group, tries, ended]}]}`.
`state`: `waiting` | `running` | `merged` | `out`. Changed only under the lock folder `queue.lock`. The last 50
finished entries are kept.

## Runner
Per round: up to 5 waiting pull requests of the first one's repository and base branch, in line order. Merged
already -> merged; closed, draft, own checks failed, unreadable -> out with the reason. One left: the core waiter
(`orch.prwait.run_one`, merge on green). Several: a group commit built in a bare blobless copy
(`git merge-tree --write-tree` + `git commit-tree`, nothing checked out), pushed to `orch-queue/<base>-<unix time>`,
one pull request "Merge queue: #a, #b" whose body lists them and repeats their `Closes` references, merged by the
core waiter with a merge commit; GitHub then marks the included pull requests merged. A conflicting one, a fork
pull request, and one whose head moved since it was looked at never join a group (the first two run alone, the
last waits again). Red: the group is closed and only its members are split in halves (recursively). Neither green
nor red: back to the front with a 2-minute pause, at most 3 counted tries (no room in the write limit is not
counted). A pull request with an unanswered Merge card on any ticket leaves the queue. A runner that died leaves
entries `running`: the next runner closes their group pull request and puts them back first. Group titles are
written as code text, so words in a title never close issues; only GitHub's own closing references are repeated. Each verdict goes on the entry's ticket (history line and reference state). Every GitHub
write takes a slot of `orch.ghlimit`.

## Merge when green (ORCH-166)
`ext.pull-requests.merge_when_green`: `"on"` | `"off"` (absent = off), a choice field "Merge when green" (Off, On)
under the ticket's Details; set with `orch ticket set <ticket> pull-requests.merge_when_green on`.

- `orch pull-requests tend [--json]`: one pass, no AI call. For every ticket with the switch on, each open pull
  request reference (not recorded merged or closed) that GitHub shows open and not a draft, and that no unanswered
  Merge card on any ticket names, is added to the queue (`by = "agent:merge-when-green"`, `ticket` = that ticket);
  the runner is started when something was added. Tickets unreadable: nothing is queued (refused). Switch off: a
  `waiting` entry this switch added for that ticket is taken out; a `running` one finishes its round.
  Prints `{"added": [url], "removed": [url], "skipped": [[url, why]]}`.
- Not every minute again: `switch.json` remembers per pull request the commit put in line (`head`, `tries`, `at`).
  A new commit goes in at once; the same commit again only 10 minutes after the last time, while none of its checks
  failed, at most 3 times. A draft forgets it (marked ready = in line at once); switching off forgets it.
- The merge is the runner's (above): `orch.prwait.run_one(url, merge=True)` for one, the group for several; only the
  checked commit (`--match-head-commit`), every write through `orch.ghlimit`, draft and Merge card checked again.
- `orch pull-requests start|stop|status --json` (called by `orch start|stop|status`): one watcher per workspace
  (lock folder `watch.lock`, owner = pid and start time), `tend` every 60 seconds, log `watch.log`. It ends by itself
  when the add-on is no longer on here. `start` → `{"running": true, "pid"}`, `stop` → `{"stopped": bool}` (signals
  only the pid the lock names while that process lives with the recorded start time), `status` → `{"running",
  "pid"?}`, exit 1 when not running.
