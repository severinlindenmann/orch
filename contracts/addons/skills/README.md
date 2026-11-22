# Skills add-on (`orch skills`, Preview, ORCH-834)

Everything helpers get in a workspace, in four kinds, and Turn off / Turn on **for this workspace only**.
Delete moves a skill of this workspace or of this computer into a Bin, Restore puts it back, New skill makes a draft
(ORCH-841). Nothing else is moved, edited or deleted (edit: ORCH-840).

## Commands
| Command | What |
|---|---|
| `orch skills list [--json]` | Every item (schema `orch.skills-page/1`, below), with its id |
| `orch skills off <id>` / `on <id>` `[--by X] [--json]` | Turn one item off or on here; only a person (refused under a helper tool or with `--by agent:`); exit 2 with the reason when it cannot be |
| `orch skills delete <id>` `[--by X] [--json]` | Move one skill (`skill:workspace:…` or `skill:mine:…`) into its Bin; only a person |
| `orch skills bin [--json]` | What is in both Bins (`bin`, below), newest first |
| `orch skills restore <bin id>` `[--by X] [--json]` | Put one Bin entry back where it was; refused when a skill of that name is there; only a person |
| `orch skills new <name>` `[--by X] [--json]` | Make `.agents/skills/<name>/SKILL.md` with the standard header, status draft, owner = the person; only a person |
| `orch skills history [--json]` | Who turned on, off, deleted, restored or made what (newest first, last 200) |
| `orch skills act on|off|delete|restore|new --by X --json -- <target>` | The page's clicks, run by the dashboard as the person (`[acts.*]`, who = people). Targets: an item id; `bin:<workspace|mine>:<entry>` for restore; `skill:workspace:<name>` for new |
| `orch skills start|stop|status|run` | The background process that serves the page (`[page]`, port 8436 or any free one) |

## Items
`id` = `<kind>:<where>:<name>`: kind `skill` · `instructions` · `service` · `login`; where `orch` (orch and its add-ons) ·
`workspace` · `admin` (shared over the relay) · `mine` (this computer, outside the folder). Each item has `name`,
`description`, `on`, `can_off`, `locked` (why not, plain words), `tools` ({"Claude": "on"|"off", "Codex": ...} for the
helper tools found here), `note` ("Codex still sees it" when off but a tool still sees it), `problems` (Needs a look),
and for skills `fields` (the header metadata read by `orch.skillmeta`, ORCH-532; without it only the description).

## What off does
| Item | Off |
|---|---|
| orch's and the admin's skills | the name goes on `.orch/skills-off.json` (local-files.md); the core's linking skips it |
| this workspace's and this computer's skills | `.claude/settings.local.json` `skillOverrides: {"<name>": "off"}` |
| connected services | `.claude/settings.local.json` `permissions.deny: ["mcp__<server>__*"]` |
| your rules for every project (`~/.claude/CLAUDE.md`) | `.claude/settings.local.json` `claudeMdExcludes: ["<full path>"]` |
| the main `orch` skill, the workspace's instruction files, orch's blocks, logins | cannot be turned off here (`locked`) |

orch records the settings lines it wrote in `.orch/addons/skills/owned.json` and removes only those; a line written by
hand shows as off and `locked`. One change at a time (`.orch/addons/skills/.lock`). A settings file that is not readable
JSON, or reached through a link anywhere on its way, is refused, never overwritten. The settings file is replaced
only when nobody changed it since orch read it; a recorded line that is gone from the file is forgotten, so a line
written by hand later is never taken for orch's.

## Needs a look
Retired but on; description shorter than 20 characters; a program in `requires` not found; a login in
`requires-logins` not in the key store; `review-by` passed; a service whose login is not stored.

## Delete, Bin and Restore (ORCH-841)
Only skills of this workspace (real folders in `.agents/skills` or `.claude/skills`) and of this computer (the helper
tools' own skill folders, e.g. `~/.claude/skills`) are deleted; orch's and the admin's skills are turned off instead,
and a skill folder that is a link is never deleted (`can_delete` false). Two Bins:
- workspace skills: `.orch/addons/skills/bin/<entry>/` (local-files.md);
- this computer's skills: `<orch home>/skills-bin/<entry>/`, outside every workspace.

An entry (`<YYYYMMDDTHHMMSSZ>-<name>-<6 hex>`) holds `item/` (the folder, links kept as links) and `record.json`
(`orch.skills-bin/1`: kind, where, name, from, at, by, state, note). Delete is copy then remove: state `copying` →
the copy is compared file by file (sha256) → `removing` → the folder is renamed aside (`.orch-delete-<entry>`), only
files the copy holds unchanged are removed (each compared right before), anything else goes back to the old place
(`note` says so) → `in-bin`. Restore: refused when `.orch-restore-<entry>` is in the way → `restoring` → copied
there → the name is claimed with an empty folder (POSIX; mkdir fails when taken) → renamed onto the claim (never over
anything) → `restored` → entry removed. Before every list and change, under the workspace lock and the computer
bin's own lock, orch finishes or undoes a cut-off move: `copying` → the half copy goes; `removing` → the removal is
finished as above; `restoring` → the temporary folder goes when it holds only bin files (else it stays, `note`), or
the restore is finished when the folder in place holds exactly the bin copy. A record whose `from` is not a skill
folder of that place is refused.
Nothing is removed from a Bin by itself in this version. `orch addon remove skills --purge` deletes the add-on's folder
and with it the workspace Bin; this computer's Bin stays.

`bin` rows: `id` (`bin:<where>:<entry>`), `name`, `where`, `from` (`~/` for this computer), `at`, `by`, `state`,
`can_restore`, `why` (plain words when not), `note`.

## New skill
`skill:workspace:<name>`: small letters, digits and single dashes, at most 64, not `orch…`, not a name already listed.
The file: `name`, a description to fill in, `metadata` with `version: "0.1.0"`, `owner`, `status: "draft"` (ORCH-531).
