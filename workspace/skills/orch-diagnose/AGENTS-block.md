## orch diagnose

When told "Investigate orch report <ref>", or when orch looks stuck or broken, read `.agents/skills/orch-diagnose/SKILL.md`.

1. Read the report in order: `SUMMARY.md`, `errors.json`, `timeline.jsonl` around the problem time, `state/`, then content.
2. Live follow-ups: `orch diag inspect` and `orch diag query`. Both are read-only.
3. Check out the commit in `manifest.json` (a separate worktree) before reading the source.
4. Answer with the cause, the evidence (report line references), a fix proposal and the fixture or check that would have caught it.

Never delete or change anything while investigating.
