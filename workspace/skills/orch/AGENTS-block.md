## orch workspace
Every piece of work is tracked as an orch ticket. Before you start: run `orch ticket list`; if none fits, run `orch ticket new "<title>"`.
Right after creating or picking a ticket, and BEFORE you start work, add one checklist item per step (`orch check add <id> "<step>"`). A ticket with no checklist items is not allowed. Mark each item done with proof (`orch check done <id> <c> --command "<what you ran>"`, or `--note`, `--pr`, `--commit`, `--file`, `--url`) before you finish. A checklist item counts as done only with evidence.
Before a task: `orch check start <id> <c>`. End every run with `orch ticket summary <id> "<where things stand>"`.
Details: `.agents/skills/orch/SKILL.md`. When waiting for an answer, save context and pause.
