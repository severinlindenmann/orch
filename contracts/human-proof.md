# Human-only actions: proof from the human channel (invariant H1)

**H1. A human-only action needs proof from the human channel, never caller-asserted flags or environment.**
`--by human:…`, `--from local-page`, "no agent tool in the environment" and a terminal on stdin are information, not proof:
an agent can pass any flag, scrub its environment (`env -i`) and run inside a terminal (its own tmux pane).

Schema: `human-proof.schema.json` (`$defs/payload`, `$defs/settings_record`). Vectors: `vectors/human-proof-v1.json`
(forged flags, missing, expired, wrong ticket, wrong action, replay, bad signature, valid; widening settings). Reference:
`hp_verify` / `hp_effective` in validate.py. T0: `… contracts/validate.py human`.

## What v2 has today, and why it is not enough

- `tickets.require_human` / `agent_tool()`: refuse when an agent tool is detected in the environment (adapters.detect_env).
  Kept as an extra check, but it is caller-controlled (`env -i` removes it).
- Focus/dashboard servers: Host + Origin checks (`orch_ui.origin`), POST only with Origin, bound to 127.0.0.1, and
  `ORCH_FOCUS_NONCE` for the start/stop challenge. These prove "a browser on this computer sent this request to the page",
  which is the right human channel, but the page then calls the CLI with `--by human:<user>` (focus `actions.py`), so the
  CLI cannot tell the page from an agent passing the same flags.
- `workspace.permissions` (`config.permissions`): kept in the orch home keyed by the workspace's real path, never in the
  workspace; agents may lower, never raise. This pattern is reused below for widening settings.

## The proof

1. **Human key.** The core creates `<trusted orch home>/keys/<workspace local id>/human.key` (secrets.md, Trusted orch home:
   never chosen by `HOME` or `ORCH_HOME` unless pinned; the nonce store and `human-settings.json` live there too) (32 random bytes, hex, 0600, in the key
   folder of secrets.md, under its rights checks and the agent deny rules). It is never put in argv, in any environment
   variable, in the workspace or in a log.
2. **Who holds it.** Only the page servers a person starts (Focus, dashboard) read it, at start, into memory. They refuse
   to start when an agent tool is in their environment, and they never pass it to a child (agent runs, add-on commands
   get a cleaned environment as today).
3. **Page session.** On the first page load the server sets a random session cookie (`HttpOnly; SameSite=Strict; Path=/`,
   new on every server start) and the page gets nothing else secret. A click is a POST with Origin + Host checked (as
   today) and the cookie; a remote browser (through the relay or any non-loopback address) never gets a typing or settings
   proof: it is watch-only.
4. **Mint.** For a human-only click the server builds `payload = {op, target, by, iat, exp, nonce}` (`$defs/payload`):
   `op` from the fixed table below, `target` the exact ticket / run / setting / key / connection / proposal, `by` =
   `human:<user>` of the OS account the server runs as, `exp − iat ≤ 60 s`, `nonce` 16 random bytes. Proof =
   `hp1.` + base64url(compact sorted JSON of payload) + `.` + base64url(HMAC-SHA256(human key, `hp1.` + that first part)),
   no padding.
5. **Hand over.** The server runs the CLI with `--proof-stdin` and writes the proof as the **first line of stdin** (keys for
   `orch run type` follow on the next lines). Never argv, never env.
6. **Verify (core).** Refuse unless: the proof parses; the HMAC matches (constant-time compare); `op` and `target` equal
   the command being run; `iat ≤ now < exp` and `exp − iat ≤ 60`; the nonce was not used before (used nonces kept in
   `<orch home>/keys/<ws>/proofs-used.json` until their `exp`, written under the key lock); and no agent tool is detected
   (the old check stays as a second line). Then `by` comes **from the proof**; `--by` / `--from` are ignored (a different
   `--by` is refused as `forged`). Refusals are exit 2, `code: not_allowed`, "Do this in the dashboard on this computer."
7. **Streams.** One proof covers one command process: `orch run type --proof-stdin` takes the lock and accepts the keys that
   follow on the same stdin until it exits; a new process needs a new proof.

## Settings: records and tombstones

Every switch that widens what can happen (`[focus] live_session`, `[focus] session_typing`, `[insights] share_counts`,
`[insights] share_names`, `allow_get` of a key profile, connection allow lists) lives in `.orch/config.toml` /
`profiles.toml` / `.orch/mcp.json` as named, and the core also keeps a record in `<trusted orch home>/human-settings.json`,
keyed by the workspace's real path like `permissions.json` (`$defs/settings_record`).
- Setting a value **with a proof** writes the file and the record.
- **Lowering** (turning something off, sharing less) works from the file or the CLI without a proof, and the core writes a
  **tombstone** record (`value: false`) the first time it sees the lowered value.
- **Effective = file value AND (record value, or the owner default when no record ever existed).** Defaults: `live_session`
  on, `share_counts` on (owner decisions 3C, I5); everything else off.
So an agent that edits `session_typing = true` changes nothing, and once a person switched `share_counts` or `live_session`
off, an agent editing the file back to on changes nothing either. Reference `hp_settle`, vectors `settle`.

## Human-only actions in the draft-02 contracts

| op | Command / click | target | How it is proven |
|---|---|---|---|
| `run.takeover` | `orch run type <ticket> --takeover` (Session tab: Type in the session) | ticket | proof (local page only) |
| `run.type` | keys on the same stdin after a valid `run.takeover` proof | ticket | the same proof + holding the lock |
| `run.release` | `orch run type <ticket> --release` (Hand back) | ticket | proof; auto release needs none |
| `focus.settings` | Settings > Add-ons > Focus: turn `live_session` / `session_typing` **on** | setting name | proof + settings record; off needs none |
| `insights.settings` | Insights > Settings: `share_names` on, `share_counts` on again, `keep_days` / `max_mb` | setting name | proof + settings record; less sharing needs none |
| `record.delete_detail` | `orch record delete-detail <ticket>` (ticket page) | ticket | proof |
| `secret.add`, `secret.remove`, `secret.profile` | key store and profile changes, incl. `allow_get = true` | key or profile name | proof (+ settings record for `allow_get`) |
| `conn.allow` | `orch conn allow <name> …` (Allow in Used tab / Insights) | connection name | proof |
| `checkup.accept`, `checkup.rollback`, `checkup.send_to_admin`, `checkup.reject` | proposal buttons (proposal.md) | proposal id | proof |
| relay admin switch / lock | `/admin/api/policy`, `PATCH /admin/api/workspaces/<id>` | – | the relay's own admin auth (`X-Orch-Admin`, private network only, relay-api.md); never a workspace token |

## Honest limit (Level 1, owner decision R1)

An agent runs as the same OS user. One that deliberately reads `human.key` despite the deny rules can mint proofs, the same
way it could read keys. H1 removes the trivial paths (flags, env, workspace files, argv, a forged click from another
origin); it is not a wall against a hostile agent. No OS sandbox is planned.
