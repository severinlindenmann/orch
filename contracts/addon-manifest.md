# Add-ons: manifest, activation, CLI, views (`orch_api = 1`)

The core knows no add-on by name. An add-on is a Python package with an `orch-addon.toml`. Once it is turned on in a
workspace it looks and works like part of orch: same commands style, same `--json` and errors, same config file,
same skill tone, a dashboard tab that cannot be told apart from a built-in one.
Schemas: `addon-manifest.schema.json`, `addon-view.schema.json`, add-on ext schemas in `addons/` (e.g. `addons/scheduler.ext.schema.json`).
Examples: `review/scheduler.orch-addon.toml`, `review/scheduler.view.example.json`, `examples/addon-*/`.

## Manifest `orch-addon.toml`

Lives inside the add-on's top-level Python package, next to `__init__.py`
(`workspace-addons/scheduler/src/orch_scheduler/orch-addon.toml`). The package registers itself in the entry-point group
`orch.addons` as `<name> = "<module>"` (module only). The core finds the file with `importlib.util.find_spec(<module>)`
(top-level, so nothing is imported) and **never runs add-on code to discover it**.

| Key | Meaning |
|---|---|
| `schema = "orch.addon/1"`, `orch_api = 1` | Manifest format and add-on contract version. Other values: refused |
| `name` | `[a-z][a-z0-9-]{1,31}`, not a core command (`ticket`, `addon`, `relay`, `publish`, `init`, `update`, `config`, … see schema). Unique in the tool env |
| `version`, `description` | `x.y.z`; one plain sentence (shown in `orch addon list` and `orch --help`) |
| `run` | Top-level module. `orch <name> <args>` = subprocess `<orch's python> -m <run> <args>` |
| `skill` | Folder with `SKILL.md` → copied to `.agents/skills/orch-<name>/` |
| `agents_block` | AGENTS.md block body (default `<skill>/AGENTS-block.md`) |
| `ticket_ext` | Local JSON Schema for `ext.<name>` (no remote `$ref`, ≤ 32 KB) |
| `background` | `true` = has a long-running process; must implement `orch <name> stop` |
| `[dashboard]` | `label` (≤ 16 chars), `icon` (fixed set in the schema), `order`: the add-on has a tab filled by `orch <name> view --json` |
| `[[ticket_view]]` | Ticket detail rows from `ext.<name>`: `field`, `label`, `format` = `text` · `time` · `cron-human` · `chips` · `yes-no` |

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
2. removes `.agents/skills/orch-<name>/` (exactly that folder, never `orch-<name>-x`, which may belong to another add-on or the
   user), the AGENTS.md block, the `.claude/skills` links;
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
- Required subcommands: `view --json` if `[dashboard]`; `stop` if `background`. Optional: `status --json`.

## Core commands an add-on may rely on (`--json`)

- `orch ticket list --json`: a plain JSON list of ticket objects (`ticket.schema.json`, with `revision` and `ext`); done and dropped tickets only with `--all` (or `--status <s>`).
  `orch ticket show <id> --json`: one ticket; `ext.<name>` is left out for add-ons that are not active.
- `orch addon list --json`: above. `orch relay status --json`: `{"configured": false}` or
  `{"configured": true, "url", "workspace"}`; it never touches the network (the dashboard shows Inbox when `configured`).
- Errors with `--json` on stdout: `{"error": "<plain words>"}`, exit 2.

## Views (dashboard tab)

The dashboard (itself an optional add-on, the host) never imports add-on code. For each active add-on with `[dashboard]` it
**pulls** `orch <name> view --json` (timeout 2 s, max 256 KB stdout, validated with `addon-view.schema.json`):
- ok → render blocks, header "as of HH:MM" from `generated_at`, optional `notice`;
- timeout / error / invalid → keep the last good result (in memory) with a "not up to date" state, or the error state if none.
`view` must be read-only, fast, and must not start a background process. Blocks: `stat`, `list`, `calendar` (days strip),
`timeline`, `chips`, `table` (typed columns text/number/duration/date/tone). Items may have a `link`: a ticket id (opens the
ticket) or an `https://` URL (new tab). No buttons, no actions. Tone: `neutral` · `good` · `warn` · `needs-you` · `bad`.

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

## Ticket data

`ext.<name>` is a free object for the core. When the add-on is active, every CLI write of `ext.<name>` is checked with its
`ticket_ext` schema; a failing check refuses that write only. Inactive or unknown `ext` keys are kept unchanged and not shown.
Waiting is core (`waiting_on {kind: time|ticket|question|external, until?, ref?}`): the core records it and never promises
that something wakes the ticket; an add-on (the scheduler) may wake `kind: time` tickets.
