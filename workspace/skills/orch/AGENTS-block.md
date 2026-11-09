## orch workspace

1. Every change belongs to a ticket: `orch ticket list`, else `orch ticket new "<title>"`. In Chat never run `orch ticket new`: propose it with `--ref proposal:<short ticket title>`.
2. Add one task per piece of the person's work, in plain words (no ids, paths or commands), BEFORE you start: `orch check add <id> "<step>"`.
3. A task is done only with proof: `orch check done <id> <c> --command "<what you ran>" --summary "<what came out, one line>"` (or --note, --pr, --commit, --file, --url).
4. Need a decision or blocked: `orch ask <id> "<question>" --option A --option B --recommend A`, then stop.
5. End every run with `orch ticket summary <id> "<what was done and what is left>"`, then `orch ticket status <id> done` (orch moves it to Review; never claim it is Done). When the ticket reaches Review, orch sends its summary and files to the person by itself: add no task for that and don't write that it was sent. Answering a person's message is still your job.

Plans may change. There are no signing or planning gates. Details, notes, files and icon: the orch skill (`.agents/skills/orch/SKILL.md`).
