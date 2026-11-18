# Pull requests add-on contract (`orch pull-requests`)

A merge queue for GitHub pull requests (ORCH-168, first part of the GitHub plan ORCH-146). Helpers put a ready pull
request in line instead of waiting for its checks alone; the runner merges several together after one run of the
checks. No AI call. Off until `orch addon add pull-requests`. Needs `gh` signed in and git 2.38 or newer.

## Manifest (`workspace-addons/pull-requests/src/orch_pull_requests/orch-addon.toml`)
`name = "pull-requests"` (the core owns `orch github`), not recommended, `background = true` (the Merge when green
watcher and the pull request reader; the queue runner itself starts on `queue add` and ends when the queue is
empty), `[dashboard]` "Pull requests" (`orch pull-requests view`), `[[ticket_links]]` `github-pr`, `[acts.refresh]`,
`gitignore = [".orch/addons/pull-requests/"]`, `ticket_ext` and `[ticket_fields]` (section "Pull requests") =
`ext.schema.json` (this folder; the package ships a byte-identical copy). Not `ticket_ext_inert`: the switch starts
merges, so sync holds a changed block until a person allows it.

## Commands
- `orch pull-requests queue add <url> [--ticket ID] [--first] [--wait] [--max-wait MIN] [--json]`: put it at the end of the
  line (`--first`: it fixes the red base branch, so it goes ahead of every waiting entry not marked first, see Red base branch) (never twice; owner and name are kept in lower case, so one pull request has one entry). Refused when a
  person merges it with a Merge card on that ticket, when it is closed, merged or a draft, when its base branch
  is not allowed, when changes were requested or a required review is missing, when GitHub does not say which
  login gh uses, or when that login is not the set `login`. `--wait`: exit 0 = merged, 1 = left the queue (the
  last line says why), 2 = refused.
- `orch pull-requests queue list [--json]`: `{"entries": [...], "running": bool}`.
- `orch pull-requests queue remove <url>`: only a waiting entry.
- `orch pull-requests queue run`: the runner (one per workspace, lock folder `runner.lock`).
- `orch pull-requests failed-checks on|off|status|tend [--json]`: the failed-checks part (below). `on`/`off` write
  the setting `act_on_failed_checks`; `tend` runs one pass now (nothing when off).

## Settings (`.orch/config.toml`, section `[pull_requests]`)
- `bases` (list, default `["develop"]`): the base branches the queue merges into. `main` and `master` are dropped
  from the list whatever it says: a release into them is a person's Merge card.
- `login` (text, not set by default): the GitHub login the queue merges with. Set: entries are added only from
  that login and a runner signed in as anyone else does not run. Not set: each entry keeps the login that added
  it, and only a runner with that same login takes it (logins compare without case).

- `act_on_failed_checks` (true/false, default false): act on failed checks (below). Any other value is off.

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
runner pauses instead of stopping when its login lookup gets no answer (after 30 minutes without one it stops
with a log line; the next `queue add` or `--wait` starts a runner). An entry without a login leaves with the
reason. A member whose own checks still run or are missing can still join: the checks of the group run on its code.

