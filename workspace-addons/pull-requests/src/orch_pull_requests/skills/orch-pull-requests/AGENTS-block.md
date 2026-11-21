## orch-pull-requests
Every merge into develop goes through the merge queue, never `gh pr merge` or `orch ref wait <id> --merge`: mark the pull request ready, then `orch pull-requests queue add <pull request url> --ticket <id>` and finish your ticket; do not wait for its checks. The verdict goes on the ticket. A fix for a red develop: add `--first`. A CI change: queue it too; it runs alone first.
Or switch the ticket on: `orch ticket set <id> pull-requests.merge_when_green on` (queued by itself once ready). Read `.agents/skills/orch-pull-requests/SKILL.md`.
