## orch-pull-requests
Merge on green through the merge queue: `orch pull-requests queue add <pull request url> --ticket <id> --wait` instead of `orch ref wait <id> --merge`.
Exit 0 = merged; otherwise the last line says why. Or switch the ticket on: `orch ticket set <id> pull-requests.merge_when_green on` (merged by itself on green, no waiting). Read `.agents/skills/orch-pull-requests/SKILL.md`.
