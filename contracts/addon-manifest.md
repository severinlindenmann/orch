# Add-ons: manifest, activation, CLI, views (`orch_api = 1`)

The core knows no add-on by name. An add-on is a Python package with an `orch-addon.toml`. Once it is turned on in a
workspace it looks and works like part of orch: same commands style, same `--json` and errors, same config file,
same skill tone, a dashboard tab that cannot be told apart from a built-in one.
Schemas: `addon-manifest.schema.json`, `addon-view.schema.json`, add-on schemas in `addons/` (`addons/scheduler.ext.schema.json`,
`addons/automation/ext.schema.json`, `addons/focus/run-event.schema.json`); add-on question kinds: `addons/question-kinds.md`.
Examples: `review/scheduler.orch-addon.toml`, `review/scheduler.view.example.json`, `examples/addon-*/`.

## Manifest `orch-addon.toml`

Lives inside the add-on's top-level Python package, next to `__init__.py`
(`workspace-addons/scheduler/src/orch_scheduler/orch-addon.toml`). The package registers itself in the entry-point group
`orch.addons` as `<name> = "<module>"` (module only). The core finds the file with `importlib.util.find_spec(<module>)`
(top-level, so nothing is imported) and **never runs add-on code to discover it**.

| Key | Meaning |
|---|---|
| `schema = "orch.addon/1"`, `orch_api = 1` | Manifest format and add-on contract version. Other values: refused |
| `name` | `[a-z][a-z0-9-]{1,31}`, not a core command (`ticket`, `addon`, `relay`, `publish`, `init`, `update`, `config`, `start`, `stop`, `status`, … see schema). Unique in the tool env. `publish` and `relay` are built-in add-ons shipped inside the orch package (`orch/builtin/<name>/orch-addon.toml`): off until `orch addon add publish|relay`, no other add-on may take these names |
| `version`, `description` | `x.y.z`; one plain sentence (shown in `orch addon list` and `orch --help`) |
| `run` | Top-level module. `orch <name> <args>` = subprocess `<orch's python> -m <run> <args>` |
| `skill` | Folder with `SKILL.md` → copied to `.agents/skills/orch-<name>/` |
| `agents_block` | block body for .orch/harness/AGENTS.orch.md (default `<skill>/AGENTS-block.md`) |
| `ticket_ext` | Local JSON Schema for `ext.<name>` (no remote `$ref`, ≤ 32 KB) |
| `background` | `true` = has a long-running process; must implement `orch <name> start\|stop\|status --json` (Background, below) |
| `[dashboard]` | `label` (≤ 16 chars), `icon` (fixed set in the schema), `order`: the add-on has a tab filled by `orch <name> view --json` |
| `[[ticket_view]]` | Ticket detail rows from `ext.<name>`: `field`, `label`, `format` = `text` · `time` · `cron-human` · `chips` · `yes-no` · `open-page` (an "Open" button to `[page]` `path` + `/` + the value; needs `[page]`) |
| `recommended` | `true` = `orch init --recommended` turns it on (the core names no add-on; it reads this key) |
| `gitignore` | Lines kept out of git (own block of `.git/info/exclude`, never the team `.gitignore`), added by `orch addon add`, removed by `orch addon remove`: relative paths inside the workspace, no leading `/`, no `..`, no `\`, no drive letter |
| `runs_agents` | `true` = the add-on starts agent runs; it does so only through `orch run start` (one claim per ticket, the workspace's agent) |
| `requires` | Add-on names that must be active first; `orch addon add` refuses and names the missing ones (nothing is turned on by itself) |
| `needs` | `true` = implements `orch <name> needs --json` → rows of `needs.schema.json` for `orch needs` (only rows that are not ticket questions: those come from the tickets) |
| `[page]` | `path` (starts with `/`), optional `label`: the add-on serves its own local page; needs `background = true`. Its base url is the checked `url` from `orch <name> status --json` (`http://127.0.0.1:<port>`) |
| `[[ticket_links]]` | Link types the add-on knows: `kind` (`[a-z0-9-]`, not `link`), `label` (≤ 24), `icon` (a key), `match` (one or a list of `https://` patterns; `*` = one part of the address, a `*` at the end takes the rest), optional `statuses`, `preview = "thumb"`. Ticket links, below |
| `[ticket_fields]` | `section` (heading under the ticket's Details), `schema` (JSON Schema of `ext.<name>`; the same file as `ticket_ext` when both are set), `show_on_card` (≤ 3 field keys shown as a chip on board cards). Ticket links, below |
| `[acts.<verb>]` | What `orch <name> act <verb> [--by X] --json -- <ticket>` offers: `summary`, `who` (`anyone` · `people`), `writes` (`links`, `ext.<name>`). Core knows `refresh` (Act: refresh, below) |

All paths are relative to the manifest's folder and must stay inside it (no `..`, no absolute paths, no symlink leaving it).

## Install and activation

Two steps, one command for the user:

1. **Install** (per machine): the package goes into the orch uv tool env. Sources in the prototype:
   - built-in name: `orch addon add scheduler` → `workspace-addons/<name>` of the orch repo (same `ORCH_REPO`/`ORCH_REF` as orch itself);
   - local folder: `orch addon add ./my-addon` (a folder with `pyproject.toml`) → labelled "local (not checked by orch)" everywhere.
   Git URLs come later (with consent and pinning). Before installing, the CLI shows what the add-on brings (commands, skill and
   AGENTS text, ext key, dashboard tab, background process) and asks; `--yes` skips the question.
   Installed list: `~/.orch-tool/addons.json` `[{"name", "source", "version"}]`.
2. **Activate** (per workspace) — **the single switch**: `.orch/addons.json`
   `{"active": {"<name>": {"version": "0.2.0", "activated_at": "…Z"}}}`, written only by `orch addon add|remove`, **and** the
   consent record of this machine (below). A listing in `addons.json` alone (it arrives with a git clone) is only a wish.
   Only an active add-on gets: its `orch <name>` command in this workspace, its skill + AGENTS block, its dashboard tab and
   ticket-detail rows, its background process. Leftover files, `.orch/addons/<name>/` or `ext.<name>` data **never** activate anything. A command of an add-on that is
only listed answers `Add-on <name> is listed for this workspace but not turned on here. Turn it on: orch addon add <name>`.

**Consent record.** `orch addon add` writes `consent.json` in the user's orch folder (`~/.orch-tool/`, from the account
database, not `$HOME`): `[{"workspace_id", "workspace", "name", "source": "built-in"|"local", "path"?, "hash"?}]`. A local folder
is bound by a content hash: change one byte of it and the add-on is inactive ("changed on disk": `orch update` says so) until the
user runs `orch addon add <folder>` again. `workspace_id` is a random id in the gitignored `.orch/.local-id` (created by the first
`add`); a clone or a copy has none, so it has no consent. `ORCH_HOME` moves the orch folder only when it is a plain folder under
the real home, outside the current folder and the workspace, with no `.orch`, `.agents` or `.git` in it or above it up to home;
otherwise it is ignored with a note on stderr (a repo's `.envrc` cannot aim consent at a place it controls). `remove` drops the
record. The installed list (`addons.json` in the same folder) is the registry of what the machine installed through orch.

`orch addon add <name|path>` = install (if needed) + activate. `orch addon remove <name>` (this workspace):
1. `orch <name> stop` if `background = true` (the process also exits by itself when it sees it is no longer active);
2. removes `.orch/harness/skills/orch-<name>/` and its links (exactly that folder, never `orch-<name>-x`, which may belong to another add-on or the
   user) and its block in `.orch/harness/AGENTS.orch.md`;
3. drops it from `.orch/addons.json` → tab and ticket rows disappear;
4. keeps `ext.<name>` in tickets (hidden, never validated, never blocks ticket access) and `.orch/addons/<name>/`;
   `--purge` also deletes `.orch/addons/<name>/` and the `[<name>]` table of `.orch/config.toml`.
The package stays in the tool env (other workspaces may use it); `orch addon uninstall <name>` removes it from the machine.

`orch addon list --json`: a JSON list with one entry per installed add-on (active or not), sorted by name:
`[{"name", "version", "description", "source": "built-in"|"local", "active": bool,
"dashboard": {label, icon, order} | null, "ticket_view": [{field, label, format}], "background": bool}]` — the one source the
dashboard uses (it shows the entries with `active: true`).

`orch update` updates orch **and every installed add-on together** (one `uv tool install --reinstall` with all of them),
then refreshes skills and AGENTS blocks of the active add-ons in this workspace. Add-ons never update on their own.

## CLI contract (core and add-ons, same rules)

- `orch <name> …` runs the add-on as a subprocess in the workspace root, env `ORCH_ADDON=<name>`, `ORCH_ROOT=<root>`,
  `ORCH_BIN=<path of orch>`. Not active here → refused: `The scheduler add-on is not turned on in this workspace. Turn it on: orch addon add scheduler`.
- `orch --help` lists active add-ons in a group **Add-ons** (name + description), right under the core commands.
- Every command takes `--json`. Exit `0` = ok, stdout = one JSON value. Exit `2` = refused: stderr `Refused: <plain words>`,
  with `--json` stdout `{"error": "<plain words>"}`. Exit `1` = bug (traceback allowed on stderr). Same as the core.
- Add-ons change tickets only through the public CLI (`$ORCH_BIN … --json`), never by writing ticket files:
  `orch ext set <id> <name> '<json>' [--if-revision N]` (checked with the add-on's `ticket_ext` schema),
  `orch ticket patch <id> --if-revision N '<json>'` (atomic; refused when `revision` changed), `orch log`, `orch wait`, `orch ticket list --json`.
  An add-on writes only `ext.<name>`, `.orch/addons/<name>/`, and the history entries it logs (`by: agent:<name>`).
- Config: one file `.orch/config.toml`; the add-on reads only its own table `[<name>]` (and `[<name>.*]`). Defaults live in the add-on.
- Required subcommands: `view --json` if `[dashboard]`; `start`, `stop`, `status` (all with `--json`) if `background`.

## Background (`orch start`, `orch stop`, `orch status`)

An active add-on with `background = true` runs one process per workspace, started and stopped by its own commands:
- `orch <name> start --json` → starts it detached (or finds it running), exit 0, stdout `{"running": true, "pid": N, "url"?: "http://127.0.0.1:P"}`;
  refused → exit 2 with `{"error"}`. Must return within 60 s.
- `orch <name> stop --json` → `{"stopped": bool}` (false = was not running). `status --json` → `{"running": bool, "pid"?, "url"?}`, exit 1 when not running.
- `orch start` (core, in a workspace) calls `start` on every active background add-on, prints one line per add-on (its `url`, or
  `running (pid N)`), opens the first `url` in the browser when run in a terminal (`--no-open`), and records each in
  `running.json` in the user's orch folder: `[{"workspace", "name", "addon", "pid", "url"?, "started_at"}]`.
  Entries whose pid is gone are dropped whenever the file is read.
- `orch stop`: in a workspace → that workspace; outside one (or `--pick`) → the running workspaces as a numbered list, the user
  picks a number or `all`; `orch stop <path|name>` / `--all` without asking. It calls `stop` on each active background add-on there.
  An add-on that is no longer on there is never run; its process ends by itself.
- `orch status [--json]`: `running.json` grouped by workspace `[{"workspace", "name", "addons": [{"addon", "pid", "url"?}]}]`.
- Runtime files of the background process (pid, port, nonce, log) live in `.orch/run/<name>/` (gitignored, 0700). A repo can
  still force-add files there, so an add-on never trusts them alone: no symlinks are followed (`.orch/run` or the folder being a
  symlink is refused; reads with `O_NOFOLLOW`, writes as a new file + rename), a pid counts only when it is > 1, and before any
  signal the add-on checks the process is its own: the start time of that pid equals the recorded one and, on POSIX, its
  command line is `-m orch_<name> … --dir <root>`; the dashboard also asks `GET /ready?c=<challenge>` and needs the pid and
  HMAC-SHA256(nonce, challenge) back (the nonce itself is never served). Not verified → nothing is
  signalled; `stop` says so (`{"stopped": false, "note"}`), and the stale file is replaced on the next `start`.
- The core prints or opens only `url`s of the form `http://127.0.0.1:<port>` / `http://localhost:<port>`, ignores pids ≤ 1, and
  strips control characters from add-on errors.
Add-ons without `background` are ignored by all three. The core never starts anything at login.

## Core commands an add-on may rely on (`--json`)

- `orch run start <ticket> [--mode live|oneshot] [--fresh] [--by <name>]`, `orch run send|stop|status <ticket>`: the only way
  to start or talk to an agent run (run.schema.json, run-pending.schema.json). A busy ticket queues the input; it is never refused.
- `orch needs --json`: rows of `needs.schema.json` (core rows + the pulled rows of active add-ons with `needs = true`).
- Questions: `orch ask <ticket> "<text>" --kind <name>:<what> [--option …] --json` adds a question whose `kind` the add-on
  owns, with an opaque `action` object (`--action '<json>'`); the add-on acts on answered questions of its own prefix. `via` is a free short word.

- `orch ticket list --json`: a plain JSON list of ticket objects (`ticket.schema.json`, with `revision` and `ext`); done and dropped tickets only with `--all` (or `--status <s>`).
  `orch ticket show <id> --json`: one ticket; `ext.<name>` is left out for add-ons that are not active.
- `orch addon list --json`: above. `orch relay status --json`: `{"configured": false}` or
  `{"configured": true, "url", "workspace"}`; it never touches the network (the dashboard shows Inbox when `configured`).
- Errors with `--json` on stdout: `{"error": "<plain words>"}`, exit 2.

## Act (the buttons and switches of a dashboard tab)

A view action `{"op": "addon.act", "args": {"verb", "target"}}` becomes one generic call. An add-on that has such actions
**must** have this subcommand, with exactly these arguments (the dashboard sends nothing else):

`orch <name> act <verb> --by <actor> --json -- <ticket id>`

- `--by <actor>` is required to be accepted: the person who pressed the button (`human:<user>`). The add-on records it on every
  `orch` call it makes for this action (`orch ext set … --by <actor>`, `orch run start … --by <actor>`, `orch log … --by <actor>`).
  Without `--by` it uses its own actor (`agent:<name>`).
- `--json` is accepted too. Exit codes and error text are the CLI contract above (`2` = refused, `{"error": "<plain words>"}`).
- The dashboard has tests that run `addon.act` against the real `automation` add-on, so a mismatch fails the build.

## Views (dashboard tab)

The dashboard (itself an optional add-on, the host) never imports add-on code. For each active add-on with `[dashboard]` it
**pulls** `orch <name> view --json` (timeout 2 s, max 256 KB stdout, validated with `addon-view.schema.json`):
- ok → render blocks, header "as of HH:MM" from `generated_at`, optional `notice`;
- timeout / error / invalid → keep the last good result (in memory) with a "not up to date" state, or the error state if none.
`view` must be read-only, fast, and must not start a background process. Blocks: `stat`, `list`, `calendar` (days strip; a repeat
more often than hourly is one item per day with `every` ("Every 5 min", shown instead of the time) and a muted `note`),
`timeline`, `chips`, `table` (typed columns text/number/duration/date/tone). Items may have a `link`: a ticket id (opens the
ticket), an `https://` URL (new tab), or `addon:<path>` — a page of **this** add-on: the dashboard resolves it only against
the same add-on's checked `[page]` url (`http://127.0.0.1:<port>/<path>`); no `..`, no leading `/`, never another add-on or
host. No buttons, no actions. Tone: `neutral` · `good` · `warn` · `needs-you` · `bad`.

**One product:** the dashboard renders blocks with the orch design system only (tokens, the fixed icon set, motion, skeleton
while loading, the same empty and error states and wording); add-on tabs sit in the same nav list as Tickets/Inbox, ordered by
`order` — there is no "plugins" area. Add-on text never carries HTML; the dashboard sets it with `textContent`.
Published dashboard snapshots leave add-on tabs and ticket rows out unless the user asks (`--with-addons`).

## Skill and AGENTS block

Skill folder is exactly `orch-<name>` (`SKILL.md` front matter `name: orch-<name>`; a manifest `skill` path may have any folder name,
the copy in `.agents/skills/` is always `orch-<name>`), written like the core skills: plain words, commands first,
"ask the user before anything that can't be undone". The AGENTS block sits between `<!-- orch:addon:<name> -->` and
`<!-- /orch:addon:<name> -->` and is replaced as a whole; text outside the markers is never touched. The block: a heading
`## orch-<name>`, one line what it is, `Read .agents/skills/orch-<name>/SKILL.md`, at most 4 lines more.

### Skills that say what is on (template)

A skill may change with what is turned on or connected. Its `SKILL.md` (and `AGENTS-block.md`) may hold
`{{#fact}}...{{/fact}}` (kept when the fact is true) and `{{^fact}}...{{/fact}}` (kept when false); a tag alone on its line
leaves no blank line. Facts are booleans from local state only (never a name or text another workspace wrote). The
front matter is `description: "{{description}}"`, built from `description.toml` next to it: `[online] lead`, `not_for`
and `[[online.part]] when = [facts], text`; the parts whose facts are all true are joined into
"<lead> Use when you need to: a, b, or c. <not_for>" (150-500 characters, must contain "Use when" and "Not for"). An
optional `[offline] text` is used while the fact `connected` is false. `description.toml` is not copied to the project.
Core renders it (`skillrender`) when an add-on is added or removed and when the relay or publish connection changes;
it writes only on change and prints "Skills updated; they apply from the next agent session." A skill with no
`{{` is copied as is. Every skill has the parts "When to use", "Recipes", "Rules"; the AGENTS block is a heading plus at
most 3 lines. `workspace/tests/test_skills_lint.py` checks all of this for every shipped skill and every fact combination.

## Ticket data

`ext.<name>` is a free object for the core. When the add-on is active, every CLI write of `ext.<name>` is checked with its
`ticket_ext` schema; a failing check refuses that write only. Inactive or unknown `ext` keys are kept unchanged and not shown.
Waiting is core (`waiting_on {kind: time|ticket|question|external, until?, ref?}`): the core records it and never promises
that something wakes the ticket; an add-on (the scheduler) may wake `kind: time` tickets.

## Ticket links and add-on fields

A ticket's `links` is a plain list `{kind, url, title?, status?, thumb?, at, by}` (ticket.schema.json). People and
agents add them with `orch link add <ticket> <url> [--kind K] [--title T]` (http and https only; the same address twice
is one link), `orch link list <ticket>` (numbered) and `orch link remove <ticket> <n|url>`; every change is one history
line, written through the ticket lock like every other op. `kind` is the first `[[ticket_links]]` type of an active
add-on whose `match` fits the address, else `link`. How a link is shown is decided in one place,
`workspace/src/orch/links.py` (used by the CLI, the dashboard and the phone snapshot):
1. the kind belongs to an active add-on → its label (with the site's name when the address is a known site,
   e.g. "GitHub · Pull request"), its icon and the stored `status`;
2. else the address is in the known-sites table `workspace/src/orch/known_sites.json` (GitHub, GitLab, Confluence,
   Jira, Linear, Notion, Figma, Miro, Google Docs/Sheets/Slides/Drive, YouTube, Loom, Slack, Teams, SharePoint,
   Trello, Dropbox) → the site's name and icon;
3. else "Link" with the short address.
An add-on that is off changes nothing in the file: its links show as known site or plain link and get their label and
status back when it is on again. Links written before `kind` existed carry `type`; it is read as the kind.

`[ticket_fields]` turns `ext.<name>` into fields under the ticket's Details. Types come from the schema: `enum` =
choice (`x-labels` gives the shown words), `number`/`integer` = number, `format: date` = date, `format: uri` = url,
other `string` = text; `readOnly` = filled in by the add-on (people cannot set it), `x-hidden` = kept, not shown.
People set one field with `orch ticket set <ticket> <name>.<field> <value>` (empty value clears it); the value is
checked against the schema and refused in plain words (`Can't set Channel to "radio". Pick one of: YouTube, …`).
`orch addon list --json` carries `ticket_links`, `ticket_fields` (`section`, `show_on_card`, `fields: [{key, title,
type, options?, read_only, hidden}]`) and `acts` (verbs) for the dashboard.

## Act: refresh

An add-on with `[acts.refresh]` looks up its own links (e.g. a pull request's state) when someone clicks Refresh or an
agent runs `orch <name> act refresh [--by X] [--json] -- <ticket>`. Core runs the add-on's `act refresh` as usual; the
add-on prints ONE JSON object and never writes the ticket:

```json
{"ticket": "DM1-12",
 "links": [{"url": "https://github.com/acme/billing/pull/418", "title": "Add CSV export for invoices", "status": "merged"}],
 "ext": {"github": {"pr_status": "merged"}},
 "say": "Pull request #418 was merged."}
```

Core merges it in one locked write: links are matched by `url`; only `title`, `status` (`[a-z0-9 -]`, ≤ 24) and
`thumb` (`artifacts/<file>`) change; `ext` only under the add-on's own name, checked with its schema; anything else
is ignored or refused. One history line per change (`<name> refresh: <link> status open -> merged`). Nothing changed →
nothing is written and `say` (or "Nothing to update.") is printed. `--json` prints `{ticket, key, changes: [{what, url?,
name, field, old, new}], say}`. Exit codes as for every add-on command. There is no timer in core: an add-on that wants
regular refreshes adds a schedule. Example: `workspace/tests/test_links.py` (`REFRESH`) refreshes GitHub pull requests
with `gh pr view <url> --json state,title`, and answers "gh is not installed here" without it.

