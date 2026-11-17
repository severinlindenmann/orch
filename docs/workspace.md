# Tickets, tasks and proof

orch keeps your work in **tickets**. A ticket has **tasks**. A task counts as done only with **proof**.
Everything is a plain file in `.orch/` in your project. No server, no account. Words: [wording.md](wording.md).

Lines that start with `$` are run by `e2e/docs_check.py`, so they stay true.

## Make a ticket

```sh
$ orch init
$ orch ticket new "Fix the invoice export"
$ orch check add <id> "Export the file"
$ orch check add <id> "Check it opens"
$ orch ticket edit <id> --owner Anna --due 2026-12-01 --note "Ask finance first"
$ orch ticket summary <id> "Export works, the check is left"
$ orch ticket show <id>
```

Every ticket gets a short key such as `INV-12`: the workspace code and a running number. Use the key anywhere a
command wants a ticket (`orch check add inv-12 "Export the file"`); the id `t_…` keeps working too. `orch init` picks
the code from the folder name (`--code INV` to choose it); `orch config set workspace.code INV` changes it for new
tickets, old keys stay as they are. Numbers are never reused.

Owner, due day and note are free text for people. orch never acts on them. The summary is one or two sentences on
where things stand; it is what you see first on the dashboard and the phone.

## Tasks

```sh
$ orch check start <id> c1
$ orch check edit <id> c2 "Check it opens in Excel"
$ orch check move <id> c2 --after c1
$ orch check stop <id> c1
$ orch check remove <id> c2
```

`start` marks the task someone is working on. `remove` keeps the task in the history. `reopen` opens a done task again. `orch check wont-do <id> c2 [--reason "…"]` is a person's decision that a task will not be done: it counts as resolved, needs no proof, and `reopen` undoes it. Agents cannot set it; they ask.

## Proof

A task is done when it has proof: a command, a note, a file, a link, a commit or a pull request.

```sh
$ orch check done <id> c1  # refused
$ orch check done <id> c1 --command "uv run pytest -q"
$ orch check reopen <id> c1
$ orch check done <id> c1 --file report.csv --title "The export" --role result
$ orch ticket status <id> done
```

When an agent sends a ticket to Review while a step's proof is changed or failed, the move goes through, with the honest proof line, and the command prints as its next step: run the checks again and record them with `orch check record`.

`--file` copies the file into `.orch/tickets/<id>/evidence/`. Proof files are not committed to git (they stay on this
computer). On another computer the ticket shows "file on another computer". Roles: `result`, `check`, `support`.

## Sub-tickets

```sh
$ orch ticket new "Check the totals" --parent <id>
$ orch ticket tree <id>
```

A big ticket can be split into sub-tickets. The parent shows "Sub-tickets: 0 of 1 closed".

## Questions and what needs you

```sh
$ orch ask <id> "Send it to finance now?" --option Yes --option "Not yet" --recommend Yes
$ orch needs
$ orch answer <id> q1 "Yes"
$ orch needs
```

`orch needs` is one list of everything that waits for a person: open questions first, then failed runs and add-on
rows (for example "automation is not running"). The same list is on the dashboard and the phone.

To pause a ticket until a time: `orch wait <id> --until 2026-12-01T08:00:00+01:00`.

When the agent asks: only when a step cannot be undone, costs money, touches production, deletes real data or is
visible to people outside this workspace and its connected workspaces; everything else it just does. To change that
list, write your own in `.orch/ask-when.md` (plain lines, one case each); the agent reads it before it asks and it
replaces the default. While a question waits, the agent keeps working on the steps that do not need the answer.

## Review stack

Things that wait for your yes (a draft, a Check result, a plan, a link before it goes public, a question with
choices) are shown as cards you answer with one gesture: right is yes, left is no, down is "change this". A
card is a question on the ticket with a `card` (what you were shown) and `shown` (an exact copy of the files it
showed, kept under `.orch/tickets/<id>/reviewed/`, so a later change to a file never moves your answer onto
something else).

