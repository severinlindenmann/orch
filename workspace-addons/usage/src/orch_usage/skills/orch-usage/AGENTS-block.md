## orch-usage
The accounts the helpers spend on (subscriptions, API credits), their limits, order and history. Read `.agents/skills/orch-usage/SKILL.md`.
See them: `orch usage list`. Change a rule only when the person asks for it: `orch usage limit <account> <number>`; every change lands in the history.
Before your own subagent or a credit skill spends, ask `orch usage ask <kind of work>` (Lead, Code, Reviews, Builds, Scripts or Helpers); when it says No room, do not start it: say so on the ticket and wait.
