## orch-scheduler
Starts agent runs on a time or by cron. Read `.agents/skills/orch-scheduler/SKILL.md`.
To wake a ticket later: `orch wait <id> --until <time>`. To repeat: `orch ticket new "<title>" --recurring "<cron>"`.
Do not start the scheduler yourself unless the user asks.
