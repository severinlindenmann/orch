---
name: orch-focus
description: Use when a person wants to watch an agent work on a ticket, answer its questions as they come, or send it a message while it works. Focus is a live page; you only keep the ticket current.
---

# orch focus

Focus shows one ticket live: its tasks, what the agent is doing, its questions, and a message box.
Open it with `orch focus open <ticket>`. It starts, messages and stops agents only through `orch run start|send|stop`.

For you, the agent: keep the ticket current. `orch check start <ticket> <task>` when you begin a task,
`orch check done <ticket> <task> --note "what shows it"` when it is done, and `orch ask` when you need an answer.
The page builds its board from those, so every agent shows the same board.

This is a short first text; the full guide comes with the skills pass.