Every member is looked at again (state open, not a draft, same base branch and allowed, same head commit, no
changes requested or missing review, no unanswered Merge card) before its group is built, just before the
group pull request is opened, and right before the merge: the core waiter asks the runner (`before_merge`) just
before `gh pr merge`, after the wait for room. That last check also needs the group pull request itself still
open, on the same head and the same allowed base branch, and gh still on the runner's login; a check that fails
with an error stops the merge. Changes requested count from `reviewDecision` and from each reviewer's latest
decision in `reviews` (approved, changes requested or dismissed; a later comment does not take a change request
back), because `reviewDecision` is empty when the base branch's rules require no reviews. A hold whose members
did not change counts as a try. A member that changed is taken out (closed, draft, base not allowed, review, Merge card) or
put back in line (new commit, another allowed base branch); a group that was stopped this way is closed and the
rest wait again. One left: the core waiter
(`orch.prwait.run_one(url, True, queue=True)`, merge on green). In queue mode the waiter never takes the base
branch into the pull request's branch: when the base got commits that touch its files since it took the base in,
it answers `behind`, and the runner checks it once on top of the base as a group of one (a group commit of just
that pull request, its own group pull request "Merge queue: #a"); red, a conflict with the base, or a fork then
leaves the queue with what to do. So no pull request runs its checks again after each merge. Several: a group commit built in a bare blobless copy
(`git merge-tree --write-tree` + `git commit-tree`, nothing checked out), pushed to `orch-queue/<base>-<unix time>-<workspace mark>` (6 hex characters of the workspace path, so two
workspaces never share a branch),
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
deletes `orch-queue/*` branches it did not write down: two workspaces on one repository each keep their own. Red base branch (ORCH-391): before each round the runner reads the failed jobs of the base branch's last finished push run of each workflow (`gh run list --event push`, cancelled runs skipped; one look per minute). While that is red it builds no groups: one entry at a time, fixes first (added with `--first`, or its ticket is a red-run ticket of the release keeper: a child of the `github.release_keeper` role ticket whose done-when line says a run is green). A pull request or group whose failed checks are all among the base branch's failed jobs is not blamed: not split, no try used, it waits 5 minutes for the fix (a fix that is still red in them uses a counted try). One that fell behind waits until the base is green instead of its check on top of the base. Group titles are
written as code text, so words in a title never close issues; only GitHub's own closing references are repeated. Each verdict goes on the entry's ticket (history line and reference state). When an entry with a ticket leaves
the queue unmerged, the ticket's helper is woken with the reason and the `queue add` line to run again (the same
wake as failed checks: a live helper gets it as input, otherwise one is started; a history line says which), since
helpers put their pull request in line and finish. Not for one that was closed, made a draft or is merged with a
Merge card (reference states `closed`, `draft`, `owner merges`). Every GitHub
write takes a slot of `orch.ghlimit`, except the merge itself: the queue merges one group per run of the checks,
so its merges are counted (`orch github writes`) but never wait for the hourly merge count. `orch ref wait
--merge` outside the queue still waits for it and still takes the base in.

Known limit: a base branch whose rules require an approving review never merges a group pull request (nobody
reviews it); its members end after 3 tries. The queue is meant for base branches without that rule.

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

## Pull requests page and live state on tickets (ORCH-165)
- Every watcher round first reads the repositories the tickets link (a pull request, an issue or the repository on an
  open ticket, plus every linked pull request not yet recorded merged or closed), one read-only `gh api graphql`
  call per repository (open pull requests, newest 50, and the linked ones by number), at most 10 repositories.
  Nothing is written to GitHub. Kept in `.orch/addons/pull-requests/prs.json` (`{"schema":
  "orch.pull-requests-prs/1", "polled_at", "repos": {repo: {"polled_at", "error"?, "open": [n]}}, "prs": {url:
  row}}`; the folder and file are never followed through a link).
- A ticket changes only through the core: `orch pull-requests act refresh --by agent:pull-requests -- <ticket>`
  (env `ORCH_PULL_REQUESTS_CACHED=1`: answer from prs.json), and only when what it shows differs. The answer sets
  each pull request link's `status` (`open`, `draft`, `checks running`, `checks failed`, `conflict`, `behind`,
  `blocked`, `ready to merge`, `merged`, `closed`), its `title` when the link has none, and `ext.pull-requests`
  `pr` / `checks` (`Passed` · `Running` · `Failed` · `No checks`) / `merge` (`Ready to merge` · `Blocked` · `Behind
  its base` · `Has a conflict` · `Draft` · `Not known yet` · `Merged` · `Closed`) of the ticket's newest open pull
  request: read-only fields under Details that store the shown words. A person's Refresh or a helper (no env) reads GitHub first. Checks follow the core waiter's words: only
  SUCCESS passes, SKIPPED is fine, an unexpanded matrix job is left out, anything else finished is a failure.
- `orch pull-requests view --json`: the page (orch.addon-view/1, read only, no GitHub call): three counts (Open,
  Checks failed, Ready to merge), one table per repository (Pull request with branch and author, Ticket, Checks,
  Merge; failed first, then ready to merge, then newest), the empty state, and a notice with Start reading when the
  watcher does not run. `orch pull-requests poll [--json]`: one read now.

