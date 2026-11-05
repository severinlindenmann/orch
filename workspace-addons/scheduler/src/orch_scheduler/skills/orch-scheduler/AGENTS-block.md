## orch-scheduler
Starts agent runs at a time, on a repeat, and when the phone or another workspace sends work. Read `.agents/skills/orch-scheduler/SKILL.md`.
Wake a ticket later: `orch wait <id> --until <time>`. Repeat it: `orch scheduler repeat <id> "<cron>"`.
Do not start the scheduler yourself unless the user asks.
