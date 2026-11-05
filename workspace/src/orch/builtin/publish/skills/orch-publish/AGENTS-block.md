## orch-publish
Share files and small apps by private link. Read `.agents/skills/orch-publish/SKILL.md`.
Publish only what the user asked for. Never publish anything from `.orch/secrets/`.
Add the resulting link to the ticket with `orch link add`.
Right after connecting, describe this workspace once: `orch publish profile --description "<one sentence>" --tags a,b` (2-4 tags).
Give the user the whole link `orch publish file` prints (it ends in `#k=...`); the app link keeps its `?token=`.
