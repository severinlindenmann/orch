# orch-workspace-addons (dashboard, scheduler)

## What it does
**Dashboard:** a light, read-only web page on the laptop that shows the ticket files. No buttons that change data.
Optional: a read-only snapshot published as a private publish app.
**Scheduler:** starts agent runs: once at `wake_at`, recurring by cron, and when the relay inbox brings work.

## Tech stack
Python 3.12, uv, depends on `orch-workspace` (ticket code). Dashboard: stdlib `http.server` + plain HTML/CSS/JS
(orch core `tokens.css` and orbit logo copied; no React, no build step). Scheduler: `croniter`, `subprocess`.

## Folder layout
```
workspace-addons/
  dashboard/  pyproject.toml (adds `orch dashboard` via entry point)  src/orch_dashboard/{server.py, snapshot.py, web/}  skills/orch-dashboard/  tests/
  scheduler/  pyproject.toml (adds `orch scheduler` via entry point)  src/orch_scheduler/{loop.py, runner.py, service.py}  skills/orch-scheduler/  tests/
```
`orch addon add dashboard|scheduler` installs the package from `workspace-addons/<name>` into the orch tool env and adds its skill + AGENTS.md block to the project.

## Commands
| Command | Does |
|---|---|
| `orch dashboard` | Serves `127.0.0.1:8420`: ticket list (active, waiting, open, done), ticket detail, scheduler view, inbox view. Reads `.orch/` on every request |
| `orch dashboard snapshot --publish` | Renders the same pages as static HTML and runs `orch publish app` (static, private) → link with view token |
| `orch scheduler run` | Loop every 60 s (below). `--once` for one pass |
| `orch scheduler start` / `stop` | Starts at login: launchd (macOS), systemd user unit (Linux), Task Scheduler at logon (Windows) |
| `orch scheduler list` | Next wake-ups and recurring runs, in plain words |

Scheduler pass:
1. Ticket with `wake_at <= now` and status not done/dropped → run agent, clear `wake_at`.
2. `type: recurring` with `ext.scheduler.cron` due (5-field, UTC) → run agent. Runs missed while the machine was off → one catch-up run, not several.
3. `orch relay inbox --json` (if relay is set up). Run agent for: `start`/`delegate` with a valid allow (delegate first becomes a new ticket);
   `answer` or `webhook` for a ticket that is `waiting` on it. Everything else waits for the next agent session.
4. Run = `config.toml` agent command with prompt `Continue orch ticket <id>. Read .agents/skills/orch/SKILL.md first.`;
   one run per ticket at a time; output to `.orch/scheduler/logs/`; history entry `by: agent:scheduler`.
An agent that is already working runs `orch relay inbox` itself; the seen-list stops double work.

## Data storage
Reads `.orch/tickets/`, `.orch/inbox/`. Writes only `.orch/scheduler/` and the ticket fields above. Dashboard writes nothing.

## Tests
- T0: `uv run pytest tests/test_loop.py -k cron -x -q` (scheduler), `uv run pytest tests/test_pages.py -x -q` (dashboard).
- Scheduler tests use a fake clock, a fake relay and a fake agent command (`python -c …` that writes a file).
- Dashboard: page tests on HTML; Playwright click-through in e2e. CI: `workspace-addons/**`, `workspace/**`, `contracts/**`.

## Install
`orch addon add dashboard` / `orch addon add scheduler` in the project (needs orch installed, see workspace.md). `orch update` updates them too.

## Not included
Editing in the dashboard, login, multi-workspace dashboard, run limits or budgets, retries beyond the next pass.
