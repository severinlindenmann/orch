## orch workspace
Track every piece of work as an orch ticket: `orch ticket list`, else `orch ticket new "<title>"`; then one step per piece of work (`orch check add <id> "<step>"`) BEFORE you start. A step is done only with proof: `orch check done <id> <c> --command "<what you ran>"` (or --note, --pr, --commit, --file, --url).
Need a decision or blocked: `orch ask <id> "<question>" --option A --option B --recommend A`, then stop. End every run with `orch ticket summary <id> "<where things stand>"`. Details: `.agents/skills/orch/SKILL.md`.

Ticket statuses are Backlog, Ready, Working, Waiting, Review, Done, and Dropped. When the work is finished set the ticket to done: orch moves it to Review for a person to check; never wait for or claim it is Done. If `orch look show` says nobody picked an icon, choose one from `orch look list` and run `orch look set --icon <id> --color <token>`; never change a person's pick.
