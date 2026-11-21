# Add-ons

Add-ons give orch more. Each one is off until you turn it on, and works on its own. Without add-ons, orch shows no trace of them.

publish and relay are built into orch (no separate package) but are also off until you turn them on; orch works fully without them. The others are separate packages under `workspace-addons/`.

| Add-on | What it does |
|---|---|
| automation | Starts your agent at a time, on a repeat, or when the phone or another workspace sends work |
| focus | The live page of every helper session, in the dashboard: watch it work, answer, send a message |
| dashboard | One page with every ticket and what needs you |
| dashboard-tester | Looks at every dashboard page once a day and reports what is broken, without clicking anything |
| publish (built in) | Share a file or a small app by private link ([publish.md](publish.md)) |
| relay (built in) | Messages and tasks between workspaces and phones ([relay.md](relay.md)) |

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

The live page of every helper session, drawn by the dashboard (turn the dashboard on too). You see each session, the agent's
steps, its questions, and a box to send it a message while it works. Start and Stop on the page do the same as
`orch run start` and `orch run stop`. Close the browser and the agent keeps working. The Focus add-on itself has no page
or server: it only opens the right place in the dashboard and tells Needs you when a helper waits for your OK.

```sh
$ orch addon add focus --yes
$ orch addon add dashboard --yes
$ orch start
$ orch focus open <id> --no-open
$ orch stop
```

`orch focus open <id>` prints the dashboard address of that ticket's session (`#addon/focus/t/<id>`). Leave out `--no-open`
and your browser opens it. When an agent waits for your OK, it shows as a card in Needs you.

## Dashboard tester

Once a day a program opens every dashboard page at 1280, 1920 and 390 px wide (plus the newest working and the
newest Review ticket) and reads it. It never clicks, types or presses anything. It finds page errors, failed
requests, empty or slow pages (over 6 seconds), sideways scrolling at phone width, buttons cut off at the right
edge, words from the never-list of [wording.md](wording.md) and program values such as null or NaN on screen.

New findings become problem reports kept on this computer (`orch report problem --no-send`, never shared): each
big one alone, the small ones together, at most 3 a day. A finding that an open ticket already names is not
reported. When the ticket of a report is finished, the next look checks the finding again and reports it once more
if it is still there. A quiet day costs no tokens. It needs the dashboard and automation add-ons, and downloads a
browser of about 100 MB once (not when Chrome is already on this computer).

```sh
$ orch addon add dashboard --yes
$ orch addon add dashboard-tester --yes
$ orch dashboard-tester setup --at 06:30  # skip
$ orch dashboard-tester status
$ orch dashboard-tester run --dry-run  # skip
```

`setup` makes a ticket with a daily repeat (default 06:30); it runs once a person presses Allow this script on the
repeat. `status` says what the last look found; `run --dry-run` looks once and reports and keeps nothing.
The look signs in with a one-time link that orch makes only for a run a person started (the daily repeat), never
for a helper. `--helper-each-release` on `setup` also starts one helper per new orch release (low priority, the
small model) that reads the pictures and page texts of the look and reports what a person would stumble over.
Files: `.orch/addons/dashboard-tester/` (gitignored; the newest pictures and texts in `last/`).

## Lessons

Helpers write down what they learned in this workspace, one plain line each (for example "Run the web tests with
npm run test:web"). Every later helper reads the newest lessons at its start (at most 3 KB). You see, edit or delete
them in one list (Settings, Add-ons, Lessons). Lessons stay on this computer: they are not synced or sent anywhere.

```sh
$ orch addon add lessons --yes
$ orch lessons add "Run the web tests with npm run test:web" --ticket <id>
$ orch lessons list
$ orch lessons edit <id> "<new text>"
$ orch lessons rm <id>
```

A secret in the text is refused. When the lessons are over 3 KB, helpers see only the newest; the helper merges or
removes old ones itself. Files: `.orch/addons/lessons/` (gitignored).

## Pull requests (merge queue)

When many pull requests are ready at once, merging them one by one makes each later one take the base branch in and
run its checks again. The merge queue puts them in line instead: up to five of one repository go on one group branch,
the checks run once, and they are merged together on green. A red group is split in halves and tried again, so the
good ones still get merged. A program does the waiting and merging; it needs `gh` signed in and git 2.38 or newer.

```sh
$ orch addon add pull-requests --yes
$ orch pull-requests queue add <pull request url> --ticket <id>          # in line; the verdict goes on the ticket
$ orch pull-requests queue add <pull request url> --ticket <id> --wait   # the same, and wait: exit 0 = merged
$ orch pull-requests queue list
$ orch pull-requests queue remove <pull request url>
```

`queue add` starts the runner in the background; it stops when the queue is empty. A helper does not wait: it puts
its ready pull request in line and finishes; the verdict (merged, or why it left the queue) goes on the ticket, and
when it left the queue the ticket's helper is woken with the reason. A
pull request whose files changed on the base branch since it took the base in is checked once on top of the base
branch; the queue never merges the base into it and runs its checks again. Every GitHub write counts toward this
computer's write limit (`orch github writes`); the queue's own merges are counted but never wait for the hourly
merge count, since it merges one group per run of the checks. A pull request a person merges with a Merge card is never queued.
Files: `.orch/addons/pull-requests/` (gitignored).

**Merge when green.** A switch on each ticket (Details, Pull requests; off until you turn it on). When it is on, the
ticket's open pull requests go into the merge queue by themselves once they are ready (not a draft), and are merged
when every check passed, only the commit that was checked. No helper has to wait for it. `orch start` runs the
watcher that looks every minute.

```sh
$ orch ticket set <id> pull-requests.merge_when_green on
$ orch start
$ orch ticket set <id> pull-requests.merge_when_green off   # a waiting pull request leaves the queue
```

One that left the queue (checks failed, a conflict) comes back with the next push. Never a draft, never a pull request
a person merges with a Merge card.

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

## Restart after `orch update`

`orch update` restarts the background services that were running (dashboard, automation) so they run the
new code. A restarted service gets the environment of the terminal that ran the update, with two exceptions: `HOME`
is the current user's home from the password database, and `ORCH_HOME` is the orch folder in use. Nothing the
service recorded when it started is replayed. If you run the update under a different home on purpose (for
example `sudo -E`, or in a container where the password database has no entry for your user), the service
gets your terminal's `HOME` instead and the update says so; if a service then misbehaves, run `orch stop` and
`orch start` in the shell you want it to use.

