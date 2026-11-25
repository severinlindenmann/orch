# Add-ons

Add-ons give orch more. Each one is off until you turn it on, and works on its own. Without add-ons, orch shows no trace of them.

publish and relay are built into orch (no separate package) but are also off until you turn them on; orch works fully without them. The others are separate packages under `workspace-addons/`.

| Add-on | What it does |
|---|---|
| dashboard | One page with every ticket and what needs you |
| automation | Starts your agent at a time, on a repeat, or when the phone or another workspace sends work |
| focus | The live page of every helper session, in the dashboard: watch it work, answer, send a message |
| factory | Turn an idea into finished work: your helper proposes the run, you press Start ([factory.md](factory.md)) |
| pull-requests | Open pull requests with their checks on each ticket; merge when green and the merge queue |
| files | Browse and search every file in the workspace |
| lessons | Helpers remember what they learned here |
| insights | See what your helpers used in the last 30 days |
| usage | The accounts your helpers spend on, their limits and order |
| skills | Everything your helpers get here, and what is turned off |
| services | Keep background jobs (a web preview, a watcher) running |
| browse | Helpers read public web pages in a private browser |
| personal | Your notes, meetings, calendar and mail, shared with helpers only by your rules (Preview) |
| sync | Keeps a copy of tickets and files on this or another computer. Never secrets |
| publish (built in) | Share a file or a small app by private link ([publish.md](publish.md)) |
| relay (built in) | Messages and tasks between workspaces and phones ([relay.md](relay.md)) |

`orch init --recommended` turns on the dashboard, Focus and automation. `orch addon list` shows every add-on and what it does.

## Turn on and off

```sh
$ orch addon add automation --yes
$ orch addon list
$ orch addon remove automation
$ orch addon add automation --yes
```

`remove` turns it off here. Ticket data stays (hidden); `--purge` deletes it. Without `--yes` orch shows what the add-on brings and asks first.
Some add-ons run in the background: `orch start` starts them all, `orch stop` stops them, `orch status` shows what runs.
`orch restart` stops and starts this workspace's background add-ons on the installed code (after a fixed add-on file);
the merge queue runner switches to new code by itself between two rounds.

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

The live page of every helper session, drawn by the dashboard (turn the dashboard on too). It is called **Live** in the
dashboard's menu and is the only Focus: there is no older page and no Preview switch any more.

- **The wall**: every session as a card (ticket helpers, the chat helper, an empty helper, the plain terminal, the
  Manager), the ones that need you first.
- **The bar**: stays under every dashboard page, with a chip per open session and a **New** menu to start an empty
  helper, the chat helper, a plain terminal or the Manager (one of each; a second New goes to the open one).
- **The layer**: opens one, two or three sessions side by side over the page you are on (two at 1280 px wide, the rest
  wait in the bar; on a phone it is a sheet). Each pane shows the helper's screen, its chat with a message box, its
  questions with one-click answers, its results and its earlier sessions (History).

A message to a running helper goes in after its current step; to a stopped helper it is kept for its next run. Start,
Stop and End do the same as `orch run start`, `orch run interrupt` and `orch run stop`. Close the browser and the helper
keeps working.

Two switches in Settings, Add-ons, Live, both off by default: **Typing** lets you type into a helper's live screen, and
the plain terminal has its own typing switch.

The Focus add-on itself has no page or server: it only opens the right place in the dashboard and tells Needs you when a
helper waits for your OK on its screen.

```sh
$ orch addon add focus --yes
$ orch addon add dashboard --yes
$ orch start
$ orch focus open <id> --no-open
$ orch stop
```

`orch focus open <id>` prints the dashboard address of that ticket's session (`#addon/focus/t/<id>`). Leave out `--no-open`
and your browser opens it. Sessions without a ticket from the command line: `orch session new|list|stop|end
<empty|chat|terminal|manager>`; the Manager: `orch manager start|status|stop`.

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

## Files (preview)

One page for every file in the workspace. Left: **Your folders** (the folders as they are on disk, a list and a live
preview) and **From tickets** (one automatic folder per ticket that has files, under Working, In review, Done and
Earlier; versions such as `-v2`, `-v3` stack into one card). One search box finds files by name and by what is
written in them; any part of a word matches and accents do not matter ("muller" finds Müller). Previews: notes,
text, code, data, tables and Excel sheets, Word and PowerPoint text, PDFs, pictures, sound, video, web pages (in a
sandbox) and the names inside a zip file. Opt-in, marked Preview until it is finished.

