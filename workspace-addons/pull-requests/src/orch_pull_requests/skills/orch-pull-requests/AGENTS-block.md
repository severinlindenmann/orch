## orch-pull-requests
Merge on green through the merge queue, never with `orch ref wait <id> --merge`: mark the pull request ready, then `orch pull-requests queue add <pull request url> --ticket <id>` and finish your ticket; do not wait for its checks. The verdict goes on the ticket. Never take develop in or push only to restart checks, and never ask several helpers to push at once: the queue checks on top of develop.
Or switch the ticket on: `orch ticket set <id> pull-requests.merge_when_green on` (queued by itself once ready). Read `.agents/skills/orch-pull-requests/SKILL.md`.