Your answer is kept on the ticket, in the same list as questions: one entry per card, never overwritten. A
decision has a plain one-line summary (for example "Use C with 2 changes: questions on top; month in the
heading.") which is also the answer text in the history. If you change your mind, a new entry is added that
replaces the old one; the old one stays and says what replaced it. Helpers read a short "what applies now"
block built from these entries. A Check result answered "looks good" marks the ticket Done exactly as
Accept does; "send back" works like Ask for changes.

## References and history

```sh
$ orch ref add DM1-12 https://github.com/acme/billing/pull/418
Added reference to DM1-12: https://github.com/acme/billing/pull/418
$ orch ref add DM1-12 https://www.figma.com/design/k2Lq9/Billing --title "Export button states"
$ orch ref list DM1-12
  1  Pull request  github.com/acme/billing/pull/418  open
  2  Figma         Export button states
$ orch ref rm DM1-12 2
$ orch ticket set MK2-7 marketing.budget 2400        # an add-on field (shown under Details)
$ orch log <id> "Waiting for the new price list"
```

Every change is written to the ticket's history with who did it and where (`via`: terminal, dashboard, phone).

## Separate copies

When two agents work in the same project at once, orch gives each ticket its own copy of the project (a git worktree under `~/.orch-work/<workspace>/<ticket>`, next to orch's own folder `~/.orch-tool`, so an agent in a copy can read its instructions and skills but never orch's keys), so they do not edit the same files. Settings: Off, When agents work together (default), Every time.

A copy is removed when its ticket is Done, closed or cancelled and no agent is working in it any more, and a start also checks for copies nobody needs. Before a copy goes, everything in it that git tracks or sees as new is saved on the branch `orch/<ticket>` of your project; the branch is deleted once it is merged, or after 14 days when it is not (counted from its last change). What is not kept: files git ignores (such as `.env` or build folders), and the inside of nested repositories and submodules (only the link is saved). Large new files are saved to the branch like any other. A removed copy waits a day in a trash folder first, and stays there for you to look at if something wrote into it after it was saved. If a copy cannot be saved (git is missing, the copy is on another branch, git was interrupted) it is kept and the dashboard says why; "Try again" or `orch copy retry <ticket>` clears an old lock left by an interrupted git.

Copies of a project that was moved or deleted are never removed by themselves: the dashboard counts them, and you decide ("Remove the moved ones", or `orch copy remove-orphaned <folder>`; changes are saved first when git can still reach the project). `orch copy clean` runs the check by hand.

## What orch does not protect

- An agent runs as you. orch is a shared to-do list with proof, not a lock.
- "You" or "human" in the history is a label. Any agent can write it.
- Work outside orch (an agent running in another terminal) is not stopped or tracked.
- Only messages sent through orch are tracked.

Relay and publish are separate add-ons. A workspace may use either one alone, or neither.

# Reference

## What it does
Tickets as JSON files that any agent tool can use: tasks that count as done only with proof, links to any tool,
questions and answers, history. Relay and publish ship in the same package as built-in add-ons: off until
`orch addon add publish|relay`. Runs on Windows, macOS and Linux, with or without git.

## Commands
| Command | Does |
|---|---|
| `orch init [--code XY]` | Sets up the project folder, asks which agent to use, sets the ticket key code. Safe to run again |
| `orch ticket new\|list\|show\|tree\|edit\|summary\|status\|wait\|patch` | Tickets. `done` is refused while a ticked task lacks proof |
| `orch ticket attach <id> --name <hint>` | Keeps a text file or picture (read from stdin, at most 25 MB) with the ticket in `artifacts/`. orch picks the file name; the dashboard uses it for a long pasted text (`note.md`) and dropped files |
| `orch check add\|edit\|move\|remove\|reopen\|start\|stop\|done\|wont-do` | Tasks and proof |
| `orch ask` / `answer` / `needs` | Questions and the list of what needs a person |
| `orch ref add\|list\|rm`, `orch ticket set`, `orch log`, `orch ext set\|unset` | References (URLs, tickets, artifacts and files; kind from the active add-ons, else the known-sites table, else Reference), add-on fields, history, add-on data (`ext.<addon>`; `ext unset <id> <addon>[.<key>] [--if-revision N]` removes it) |
| `orch agents`, `orch config`, `orch run ...` | Agents and runs: [agents.md](agents.md) |
| `orch doctor` | Shows what is wrong with orch here (read-only): PATH, git, uv, this folder's skill link, instruction file and reminder, plus the run checks of `orch diag inspect`. Each problem names the next step; ends with "Nothing wrong." or "N things to fix." |
| `orch doctor setup <file>\|--off`, `orch doctor pass [--dry-run]`, `orch doctor soon` | The scheduled health checks and clean-up of this computer (no AI call): every 15 minutes, started by the automation loop and the pages, never by a ticket or a repeat. The setup (JSON, kept in the orch home, never in the project) names the disk limits, load limit, addresses, processes and launch agents to watch and the folders to clean. One pass cleans up by exact path, opens one ticket per problem (none while that one is open, none when all is fine), notes on the ticket when a problem went away, and pauses automatic starts on a full disk (resumed only when the pass paused them). `orch doctor` says when the passes stopped |
| `orch doctor clean [--apply]`, `orch doctor remove-temp <path>...`, `orch doctor stop-pids <pid>...` | Clean-up by hand: finished copies (clean, merged, idle, no process in them; `git worktree remove` without force), old build output and test folders; temp folders your own mktemp made; exactly these processes (TERM, then KILL after 5 s; exit 1 when one is refused or survives) |
| `orch uninstall` | Takes orch out of this folder: add-ons, background processes, skills and links, orch's lines in `CLAUDE.local.md` / `.claude/settings.local.json` / `.git/info/exclude`, this folder's entries in the orch home, `.orch/harness`, `.orch/run`. Keeps `.orch/tickets`, `.orch/config.toml`, `.orch/secrets`. Safe to run twice; removing orch itself: `uv tool uninstall orch-workspace` |
| `orch addon add\|list\|remove\|uninstall`, `orch start\|stop\|status`, `orch update` | Add-ons: [addons.md](addons.md) |
| `orch pause [--reason "<why>"]` / `orch resume` | The runaway brake: pause stops all automation in this workspace (nothing starts on its own), resume turns it back on |

All commands accept `--json` for agents. Exit code 0 = ok, 2 = refused (stderr `Refused: <reason>`; a confirmation that needs `--yes` without a terminal prints just its question; with `--json` stdout `{"error": "<reason>"}`), 1 = bug.

## Pause and run cap
`orch pause` writes `.orch/run/paused.json`. While it is there, every start that is not a person's is refused with
one sentence ("Automation is paused in this workspace. Turn it back on with: orch resume."), extra turns of a
running one-step agent are not continued, and `orch status` says so. `--reason` keeps one short line of why in the
same file (a script that pauses on a full disk: "Disk almost full: 8 GB free"); the refusal and `orch status` then
name it ("Automation is paused in this workspace: Disk almost full: 8 GB free. Turn it back on with: orch resume.").
Pausing again keeps the first record. A person's own start always works. On top of that,
automatic starts are capped at 20 per ticket in a rolling 24 hours (counted in `.orch/run/starts.json`); the first refusal
of the day adds one history line to the ticket. Person starts are never counted.

## Data storage
`.orch/` in the workspace (contracts/local-files.md). Tickets may be committed; secrets and inbox are gitignored.
The core never names an add-on: no scheduler/dashboard words in core code or core skills; `ext.<name>` stays opaque.

## Tests
- T0: `uv run pytest tests/test_<area>.py -x -q` (e.g. `test_tickets.py -k evidence`).
- Contract tests: every `contracts/examples/ticket/*` loads/validates as expected; `vectors/publish-blob-v1.json` decrypts.
- Fake publish/relay servers in-process for client tests. CI: `workspace/**`, `contracts/**`; matrix ubuntu, macos, windows
  (PRs into develop: Linux, plus the Windows standard-user install when the install path changed).

## Install
One line from GitHub (public repo): `install.sh` / `install.ps1` in the repo root install `uv` if missing, then
`uv tool install https://github.com/severinlindenmann/orch/archive/<ref>.zip#subdirectory=workspace` (a zip download:
no git needed). Then `orch init` per project. Add-ons and `orch update` install from the same place.
Leave: `orch uninstall` in a project, then `uv tool uninstall orch-workspace` to remove orch itself.

Windows: works for a standard user (no admin rights), without git and with the default execution policy (the uv
installer runs with a bypass for that one process only). On Windows on ARM the installer picks an x64 Python
(`cryptography` has no ARM64 Windows build). Windows can not replace a running program's files, so `orch addon add`,
`orch addon uninstall` and `orch update` finish in the background right after the command ends (about a minute; log:
`finish.log` in orch's home, `orch addon list` shows the result; wait for it before the next orch command). CI runs
`e2e/windows/run-as-standard-user.ps1` on develop pushes and on PRs that change the install path: the standard-user
flow (install, init, ticket, dashboard add-on in the background, update) and the scheduler flow (automation add-on: a
repeat and a one-time wake-up in a named time zone start a fake agent). On a winvm clone run the same script; add
`-Flows dashboard` for the dashboard smoke (Playwright inside the machine opens Home, Tickets, a ticket, General and
Settings, and at 720 and 390 px; screenshots end up in `C:\Users\Public\orchsmoke\shots`).
`-Flows relay -EnvFile <file>` adds a relay round trip with a Mac workspace: `e2e/windows/relay-pair.py` makes the two
workspaces on a relay and writes the file, `e2e/windows/relay-peer.py` answers on the Mac (text and file back).
`-Flows tls` checks how orch checks web certificates on Windows: a trusted certificate for the right name is accepted,
one for another name and a self-signed one are refused (the self-signed server never gets the token).

## Not included
Signing, approvals, planning gates, fixed requirements, durations, a server.
