# Workspace look: icon and colour

Every workspace can have one **icon** (out of 100) and one **colour** (out of 12). The same badge shows in the dashboard,
on the phone, in the relay admin portal and in the publish admin portal. Nothing picked: the first letter of the name in
a colour taken from the name. Shared file pages of publish show the workspace name and icon too, unless the owner
turns that off (on by default).

Files: `look.json` (the allowlists: icons with category, label, search words; colours with a dark and a light tone),
`look.schema.json` (field shapes), `look/icons/<id>.svg` (the drawings, Lucide 1.70.0, ISC licence in
`look/LICENSE-lucide.txt`; keep the licence note wherever they ship), `vectors/look-v1.json`. `validate.py` checks all of them.

## Fields

| Field | Value | `null` means |
|---|---|---|
| `icon` | an icon id from `look.json` (`wallet`, `house`, …) | first letter of the name |
| `color` | a colour token from `look.json` (`teal` … `slate`) | **Automatic**: colour from the name |
| `look_by` (relay, publish only) | `admin` \| `workspace` | nobody set it yet |

No other values. No uploads, no free SVG, no hex colours. Ids and tokens never change meaning; a new set is a new version.

## Where it lives and who sets it

- **Workspace:** `.orch/config.toml` `[workspace] icon = "wallet"`, `color = "amber"`, `look_set_by = "agent"|"human"`
  (left out = `null` / nobody). A value not in `look.json` is ignored (default shown).
- **The agent picks it by default:** during setup the agent reads `orch look list`, picks an icon and colour that fit the
  workspace name and description and runs `orch look set` (`look_set_by = agent`). It may change its own pick later.
- **The person changes it** in the dashboard, Settings → General → *Icon and colour* (a click, no typed word;
  `look_set_by = human`). From then on `orch look set` from an agent is refused ("The person chose this icon. Ask them to
  change it in the dashboard.") (vectors `local_set`).
- **Push:** after each save and on every `connect` the core sends `PATCH /v1/me {icon, color}` to each connected service
  (relay, publish). The first such call makes the workspace the owner of its look there (`look_by = workspace`). Exception
  on connect: when the local look is `null`/`null` and the service holds an admin look, the core first takes that look
  into `config.toml` with `look_set_by = human` (the admin is the owner, so an agent may not replace it) and sends it
  back (vectors `connect`). A failed push is retried with the latest value on the next connect.
- **Relay / publish admin portal:** may set the look only while `look_by` is `null` or `admin` (e.g. a workspace created
  but not connected yet). Once `look_by = workspace` the portal shows it read only ("Chosen in the workspace's dashboard")
  and an admin change of `icon`/`color` gets `409 conflict` (the whole body is refused, other fields included). The
  `look_by` check and the write happen in one database transaction. A new workspace token (`/token`) keeps `look`
  and `look_by`.
- **Phone:** reads `icon`, `color` from `GET /v1/phone/workspaces`; stores nothing of its own.
- Applied at once, never pending: unlike the description these are no free text and cannot carry instructions.
  A look change is not part of `workspaces.json` (agents do not need it): no version bump, no refresh-hint.

## CLI (agents and people)

| Command | Does |
|---|---|
| `orch look list [--json]` | the 100 icons (id, label, group, search words) and 12 colours; `--json` = `{categories, icons, colors}` as in `look.json` |
| `orch look show [--json]` | this workspace's `{icon, color, set_by}` and what each service has |
| `orch look set [--icon <id>\|none] [--color <token>\|auto]` | saves to `config.toml` and pushes; unknown id/token → refused with the nearest ids; agent after a human pick → refused |

The orch core skill and the `AGENTS.orch.md` entry get three lines: the agent picks the icon and colour at setup with
these commands, the person may change it in the dashboard, and an agent never changes a pick the person made.
`orch status --json` items carry `icon` and `color` (for the dashboard's workspace switcher).

## Shared file pages (publish)

`show_on_shared_pages` (publish workspace record, default `true`): `GET /f/<id>/meta` returns `{workspace: {name, icon,
color}}` and the file page shows the badge and name above the file; `false` → `{workspace: null}`, only the orch logo.
The person switches it in the dashboard (Settings → Add-ons → Publish: "Show workspace name and icon on shared pages");
the core sends `PATCH /v1/me {show_on_shared_pages}` to publish. Only a person may change it: the core refuses `agent:*`
  callers (vectors `shared_pages_set`); publish cannot tell them apart, so the core is where this is enforced.
App pages (`/a/<name>`) are the workspace's own and are not changed.

## Description from the dashboard

The dashboard can edit the description (and tags) through the **same proposal path** as `orch relay|publish profile`:
`PATCH /v1/me {description}` to each connected service → pending → the owner approves it in the admin portal →
`description_by = workspace`. The dashboard shows "Waiting for approval" with a link to the admin portal while
`whoami.pending` is set. No new endpoint, no new trust path (the services cannot tell a person from an agent holding the
workspace token). Not connected anywhere → the row says "Shown once you connect a relay or publish".

## Body rules (`PATCH /v1/me`, admin PATCH)

- Left out = unchanged; `null` = back to the default. Both fields are checked first: one bad value and nothing is stored
  (`422 invalid`).
- `PATCH /v1/me`: look fields (and publish's `show_on_shared_pages`) may not be mixed with `description`/`tags` (or anything else) in one body → `422`. A look
  body answers `200 {…whoami}`; description/tags keep their `202` approval flow.

## Default (Automatic colour and letter)

- `clean(name)` = NFC, then trim Unicode White_Space at both ends.
- **Colour** = `colors[djb2_32(clean(name)) % 12]` in `look.json` order (frozen): `h = 5381`, then for each UTF-8 byte
  `h = (h * 33 + byte) mod 2^32`.
- **Letter** = the first code point of `clean(name)` whose Unicode category is L* or N*, upper-cased when the upper case is
  a single code point (else kept: `ß` stays `ß`); none → `?`.
- `name` = the name that surface shows (dashboard: folder name; relay/publish: the workspace name; phone: its own name
  for the workspace if set). Collisions are fine: it is decoration, the name always shows next to it.

## Drawing the badge

A rounded square (phone: its usual rounded avatar shape), background = the colour's `dark` tone at 18 % over `#15181d`
(light mode: `light` tone at 14 % over white), icon or letter in that tone. Icons are 24-unit line drawings
(`currentColor`, stroke 2): about 52 % of the badge size, 75 % at 20 px and below (browser tab icon). Every tone has
at least 4.5:1 on its badge background. The phone bundles the same SVGs as template images (not SF Symbols).

## Fallbacks

- Unknown icon id (newer server, older client) → letter; unknown colour token → Automatic colour; fields missing
  (older server) → letter + Automatic colour. Never a blank badge. A client never writes its fallback back.
- Workspace cannot reach a service when saving: saved locally, sent on the next connect.
