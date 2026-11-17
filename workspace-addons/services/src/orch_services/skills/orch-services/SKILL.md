---
name: orch-services
description: Use when a ticket needs something to keep running in the background (a web preview, a local server, a watcher, a bot), when the person asks what is running, or to start, stop, restart or read the log of such a job. Services are kept running by this computer's own service tool, under the person's own account. Not for one-off commands (run them yourself) and not for repeating a ticket at a time (that is automation).
---
# orch services

A service is a command that should keep running: orch writes one small record for it and hands it to this computer's
own service tool (on a Mac the login items list, on Linux the user's service manager). It runs under the person's own
account, writes its output to a log file in this workspace and comes back after a crash. "Starts by itself" means it
also starts after the computer restarts.

## Recipes

**Add a service** (stopped until you start it; `--start` starts it at once)

    orch services add "Web preview" --id web-preview --port 5173 --ticket <id> -- npm run dev -- --port 5173

The id is a short name in lowercase letters, digits and dashes. Everything after `--` is the command, word by word.
`--cwd <folder>` runs it in a folder of this workspace (default: the workspace folder). `--auto` makes it start by
itself.

**See what runs**

    orch services list

**Start, stop, restart, starts by itself**

    orch services start <id>
    orch services stop <id>
    orch services restart <id>
    orch services auto <id> on      # or off

**Read the log** (the last 20 lines; secrets are shown as ••••••)

    orch services log <id> --lines 50

**Remove** (stops it and takes it out of the computer's service list; the log file stays)

    orch services remove <id>

**Found on this computer** (jobs of the person's account that orch did not make; only reads, changes nothing)

    orch services found

**Manage with orch** (only after the person chose it for that job; nothing is moved, rewritten or restarted)

    orch services adopt launchd:com.example.web --name "Web preview" --ticket <id>

From then on start, stop, restart, auto and log work on it by its new id. `remove` on it only forgets it; the job
stays as it is. A plain program (`process:<pid>`) cannot be taken over: stop it and add it with `orch services add`.
On a Mac without `lsof`, programs running in the workspace folder cannot be found (only login jobs are listed).

Every command takes `--json`.

## Rules
- Only for jobs that must keep running. A command that finishes by itself is not a service.
- Never put a secret into the command: use `orch secret exec` inside the command instead.
- Always the person's own account: never sudo, never a system-wide service.
- Say the service by its name to the person, not by its id.
- orch shows found services; it changes one only after the person chooses Manage with orch.
