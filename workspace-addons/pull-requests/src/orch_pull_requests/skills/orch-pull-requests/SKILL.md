---
name: orch-pull-requests
description: See each pull request's checks and merge state (on the Pull requests page and live on its ticket) and merge a finished pull request through the merge queue, which merges several together after one run of the checks. Use when a ticket links a pull request, should be merged once its checks pass ("merge on green") and the pull-requests add-on is on. Not for opening pull requests or for pull requests a person merges with a Merge card.
---
# orch merge queue

When many pull requests are ready at once, merging them one by one makes each later one take the base branch in and
run its checks again. The merge queue puts them in line instead: several go on one group branch, the checks run once,
and all of them are merged together on green. A red group is split in halves and tried again, so the good ones still
get merged. No AI call: a program does the waiting and merging.

## When to use
- Your ticket's pull request is ready and the rules say to merge it on green.
- Several helpers finish pull requests for the same repository within minutes.

## Recipes

**1. Merge on green through the queue** (replaces `orch ref wait <ticket> --merge`)

    orch pull-requests queue add <pull request url> --ticket <ticket> --wait

Run it bare, not through a pipe. Exit 0 = merged (alone or with its group); exit 1 = it left the queue, the last line
says why (checks failed, a draft, closed, conflicts with the base branch, no room in the GitHub write limit). The
verdict also goes on the ticket. Fix what it says, push, and add it again. The pull request must be ready (not a draft).

**2. Or let the ticket's switch do it** (Merge when green)

    orch ticket set <ticket> pull-requests.merge_when_green on

The background watcher (`orch start`) then puts the ticket's open, ready pull requests in the queue by itself every
minute; you do not wait. Mark the pull request ready (not a draft) when it is done. Use it when the ticket or the
person says to merge on green; leave it off when a person merges with a Merge card. Turn it off again with `off`.

**3. Look at the line**

    orch pull-requests queue list

**4. Take a waiting pull request out**

    orch pull-requests queue remove <pull request url>

**5. See the checks** (no waiting, no GitHub call of your own)

While the add-on runs (`orch start`), it reads the repositories your tickets link once a minute, read-only, and keeps each linked pull request's state on its ticket: the link shows `Checks running`, `Checks failed`, `Ready to merge`, `Merged` and so on, and the ticket's Details show its newest open pull request's checks and merge state. The dashboard's Pull requests page lists the open pull requests with their ticket, checks and merge state. Update one ticket now:

    orch pull-requests act refresh -- <ticket>

Link every pull request to its ticket with `orch ref add`; one no ticket links shows on the page but on no ticket.

## Rules
- A pull request a person merges with a Merge card is never queued.
- Group pull requests are named "Merge queue: #12, #15"; do not push to their `orch-queue/...` branches.
- Every GitHub write counts toward this computer's write limit (`orch github writes`).
