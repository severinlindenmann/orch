# Add-ons

Add-ons give orch more. Each one is off until you turn it on, and works on its own. Without add-ons, orch shows no trace of them.

| Add-on | What it does |
|---|---|
| automation | Starts your agent at a time, on a repeat, or when the phone or another workspace sends work |
| focus | A live page for one ticket: watch the agent work, answer, send a message |
| dashboard | One page with every ticket and what needs you |
| publish | Share a file or a small app by private link ([publish.md](publish.md)) |
| relay | Messages and tasks between workspaces and phones ([relay.md](relay.md)) |

## Turn on and off

```sh
$ orch addon add automation --yes
$ orch addon list
$ orch addon remove automation
$ orch addon add automation --yes
```

`remove` turns it off here. Ticket data stays (hidden); `--purge` deletes it. Without `--yes` orch shows what the add-on brings and asks first.
Some add-ons run in the background: `orch start` starts them all, `orch stop` stops them, `orch status` shows what runs.

## Automation

It never starts an agent by itself: it calls `orch run start <id>`, so there is never a second agent on a ticket and your
agent settings apply ([agents.md](agents.md)).

```sh
$ orch addon add automation --yes
$ orch ticket new "Weekly report"
$ orch automation repeat <id> "every monday 08:00"
$ orch automation list
$ orch start
$ orch automation status
$ orch stop
$ orch automation repeat <id> --off
```

Phrases: `every <day> HH:MM`, `daily HH:MM`, `every N minutes`, `every N hours`, `monthly D HH:MM` (day 1-28), `today HH:MM`, `tomorrow HH:MM`.
Times use this computer's time zone; `--tz Europe/Zurich` changes it. `--each-run sub-ticket` (daily or slower) gives every run its own sub-ticket.
For one wake-up at a time, use `orch wait <id> --until <time>`. If the computer was off, one catch-up run happens.
If automation is not running, `orch needs` says so and `orch start` fixes it.

When the relay is connected, automation also reads the inbox: a text from your phone that names a ticket continues it,
and an allowed task from another workspace starts an agent on it.

## Focus

One ticket, live. You see its tasks and proof, the agent's steps, its questions, and a box to send it a message while it works.
Start and Stop on the page do the same as `orch run start` and `orch run stop`. Close the browser and the agent keeps working.

```sh
$ orch addon add focus --yes
$ orch start
$ orch focus open <id> --no-open
$ orch stop
```

Leave out `--no-open` and your browser opens. With Claude you also see each step as it happens. With a generic agent you see
the tasks it ticks off and its questions. When an agent waits for your OK, it shows as a card in Needs you.

## Write your own add-on

The core knows no add-on by name. An add-on is a folder with an `orch-addon.toml`
([contract](../contracts/addon-manifest.md)). Try it with `orch addon add ./my-addon`.

| Key | Meaning |
|---|---|
| `name`, `version`, `description` | Its command `orch <name>`, and one plain sentence shown in `orch addon list` |
| `run`, `skill`, `agents_block` | The code, and the skill text agents read |
| `ticket_ext` | Schema for the data it keeps on tickets (`ext.<name>`) |
| `[[ticket_links]]` | Reference types it knows (label, icon, address pattern, statuses): matching references get its name, icon and status |
| `[ticket_fields]` | Fields under the ticket's Details (section, schema, `show_on_card`), edited in place or with `orch ticket set` |
| `[acts.refresh]` | A Refresh that updates its references' title and status: `orch <name> act refresh -- <ticket>` |
| `background = true` | It has a long-running process: `orch <name> start\|stop\|status --json` |
| `needs = true` | `orch <name> needs --json` adds rows to `orch needs` |
| `runs_agents = true` | It starts agent runs, only through `orch run start` |
| `requires` | Add-ons that must be on first |
| `[dashboard]`, `[[ticket_view]]` | A dashboard tab, and rows on the ticket page |
| `[page]` | A page of its own on this computer |

**Rows that open.** A list in a dashboard tab can have rows that open to show more: detail lines, tickets, one switch, and up to
four buttons. A button asks the add-on to do one named thing for a ticket (`orch <name> act <verb> <ticket>`), with an optional "Are you sure?" text. The
dashboard never runs add-on code and shows add-on text as plain text only.

An add-on is code that runs on this computer with your rights. Add only what you trust.
