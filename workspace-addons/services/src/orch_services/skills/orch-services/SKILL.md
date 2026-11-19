---
name: orch-services
description: Use when a ticket needs something to keep running in the background (a web preview, a local server, a watcher, a bot), when the person asks what is running, or to start, stop, restart or read the log of such a job. Services are kept running by this computer's own service tool, under the person's own account. Not for one-off commands (run them yourself) and not for repeating a ticket at a time (that is automation).
---
# orch services

## When to use
- Something should keep running in the background for a ticket: a web preview, a local server, a watcher, a bot.
- The person asks what is running here, or wants a service started, stopped, restarted or its log read.
- Not for a one-off command (run it yourself) and not for repeating a ticket at a time (that is automation).

A service is a command that should keep running: orch writes one small record for it and hands it to this computer's
own service tool (on a Mac the login items list, on Linux the user's service manager, on Windows a task of the
person's own in Task Scheduler, no admin rights). It runs under the person's own
account, writes its output to a log file in this workspace and comes back after a crash. "Starts by itself" means it
also starts after the computer restarts. On Linux the first add or adopt also lets the person's services keep running
after they log out (their own account only, no admin rights) and says so in one line.

## Recipes

**Add a service** (stopped until you start it; `--start` starts it at once)

    orch services add "Web preview" --id web-preview --port 5173 --ticket <id> -- npm run dev -- --port 5173

The id is a short name in lowercase letters, digits and dashes. Everything after `--` is the command, word by word.
`--cwd <folder>` runs it in a folder of this workspace (default: the workspace folder). `--auto` makes it start by
itself.

**Share a folder by link** (a page, a report, drafts for someone to open in the browser)

    orch services share <folder> --ticket <id>

One command: it picks a free port of the shared range (one nothing else uses, also not a server on every address),
serves the folder read-only as a service on the ticket, checks the link and prints it. Give the person exactly the
printed link, never 127.0.0.1 or localhost. The same folder again prints the same link. When it is no longer needed:
`orch services remove <id>` (the id is in the output). Never start a web server for this by hand.
Not set up yet (it says so): the person sets `share_ports`, `share_name` (and `share_skip`, `share_check` where
needed) in the `[services]` table of `.orch/config.toml` once.

**See what runs**

    orch services list

**Start, stop, restart, starts by itself**

    orch services start <id>
    orch services stop <id>
    orch services restart <id>
    orch services auto <id> on      # or off

**Health check and a service that keeps stopping** (one pass, then it ends)

    orch services check

Each service is checked: its process is alive and, when it has a port, it answers on 127.0.0.1. When a service failed
3 times in 10 minutes (a failed check, or the computer started it again by itself) it is Failing, and orch asks ONE
question on the ticket that made it (a service without a ticket gets its own ticket "Services: <name> keeps
stopping"): Restart, Stop or Look into it, Restart recommended. Never a second question while that one is open; when
the service runs fine again for 10 minutes, orch takes the question back.
The person answers the question on the ticket. The next `check` reads the answer and acts on it once: Restart restarts
the service, Stop stops it, Look into it changes nothing and only notes it on the ticket (no new question until the
service runs fine again for 10 minutes and then fails again). `list --json` shows `health`, `failing` and the open
`question` on each service.

To check regularly, the person sets up a repeat once (do not set it up yourself; tell them these two lines):

    orch automation script add services-check -- orch services check
    orch automation repeat <ticket> "every 5 minutes" --script services-check

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
