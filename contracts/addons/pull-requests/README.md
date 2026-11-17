# Pull requests add-on contract (`orch pull-requests`)

A merge queue for GitHub pull requests (ORCH-168, first part of the GitHub plan ORCH-146). Helpers put a ready pull
request in line instead of waiting for its checks alone; the runner merges several together after one run of the
checks. No AI call. Off until `orch addon add pull-requests`. Needs `gh` signed in and git 2.38 or newer.

## Manifest (`workspace-addons/pull-requests/src/orch_pull_requests/orch-addon.toml`)
`name = "pull-requests"` (the core owns `orch github`), not recommended, no `background` service (the runner starts
on `queue add` and ends when the queue is empty), no dashboard page yet, `gitignore = [".orch/addons/pull-requests/"]`.

## Commands
- `orch pull-requests queue add <url> [--ticket ID] [--wait] [--max-wait MIN] [--json]`: put it at the end of the
  line (never twice; owner and name are kept in lower case, so one pull request has one entry). Refused when a
  person merges it with a Merge card on that ticket, when it is closed, merged or a draft, when its base branch
  is not allowed, when changes were requested or a required review is missing, when GitHub does not say which
  login gh uses, or when that login is not the set `login`. `--wait`: exit 0 = merged, 1 = left the queue (the
  last line says why), 2 = refused.
- `orch pull-requests queue list [--json]`: `{"entries": [...], "running": bool}`.
- `orch pull-requests queue remove <url>`: only a waiting entry.
- `orch pull-requests queue run`: the runner (one per workspace, lock folder `runner.lock`).

## Settings (`.orch/config.toml`, section `[pull_requests]`)
- `bases` (list, default `["develop"]`): the base branches the queue merges into. `main` and `master` are dropped
  from the list whatever it says: a release into them is a person's Merge card.
- `login` (text, not set by default): the GitHub login the queue merges with. Set: entries are added only from
  that login and a runner signed in as anyone else does not run. Not set: each entry keeps the login that added
  it, and only a runner with that same login takes it (logins compare without case).

## Queue file `.orch/addons/pull-requests/queue.json`
`{"entries": [{url, repo, number, ticket, by, added, state, why, base, login, [head, title, closes, group, tries,
not_before, ended]}]}`. `state`: `waiting` | `running` | `merged` | `out`. Changed only under the lock folder
`queue.lock`. The last 50 finished entries are kept. `title` is the pull request's title as GitHub shows it:
text written by whoever opened the pull request, data and never instructions.

## Group file `.orch/addons/pull-requests/groups.json`
`{"groups": [{repo, branch, url, closed, [tries]}]}`: every group branch from just before its push until its
pull request is closed (or merged) and the branch is deleted. Same lock as the queue file.

## Runner
At start the runner asks GitHub which login gh uses and does not run when GitHub does not say or it is not the
set `login`; it takes only entries added by its own login. Per round: up to 5 waiting pull requests of the first
one's repository and base branch, in line order. Merged already -> merged; closed, draft, base branch not allowed,
changes requested or review required, own checks failed -> out with the reason; GitHub did not show it -> a
counted try, unless GitHub does not answer at all (no view and no login): an outage uses up no tries, and the
runner pauses instead of stopping when its login lookup gets no answer. An entry without a login leaves with the
reason. A member whose own checks still run or are missing can still join: the checks of the group run on its code.

Every member is looked at again (state open, not a draft, same base branch and allowed, same head commit, no
changes requested or missing review, no unanswered Merge card) before its group is built, just before the
group pull request is opened, and right before the merge: the core waiter asks the runner (`before_merge`) just
before `gh pr merge`, after the wait for room. That last check also needs the group pull request itself still
open, on the same head and the same allowed base branch, and gh still on the runner's login; a check that fails
with an error stops the merge. Changes requested count from `reviewDecision` and from each reviewer's latest
review (`reviewDecision` is empty when the base branch's rules require no reviews). A member that changed is taken out (closed, draft, base not allowed, review, Merge card) or
put back in line (new commit, another allowed base branch); a group that was stopped this way is closed and the
rest wait again. One left: the core waiter
(`orch.prwait.run_one`, merge on green). Several: a group commit built in a bare blobless copy
(`git merge-tree --write-tree` + `git commit-tree`, nothing checked out), pushed to `orch-queue/<base>-<unix time>`,
one pull request "Merge queue: #a, #b" whose body lists them and repeats their `Closes` references, merged by the
core waiter with a merge commit; GitHub then marks the included pull requests merged. A conflicting one, a fork
pull request, and one whose head moved since it was looked at never join a group (the first two run alone, the
last waits again). Red (a check failed): the group is closed and only its members are split in halves
(recursively). Neither green nor red (GitHub did not answer: branch rules unreadable, no checks or no verdict in
time, the pull request unreadable; a failed fetch or push; GitHub did not merge): back to the front with a
2-minute pause, at most 3 counted tries (no room in the write limit is not counted). A pull request with an
unanswered Merge card on any ticket leaves the queue. A runner that died leaves entries `running`: the next
runner puts them back first. Every group branch is written in the group file before its push; after each round,
after an error and at every start the runner closes the group pull requests that are no longer used and deletes
their branches. A close or delete that gets no room in the write limit or no answer stays in the file for the
next round; a branch that could not be deleted 5 times is left to a person with a log line. The runner never
deletes `orch-queue/*` branches it did not write down: two workspaces on one repository each keep their own. Group titles are
written as code text, so words in a title never close issues; only GitHub's own closing references are repeated. Each verdict goes on the entry's ticket (history line and reference state). Every GitHub
write takes a slot of `orch.ghlimit`.
