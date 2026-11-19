# Skills add-on (`orch skills`, Preview, ORCH-834)

Everything helpers get in a workspace, in four kinds, and Turn off / Turn on **for this workspace only**.
Nothing is moved, edited or deleted (edit: ORCH-840, delete and bin: ORCH-841).

## Commands
| Command | What |
|---|---|
| `orch skills list [--json]` | Every item (schema `orch.skills-page/1`, below), with its id |
| `orch skills off <id>` / `on <id>` `[--by X] [--json]` | Turn one item off or on here; only a person (refused under a helper tool or with `--by agent:`); exit 2 with the reason when it cannot be |
| `orch skills history [--json]` | Who turned what on or off (newest first, last 200) |
| `orch skills act on|off --by X --json -- <id>` | The page's clicks, run by the dashboard as the person (`[acts.on]`, `[acts.off]`, who = people) |
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
