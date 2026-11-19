# Skills add-on (`orch skills`, Preview, ORCH-834, ORCH-842)

Everything helpers get in a workspace, in four kinds, and Turn off / Turn on **for this workspace only**.
Nothing is moved or edited (edit: ORCH-840, delete and bin: ORCH-841); Remove from here deletes only the
workspace's copy of a shared skill (the admin keeps it).

## Commands
| Command | What |
|---|---|
| `orch skills list [--json]` | Every item (schema `orch.skills-page/1`, below), with its id |
| `orch skills off <id>` / `on <id>` `[--by X] [--json]` | Turn one item off or on here; only a person (refused under a helper tool or with `--by agent:`); exit 2 with the reason when it cannot be |
| `orch skills remove <id>` / `restore <id>` `[--by X] [--json]` | A skill your admin shares: out of this workspace (relay updates skip it) / back (starts a relay update); only a person |
| `orch skills check <id> [--json]` | Ask Claude once (`claude mcp list`) which connected services are signed in; kept in `.orch/addons/skills/signin.json` |
| `orch skills history [--json]` | Who turned what on or off, removed or brought back (newest first, last 200) |
| `orch skills act on|off|remove|restore|check --by X --json -- <id>` | The page's clicks, run by the dashboard as the person (`[acts.*]`, who = people) |
| `orch skills start|stop|status|run` | The background process that serves the page (`[page]`, port 8436 or any free one) |

## Items
`id` = `<kind>:<where>:<name>`: kind `skill` · `instructions` · `service` · `login`; where `orch` (orch and its add-ons) ·
`workspace` · `admin` (shared over the relay) · `mine` (this computer, outside the folder). Each item has `name`,
`description`, `on`, `can_off`, `locked` (why not, plain words), `tools` ({"Claude": "on"|"off", "Codex": ...} for the
helper tools found here), `note` ("Codex still sees it" when off but a tool still sees it), `problems` (Needs a look),
`actions` (other clicks: `remove`, `restore`, `check`), `codex_limit` (why Codex cannot be switched for it), and for
skills `fields` (the header metadata read by `orch.skillmeta`, ORCH-532; without it only the description).
Shared skills also carry `newer` (the admin has a newer version, or newer settings wait for the next relay update);
a removed one shows as a row with `removed: true` and the action `restore`. Services carry `signin` (plain words) and
`signin_state` (`connected` · `needs-sign-in` · `failed` · `pending` · `off`). Logins carry `on_means`, `off_means`
and `scope`.

## What off does
| Item | Off |
|---|---|
| orch's and the admin's skills | the name goes on `.orch/skills-off.json` (local-files.md); the core's linking skips it |
| this workspace's and this computer's skills | `.claude/settings.local.json` `skillOverrides: {"<name>": "off"}` |
| connected services | `.claude/settings.local.json` `permissions.deny: ["mcp__<server>__*"]`; for a service Codex has, also a marked block `[mcp_servers."<name>"] enabled = false` in the folder's `.codex/config.toml` (only when Codex trusts the folder; otherwise `codex_limit` says so) |
| logins (key profiles) | `orch secret profile agents-disable <profile>`: helpers may use it only through its own command, or not at all when it has none. Kept in this workspace's key folder: **per workspace** |
| your rules for every project (`~/.claude/CLAUDE.md`) | `.claude/settings.local.json` `claudeMdExcludes: ["<full path>"]` |
| the main `orch` skill, the workspace's instruction files, orch's blocks, keys no profile uses | cannot be turned off here (`locked`) |

## What Codex supports (Codex 0.170, checked 19 Nov 2026)
Services: a per-folder switch in `.codex/config.toml`, honoured only in folders Codex trusts. Skills: none per folder
(`[[skills.config]]` counts only in `~/.codex/config.toml`, for every folder), so a skill of this workspace stays
visible to Codex (`codex_limit`); orch's own and shared skills are links orch removes, so they are off for Codex
too. Rules files: Codex always reads the folder's `AGENTS.md`.

## Sign-in
A service with an orch key profile: whether its login is stored here. Any other service: what Claude reported at the
last `check` (Claude keeps a web sign-in in its own store; orch cannot read them). `check` starts the services'
programs, so it runs only on a click. The sign-in itself happens in Claude (`/mcp`).

orch records the settings lines it wrote in `.orch/addons/skills/owned.json` and removes only those; a line written by
hand shows as off and `locked`. One change at a time (`.orch/addons/skills/.lock`). A settings file that is not readable
JSON, or reached through a link anywhere on its way, is refused, never overwritten. The settings file is replaced
only when nobody changed it since orch read it; a recorded line that is gone from the file is forgotten, so a line
written by hand later is never taken for orch's.

## Needs a look
Retired but on; description shorter than 20 characters; a program in `requires` not found; a login in
`requires-logins` not in the key store; `review-by` passed; a service whose login is not stored; a service Claude
reported as needing a sign-in.
