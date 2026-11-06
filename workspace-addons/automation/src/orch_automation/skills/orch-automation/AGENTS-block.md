## orch-automation
Starts agent runs at a time or on a repeat{{#relay}}, and when work arrives from outside{{/relay}}. Read `.agents/skills/orch-automation/SKILL.md`.
Wake a ticket later: `orch wait <id> --until <time>`. Repeat it: `orch automation repeat <id> "every monday 08:00"`.
Do not start the automation yourself unless the user asks.
