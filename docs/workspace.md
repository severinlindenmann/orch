# orch-workspace

## What it does
Tickets as JSON files that any agent tool can use: checklist items that count as done only with evidence,
links to any tool, questions and answers, history. Plus the client commands for publish and relay.
Runs on Windows, macOS and Linux, with or without git.

## Tech stack
Python 3.12, uv. Stdlib `argparse`, `json`, `urllib.request`. Deps: `cryptography` (publish file encryption), `jsonschema` (check every write against `contracts/ticket.schema.json`). No server.

## Folder layout
```
workspace/
  pyproject.toml            package orch-workspace, script "orch"
  src/orch/cli.py           argument parsing only
  src/orch/tickets.py       load/save/validate, keeps unknown fields, atomic write (tmp + rename)
  src/orch/init.py          orch init: folders, skill, AGENTS.md block, .claude/skills link, .gitignore
  src/orch/addons.py        orch addon add|list|remove|uninstall, activation, add-on dispatch (subprocess), orch update
  src/orch/publish.py       publish client (encrypt, upload, apps)
  src/orch/relay.py         relay client (inbox, send, allow, refresh, webhook)
  skills/{orch, orch-publish, orch-relay}/SKILL.md   copied into projects by init / connect
  tests/
```

## Commands
| Command | Does |
|---|---|
| `orch init` | Set up the project folder (local-files.md). Safe to run again |
| `orch addon add <name\|./folder> [--yes]` / `remove <name> [--purge]` / `list` / `uninstall <name>` | Add-on contract (contracts/addon-manifest.md): install a built-in or local add-on and turn it on in this workspace (`.orch/addons.json`), or turn it off. The core knows no add-on by name |
| `orch <addon> …` | Runs an active add-on as a subprocess; listed under **Add-ons** in `orch --help` |
| `orch update` | Reinstalls orch + all installed add-ons together from GitHub `main`, then refreshes the skills and AGENTS.md blocks in this project |
| `orch publish connect <url> --workspace ws_… --token orp_…` / `orch relay connect …` | What the admin prompts contain (publish-api.md, relay-api.md) |
| `orch ticket new "<title>"` / `list` / `show <id>` / `status <id> <status>` | Tickets. `done` is refused while a checked item lacks evidence |
| `orch ticket patch <id> --if-revision N '<json>'` | Atomic change of several fields; refused when the ticket's `revision` changed meanwhile. Every write adds 1 to `revision` |
| `orch check add <id> "<text>"` / `done <id> <c> --evidence '{"type":…,"ref":…}'` | Checklist; `done` without evidence is refused |
| `orch log <id> "<text>"` | History entry. `by` = `--by`, else the agent tool seen in the environment (`agent:claude-code`, `agent:codex`), else `human:<os user>` |
| `orch ask <id> "<q>" --option A --option B --recommend A [--phone]` / `answer <id> <q> "<a>"` | Questions; `--phone` also sends it to the phones via the relay |
| `orch link add <id> --type <t> --url <u>` / `orch ext set <id> <addon> '<json>' [--if-revision N]` | Links and add-on data (`ext.<addon>`, checked with the add-on's schema when it is active) |
| `orch wait <id> --until <time>` / `--on question:q1\|ticket:t_…\|external:<text>` / `--clear` | Sets `waiting_on` (`kind` time/question/ticket/external), status `waiting`. orch only records it; something wakes the ticket only if an add-on does (the scheduler wakes `time`) |
| `orch publish whoami` / `file <path> [--days N\|--permanent]` / `app <folder> [--days N\|--permanent]` / `list` / `restart` / `stop` / `delete` / `new` | publish-api.md |
| `orch relay inbox` / `done <m>` / `send <ws> "<text>" [--file f]` / `delegate` / `start` / `allow <m> --once\|--permanent` / `refresh` / `webhook new --once\|--permanent` / `whoami` (relay-api.md, local-files.md) | relay-api.md |

All commands accept `--json` for agents. Exit code 0 = ok, 2 = refused (stderr `Refused: <reason>`; with `--json` stdout `{"error": "<reason>"}`), 1 = bug. Add-ons follow the same rules.

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
Signing, approvals, planning gates, fixed requirements, claims/locking, durations, a GUI, a server.