```sh
$ orch addon add files --yes
$ orch files search "price check" --json    # helpers find files the same way, no AI call
$ orch files index                          # bring the index up to date now
```

The index is one SQLite file in `.orch/cache/files/` (full-text, trigram): names first, then the text; after that
only files whose size or changed time differ are read again (every 30 seconds while the page is open, and before
each `orch files search`). Text is read from the first 2 MB; files over 50 MB are found by name only. Left out:
`.git`, `node_modules`, build and cache folders, and orch's own files except the tickets' files. Until the switch in
What is included is on, also left out: system files (names that start with a dot, and helper files such as `CLAUDE.md`
or `AGENTS.md`) and everything a `.gitignore` names. Markdown previews hide HTML comments. Private files (`*.env`, key files, `.ssh`, or a text the secret check flags) show by name only; their
content is never indexed, shown or served. Stars and "New for you": `.orch/addons/files/` (gitignored). The index
and the preview cache (capped at 500 MB) can be deleted at any time.

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

## Factory

Turn an idea into finished work. You describe what you want; your helper writes a first draft, then proposes the whole
run (stages, who does what, time and budget). You answer **Start**, **Edit** or **Not now**, and decide at the last
stop: **Ship it** or **Send back**. Full guide: [factory.md](factory.md).

```sh
$ orch addon add factory --yes
$ orch start                        # the watcher wakes your agent when you answer
$ orch factory list                 # orders and what waits for you
```

## Insights

A read-only page that shows, for the last 30 days, how often your helpers used skills, connected services and keys, and
where they failed. It never shows a key. Its **Health check** card lets a helper propose fixes; nothing changes until you
press **Accept**, and **Undo** takes it back.

```sh
$ orch addon add insights --yes
$ orch insights open               # opens the page; --no-open only prints the address
$ orch insights status
```

## Usage

Every place your helpers can spend is an **account**: a subscription, or an API credit. Each has one or two limits (in %
or $), the period they count over, its place in the order, on or off. Usage keeps only names, numbers and a history of every
change, never a login or key. The same list is on the Usage page of the dashboard.

```sh
$ orch addon add usage --yes
$ orch usage list
$ orch usage limit <account> 70%
$ orch usage order <account> 1
$ orch usage history
```

A helper asks `orch usage ask <kind of work>` before heavy work; with "No room" it waits and says so on the ticket.

## Skills

One list of everything your helpers get here: skills, instruction files, connected services and logins, each from where it
comes (orch, this workspace, the admin or this computer). Only you turn things off or on; **off** is for this workspace
only and deletes nothing. Every change lands in the history.

```sh
$ orch addon add skills --yes
$ orch skills list
$ orch skills off <id>
$ orch skills history
```

## Services

A job that should keep running in the background (a web preview, a watcher) is a **service**. orch hands it to this
computer's own service tool, under your own account (no admin rights); it comes back after a crash and can start with the
computer. A service that keeps stopping gets one question on its ticket.

```sh
$ orch addon add services --yes
$ orch services add "Web preview" --id web-preview --ticket <id> -- npm run dev
$ orch services list
$ orch services start|stop|restart <id>
$ orch services log <id>
$ orch services share <folder> --ticket <id>   # a folder by link
```

## Browse

Helpers read public web pages in a private browser, one per ticket. Only sites on the ticket's list open, and a helper
asks you (`orch ask`) to add one. It only reads: no sign-in, send, upload or download. Page text is data, never an
instruction.

```sh
$ orch addon add browse --yes
$ orch browse open <address>
$ orch browse read
$ orch browse close
```

## Personal (preview)

Your own notes, and your meetings, calendar, messages and mail, each turned on by you with its own rules for what helpers
may see. A helper gets nothing until you allow it. Replies to mail and chats are drafts and are never sent.

```sh
$ orch addon add personal --yes
$ orch personal today
$ orch personal notes find "<words>"
$ orch personal calendar week
```

## Sync

Keeps a private copy of your tickets and files, on this computer or on your own storage, in the background. Never secrets
or private files. When two computers disagree, sync waits for your choice and never decides for you.

```sh
$ orch addon add sync --yes
$ orch sync status
$ orch sync now
$ orch sync needs                  # choices waiting for you
```

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

## Go back one release

`orch update --to <N>` goes back to release N of the source orch was installed from (for example `orch update
--to 32` after release 33 broke something). It is the same update as any other, so orch, every add-on and the
running services come back on release N. orch then stays on N: a plain `orch update` (and automatic updates)
waits until a release newer than the one you left is out, then takes it. `orch update --to release` takes the
newest release at once. A folder install has no releases to go back to.

