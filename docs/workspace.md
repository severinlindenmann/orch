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

## Links and history

```sh
$ orch link add <id> --type github --url https://example.com/pr/1
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
| `orch init` | Sets up the project folder, asks which agent to use. Safe to run again |
| `orch ticket new\|list\|show\|tree\|edit\|summary\|status\|wait\|patch` | Tickets. `done` is refused while a ticked task lacks proof |
| `orch check add\|edit\|move\|remove\|reopen\|start\|stop\|done` | Tasks and proof |
| `orch ask` / `answer` / `needs` | Questions and the list of what needs a person |
| `orch link add`, `orch log`, `orch ext set` | Links, history, add-on data (`ext.<addon>`) |
| `orch agents`, `orch config`, `orch run ...` | Agents and runs: [agents.md](agents.md) |
| `orch addon add\|list\|remove\|uninstall`, `orch start\|stop\|status`, `orch update` | Add-ons: [addons.md](addons.md) |

All commands accept `--json` for agents. Exit code 0 = ok, 2 = refused (stderr `Refused: <reason>`; with `--json` stdout `{"error": "<reason>"}`), 1 = bug.

## Data storage
`.orch/` in the workspace (contracts/local-files.md). Tickets may be committed; secrets and inbox are gitignored.
The core never names an add-on: no scheduler/dashboard words in core code or core skills; `ext.<name>` stays opaque.

## Tests
- T0: `uv run pytest tests/test_<area>.py -x -q` (e.g. `test_tickets.py -k evidence`).
- Contract tests: every `contracts/examples/ticket/*` loads/validates as expected; `vectors/publish-blob-v1.json` decrypts.
- Fake publish/relay servers in-process for client tests. CI: `workspace/**`, `contracts/**`; matrix ubuntu, macos, windows.

## Install
One line from GitHub (public repo): `install.sh` / `install.ps1` in the repo root install `uv` if missing, then
`uv tool install git+https://github.com/severinlindenmann/orch#subdirectory=workspace`. Then `orch init` per project.

## Not included
Signing, approvals, planning gates, fixed requirements, durations, a server.
