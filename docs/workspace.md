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

`start` marks the task someone is working on. `remove` keeps the task in the history. `reopen` opens a done task again.

## Proof

A task is done when it has proof: a command, a note, a file, a link, a commit or a pull request.

```sh
$ orch check done <id> c1  # refused
$ orch check done <id> c1 --command "uv run pytest -q"
$ orch check reopen <id> c1
$ orch check done <id> c1 --file report.csv --title "The export" --role result
$ orch ticket status <id> done
```

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
| `orch check add\|edit\|move\|remove\|reopen\|start\|stop\|done` | Tasks and proof |
| `orch ask` / `answer` / `needs` | Questions and the list of what needs a person |
| `orch ref add\|list\|rm`, `orch ticket set`, `orch log`, `orch ext set\|unset` | References (URLs, tickets, artifacts and files; kind from the active add-ons, else the known-sites table, else Reference), add-on fields, history, add-on data (`ext.<addon>`; `ext unset <id> <addon>[.<key>] [--if-revision N]` removes it) |
| `orch agents`, `orch config`, `orch run ...` | Agents and runs: [agents.md](agents.md) |
| `orch addon add\|list\|remove\|uninstall`, `orch start\|stop\|status`, `orch update` | Add-ons: [addons.md](addons.md) |

All commands accept `--json` for agents. Exit code 0 = ok, 2 = refused (stderr `Refused: <reason>`; with `--json` stdout `{"error": "<reason>"}`), 1 = bug.

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

Windows: works for a standard user (no admin rights), without git and with the default execution policy (the uv
installer runs with a bypass for that one process only). On Windows on ARM the installer picks an x64 Python
(`cryptography` has no ARM64 Windows build). Windows can not replace a running program's files, so `orch addon add`,
`orch addon uninstall` and `orch update` finish in the background right after the command ends (about a minute; log:
`finish.log` in orch's home, `orch addon list` shows the result; wait for it before the next orch command). CI runs
`e2e/windows/run-as-standard-user.ps1` on develop pushes and on PRs that change the install path: the standard-user
flow (install, init, ticket, dashboard add-on in the background, update) and the scheduler flow (automation add-on: a
repeat and a one-time wake-up in a named time zone start a fake agent). On a winvm clone run the same script.

## Not included
Signing, approvals, planning gates, fixed requirements, durations, a server.