## Failed checks (ORCH-167)
Off until `act_on_failed_checks = true`. The Merge when green watcher runs one pass every minute after its own
(a failure of one part never skips the other). One pass looks at each open pull request linked on a ticket that
is Ready, Working, Waiting or in Review (not Backlog, Done or Won't do) (a pull request on two tickets: the first ticket), with one read
(`gh pr view --json state,isDraft,headRefOid,statusCheckRollup`), the newest check per name:
- a GitHub Actions job that ended cancelled or timed out is run again once per commit and job name
  (`gh run rerun --job`). It first takes a slot of `orch.ghlimit` (kind `other`) without waiting; no room: no
  rerun and no wake this pass. A rerun GitHub refused is not tried again and counts as a real failure. For 10
  minutes after a rerun the replaced job still shown by GitHub counts as running.
- when every check of the commit has finished and one failed (failure, error, startup failure, action required,
  or cancelled / timed out again after its rerun), the ticket's helper is woken once per commit: a live helper
  gets an input of kind `event`, otherwise the input is queued and the helper is started like the helper
  watcher does (`agent:automation`, so the pause and the daily cap apply). The text names the pull request, the
  short commit, each failed check with its link, and the last 30 lines (each cut at 300 characters, colour codes
  and time stamps removed) of up to 3 failed jobs' logs (`gh run view --job --log-failed`). A log line that
  `orch.secretscan` flags (scanned over the last 400 lines before they are cut, with the workspace's stored
  keys; when those cannot be compared no log is shown) is replaced by "(line hidden: it looks like a secret)";
  a private key block is hidden whole, also when its BEGIN line lies before the window. Check names, links and
  log lines are quoted (names in code text, the log in a fenced block with backticks and control characters
  removed) and marked as data, never instructions. A pull request from a fork gets names and links only, no
  logs. Only jobs of the pull request's own repository are rerun or read.
- each rerun and wake writes one history line on the ticket (`agent:failed-checks`).
Memory: `.orch/addons/pull-requests/checks.json` `{pull request key: {head, reran: {name: {job, ok, at}}, woke}}`;
a new commit starts over; pull requests no longer open on an open ticket are dropped.

### A test broken for everyone (ORCH-455)
Part of the same pass, so off with it. Before the wake, the logs of up to 6 failed jobs are read once. "The same
way" is the check name plus every failing test its log names (pytest `FAILED a.py::t`, also after xdist's
`[gw0] [ 50%]`; node `not ok N - name`; sorted, joined by ` + `), else the last error line with numbers, hashes
and temp paths taken out; a log naming neither never counts, nor does a pull request from a fork.
- When the same check fails the same way on 3 or more pull requests of 3 or more tickets within an hour, the test
  is broken: one GitHub issue is opened (`gh issue create`, a slot of kind `other` first; no room or refused: a
  later pass tries again), its body lists the pull requests and the secret-checked end of one log.
- The helpers of the pull requests that showed it, also those already woken to fix it, are woken once with "not
  your change: do not change your pull request for it" (one history line each). Later pull requests failing only
  in a broken test get that text instead of the fix-it wake; one with another failure too gets the fix-it wake
  with a "Not your change" list. A failed check whose log names no failure of its own, next to a broken test, only
  sums up the others: not counted as theirs, and remembered with the broken test (`along`).
- orch makes one ticket per broken test ("Broken test: ...", the issue linked) and asks a person there once
  (kind `pull-requests:aside`, options "Put it aside" / "Leave it"). "Put it aside": the test is set aside; the
  repository's Actions variable `ORCH_ASIDE` (`gh variable set`, a slot of kind `other`) is set to a JSON list of
  `{check, test, issue}` so the repository's own test run can count it as an expected failure (still run and
  shown); a pull request failing only in set-aside tests wakes no helper (a history line only). "Leave it": never
  asked again.
- The merge queue does not blame a pull request or group whose failed checks are all checks with a broken test
  (found or set aside) or such a summing-up check: not split, no try used, it waits 5 minutes, as for a red base
  branch.
- Every 10 minutes the issue is read (`gh issue view --json state`); closed: the test counts again, `ORCH_ASIDE`
  is set without it, a history line goes on its ticket. A broken test without an issue and no new failure for
  2 days is forgotten.
Memory: `.orch/addons/pull-requests/broken.json` `{hits: [{key, pr, ticket, at}], tests: {key: {repo, check, test,
prs, issue, ticket, question, aside, fixed, told, ...}}}`.
