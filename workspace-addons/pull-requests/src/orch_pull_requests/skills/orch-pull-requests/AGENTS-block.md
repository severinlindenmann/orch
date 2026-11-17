## orch-pull-requests
Merge on green through the merge queue: `orch pull-requests queue add <pull request url> --ticket <id> --wait` instead of `orch ref wait <id> --merge`.
Exit 0 = merged; otherwise the last line says why. Read `.agents/skills/orch-pull-requests/SKILL.md`.
