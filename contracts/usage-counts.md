# Daily counts for the admin, and the admin switch/lock (`orch.usage/1`)

In v2 the "hub" of the draft is the relay admin. A workspace connected to a relay sends it daily counts, on by default
(owner decision I5), so the admin sees which shared skills, connections and keys are used and where they fail. The workspace
and the admin can both switch it off (R6). This workspace's own names stay hidden until the person shares them (R3). The relay
being down never blocks local work.

Schema: `counts.schema.json` `$defs/upload`, `$defs/policy`. Examples: `examples/usage-upload/`, `examples/usage-policy/`.
Vectors: `vectors/counts-v1.json` `names`, `queue`, `idempotent`. T0: `… contracts/validate.py counts`. Routes are listed in
relay-api.md (Usage counts and policy).

## Workspace side

- Settings: `[insights] share_counts = true`, `[insights] share_names = false` (`.orch/config.toml`). Turning sharing **on**
  (share_names, or share_counts again) needs an `insights.settings` proof and counts only with the settings record
  (invariant H1, human-proof.md); turning it off works from the file. The core reads them only as effective values
  (`orch config get insights.share_counts|insights.share_names --json`, `orch record settings --json`): a file `true`
  without the person's record reads `false` (`share_counts` stays on by the owner default while no record ever existed).
  Set with `orch config set insights.share_counts|insights.share_names on|off [--proof-stdin] [--if-current <old>]`; `on`
  from off needs the proof (value-bound target, e.g. `insights.share_names=on`; the core compares with its current value,
  human-proof.md, Settings) and an agent caller is refused (`needs_person`). `share_counts on` is refused
  (`not_available`) while the workspace is not connected to a relay or the last relay policy said `usage_counts: "off"`
  (`orch relay refresh` keeps the snapshot's `policy` in `.orch/secrets/policy.json`; `orch relay connect` clears it once
  the new connection is saved, a failed connect leaves the current one's policy). On `orch relay connect`
  a one-time notice says: "Daily counts go to your admin: how often skills, connections and keys are used. No text, no chats.
  This workspace's own names stay hidden. Turn it off in Insights > Settings." Insights shows a chip "Sharing counts with
  your admin" while it is on.
- **What is sent**: one `orch.usage/1` body per closed UTC day (never today; a day closes at 01:00 UTC), built from the
  counts: per item `kind`, `source`, `uses`, `runs`, `ok`, `failed`, `refused`, plus the day's `runs` and `tickets`. No text,
  no ticket titles, no chats, no key values, no versions, no file paths. The schema has no field for text.
- **Names** (invariant P1, common.md): sent as they are only for `admin`, `builtin`, `marketplace` sources (the admin knows
  them already, or they are public). For every other source (`workspace`, `harness`, `none`, anything unknown) the name is replaced by `ref` = `h_` + the first 16 hex of
  HMAC-SHA256(key = a random salt in `.orch/.usage-salt` (0600, created on first use, in `.orch/.gitignore`), message = `<kind>:<name>`), stable per workspace so the
  admin sees "own skill h_3fa9… used 14×" without the name, unless `share_names = true` (in effect only with its settings record, human-proof.md). The body says `share_names`.
- **Queue**: each closed day is written to `.orch/record/outbox-usage/<day>.json` first, then sent oldest first on the next
  relay call (inbox pull, refresh) or the daily timer; deleted after a 2xx. Kept at most 60 days, older ones are dropped.
  `share_counts = false` or the admin's `usage_counts: "off"` → nothing is queued and the queue is deleted. Offline → the
  queue waits; nothing local waits for it.
- A `403 not_allowed` answer (the admin switched counts off for this workspace) is treated like `usage_counts: "off"`.

## Relay side

- `PUT /v1/usage/days/<YYYY-MM-DD>` (workspace auth), body `$defs/upload` with `day` equal to the path. **Idempotent per
  workspace + day**: the stored day is replaced as a whole. `200 {day, replaced: bool}`. A day in the future or older than
  400 days → `422 invalid`; counts off for this workspace or relay-wide → `403 not_allowed`; body over 256 KB → `413`.
  Stored 400 days. **The relay enforces the names rule on receipt**: with `share_names: false`, an item whose source is not
  `admin`, `builtin` or `marketplace` and that carries a `name` makes the whole body `422 invalid` (nothing stored).
- `GET /v1/policy` (workspace auth) → `$defs/policy` `{usage_counts: "on" | "off", live_session: "allowed" | "locked_off"}`;
  the same object is in `GET /v1/refresh` as `policy` (a change raises `version` and sends a refresh-hint).
- Admin: `GET / PUT /admin/api/policy` `{usage_counts: bool, live_session_locked: bool}` (relay-wide defaults: true, false);
  `PATCH /admin/api/workspaces/<id>` `{usage_counts: bool}` turns counts off for one workspace (the effective value is off
  when either is off); `GET /admin/api/usage?workspace=&from=&to=&kind=` → `{items: [{workspace, day, kind, name, ref,
  source, uses, runs, ok, failed, refused}], next}`.
- **Live session lock**: `live_session: "locked_off"` makes every workspace of this relay refuse `orch run screen` and
  `orch run type` (`locked_by_admin`, screen.md) and hide the Session tab, whatever `[focus] live_session` says. A workspace
  that cannot reach the relay keeps the last policy it got.

## Admin portal

The portal renders every name with `textContent` (names are workspace-chosen text).
Insights for the admin: per shared skill / connection / key, "used in 6 of 9 workspaces this week, 3 refusals", own names
shown as "own skill (hidden)". Buttons in a workspace's Insights that ask the admin ("Ask admin", "Send to admin") appear only
when a relay is connected.
