# Pull requests add-on contract (`orch pull-requests`)

A merge queue for GitHub pull requests (ORCH-168, first part of the GitHub plan ORCH-146). Helpers put a ready pull
request in line instead of waiting for its checks alone; the runner merges several together after one run of the
checks. No AI call. Off until `orch addon add pull-requests`. Needs `gh` signed in and git 2.38 or newer.

## Manifest (`workspace-addons/pull-requests/src/orch_pull_requests/orch-addon.toml`)
`name = "pull-requests"` (the core owns `orch github`), not recommended, no `background` service (the runner starts
on `queue add` and ends when the queue is empty), no dashboard page yet, `gitignore = [".orch/addons/pull-requests/"]`.

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
