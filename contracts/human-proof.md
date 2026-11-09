# Human-only actions: proof from the human channel (invariant H1)

**Threat-model boundary (owner decision R1: Level 1, no OS sandbox).** An agent runs as the same OS user and can always read
or write anything that user can. **Goal:** no agent can act as the person *through orch's own interfaces*: flags,
environment, workspace files, the local page, the relay client. **Non-goal:** an agent that patches the orch install, edits
orch-home files directly, or traces processes; such findings go to "Level 2 later" (human-proof.md), not into these contracts.

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

1. **Human key.** The core creates `<guarded orch home>/keys/<workspace local id>/human.key` (secrets.md, Guarded orch home:
   a real workspace never uses an env-chosen home; the nonce store and `human-settings.json` live there too) (32 random bytes, hex, 0600, in the key
   folder of secrets.md, under its rights checks and the agent deny rules). It is never put in argv, in any environment
   variable, in the workspace or in a log.
2. **Who holds it.** Only the page servers a person starts (Focus, dashboard) read it, at start, into memory. They refuse
   to start when an agent tool is in their environment, and they never pass it to a child (agent runs, add-on commands
   get a cleaned environment as today).
3. **Page session.** The session cookie is bootstrapped only from a **one-time launch token**: when a person starts or
   opens the page (`orch start`, the dashboard's Open button, the CLI hand-off below), the core writes a random token to
   `<guarded orch home>/keys/<ws>/launch-<server>.token` (0600, single use, 120 s) and opens the browser at
   `http://127.0.0.1:<port>/#launch=<token>` (a URL fragment, never sent in a request line or logged). The page posts it
   once to `/session`; the server compares it with the file, deletes the file, and sets the cookie (`HttpOnly;
   SameSite=Strict; Path=/`, new on every server start). A first GET without a token gets a read-only page and no cookie.
   **Mint routes exist only on the loopback listener**; every request, GET included, must carry `Host: 127.0.0.1:<port>` or
   `localhost:<port>`; any `X-Forwarded-*` or `Forwarded` header, or a request that arrived through a remote-access path
   (relay or any proxy, even when the peer is 127.0.0.1), never gets a proof: it is watch-only. Origin is checked on POST as today.
   **Servers that may hold the key:** only the orch-shipped page servers of the Focus and dashboard add-ons
   (`workspace-addons/focus`, `workspace-addons/dashboard`, installed from orch's own source; the core checks the installed
   manifest hash against the shipped one before it writes a launch token for them). A local or marketplace add-on never gets a
   launch token. (The key file itself is protected only by Level 1, below.)
4. **Mint.** For a human-only click the server builds `payload = {op, target, by, iat, exp, nonce}` (`$defs/payload`):
   `op` from the fixed table below, `target` the exact ticket / run / setting / key / connection / proposal, `by` =
   `human:<user>` of the OS account the server runs as, `exp − iat ≤ 60 s`, `nonce` 16 random bytes. Proof =
   `hp1.` + base64url(compact sorted JSON of payload) + `.` + base64url(HMAC-SHA256(human key, `hp1.` + that first part)),
   no padding.
   *Implementing slice 4.6 must* add `args_sha256` (sha256 of the canonical JSON of the values set: `keep_days`, the
   connection actions, …) to the payload so a proof also binds the value, not only the target.
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
`profiles.toml` / `.orch/mcp.json` as named, and the core also keeps a record in `<guarded orch home>/human-settings.json`,
keyed by the workspace's real path like `permissions.json` (`$defs/settings_record`).
- Setting a value **with a proof** writes the file and the record.
- **Lowering** (turning something off, sharing less) works from the file or the CLI without a proof, and the core writes a
  **tombstone** record (`value: false`) the first time it sees the lowered value.
- **Effective = file value AND (record value, or the owner default when no record ever existed).** Defaults: `live_session`
  on, `share_counts` on (owner decisions 3C, I5); everything else off.
For list values (connection allow lists) a narrower file narrows the record (`grant ∩ file`), the list form of a
tombstone (inventory.md).
So an agent that edits `session_typing = true` changes nothing, and once a person switched `share_counts` or `live_session`
off, an agent editing the file back to on changes nothing either. Reference `hp_settle`, vectors `settle`.

## The relay connection record (`relay.connect`)

The relay address, workspace id, token and the paired phones come **only** from a record in the guarded orch home
(`<orch home>/keys/<ws>/relay.json`: `{url, workspace, token, phones, connected_by, at}`), written by `orch relay connect` /
the dashboard's Connect with a `relay.connect` proof; `phones` is updated by each refresh fetched under that record. The
token lives **only** in that record. The workspace's `.orch/secrets/relay.json` holds `{url, workspace}` and no token, and is
no longer authority: when its `url` or `workspace` differs from the record, every relay call is refused ("The relay settings
in this folder were changed. Connect again from the dashboard."); a `token` found in it is never read (the core rewrites the
file without it).
The relay client uses no proxy from the environment (`HTTP(S)_PROXY`, `ALL_PROXY` are ignored: an empty proxy handler) and a
fixed trust store shipped with orch or the OS default, never `SSL_CERT_FILE` / `SSL_CERT_DIR` / `REQUESTS_CA_BUNDLE`.
Reference `relay_conn`, vectors `relay`. Admin-source classification (inventory.md) uses refreshes fetched this way only.

## Phone actions (verdict, answer from the phone)

No proof is minted and the person sees no extra step. The proof is the relay channel itself: the workspace applies a phone
verdict or answer only (1) from a message it fetched itself from the relay named in the relay record (above), over TLS with
the record's token, without env proxies or CA overrides, never from a file read back from `.orch/inbox/` (agents can write
there; saved files are for display and replay of non-human messages only), (2) when `from` is a `ph_` id in the record's
`phones` list (the relay builds phone messages itself and checks sender = caller, so no workspace or agent can post as a
phone), and (3) when `reply_to` names a question this workspace sent (relay.py `_answer_asked`, `_apply_review_answer`).
`by` is `human:<phone>` from that channel, never from the body's own label. Any process may run the fetch (`orch relay
inbox`); what it can apply is decided by the relay, not by the caller. Device-key-signed phone verdicts are a later step
(Level 2 later).

## Dev mode: the test human persona (demo workspaces only)

e2e drives owner-only steps in demo workspaces with a scripted test human. Its proofs carry `"dev": true` in the payload and
are signed with a separate **dev key** (`<guarded orch home>/keys/<ws>/dev-human.key`).
- **Dev status is a record in the guarded orch home** (`<orch home>/dev-workspaces.json`, keyed by the workspace's real
  path), written only by an install whose install record says *dev* (the dev kit's installer), and only at the moment it
  **creates** a demo workspace. A workspace that already has a `human.key` can never become dev (reference `dev_can_mark`).
- A normal install never reads `<state dir>/orch/dev-workspaces.json` or any other workspace-side or state-dir file for this;
  the kit's file is only an input to the dev installer when it creates demo workspaces.
- The verifier: a `dev: true` proof on a workspace without a dev record → refused (`dev_on_real`), whatever a file says
  and whatever key signed it; on a dev workspace it must verify with the dev key and `by` must be `human:test-human`.
  A real workspace never has a dev key (vectors `verify` "listed in the file but no record", "dev proof on a dev
  workspace", `dev_mark`).

## A person in their own terminal

A human-only command run without a proof is refused with a **hand-off to the dashboard**: the core adds a pending item for
that action to the local page and, on a desktop, opens the browser at it with a fresh launch token (step 3). The CLI prints
only "Opened the dashboard: click <button> to finish." **The launch token is never printed, returned or written where the
calling process can read it** (not stdout, not stderr, not the workspace). On a headless host (VPS) no browser is opened: the
item waits on the page the person already has open (through their own tunnel); the CLI says so.
The hand-off page says **"Requested by a command"**, shows the full action, target and value (the relay host, the hash being
allowed, the key profile, the update version), never puts focus on the confirm button, and hand-offs are rate-limited per op
(at most 3 pending per op, a new one replaces the oldest). No typed confirm words (owner rule). A confirmation on `/dev/tty`
is not used: a live agent runs in its own tmux pane with a terminal too, so a tty proves nothing.
What Level 1 promises: an agent cannot finish a human-only action with flags, environment, a tty or a forged workspace file;
it can ask for a hand-off, which the person sees as a request from a command and has to click.

## Human-only actions (every op that trusts person detection or env today)

Minted by: **page** = the local Focus or dashboard page (proof on stdin, steps 3–6); **phone** = the relay channel (above);
**terminal** = the CLI hand-off to the page. Vector class: every op is covered by the same `verify` vectors (forged
flags, missing, expired, other target, other op, replay, other key, tampered, untrusted home, dev on real); the op-specific
rows add a named case.

| op | Command / click | target | Minted by | Named vector |
|---|---|---|---|---|
| `run.takeover`, `run.type`, `run.release` | Session tab: Type in the session / Hand back (keys follow the proof on stdin) | ticket | page | screen `takeover` |
| `focus.settings` | Settings > Add-ons > Focus: `live_session` / `session_typing` on | setting | page | `settle` |
| `insights.settings` | Insights > Settings: `share_names`, `share_counts` on, `keep_days`, `max_mb` | setting | page | `settle` |
| `record.delete_detail` | Delete detail for this ticket | ticket | page, terminal | `verify` delete detail |
| `secret.add`, `secret.remove`, `secret.profile` | key store and profiles, incl. `allow_get` | key / profile | page, terminal | `verify` key profile, `settle` allow_get |
| `conn.allow` | Allow in the Used tab / Insights | connection | page, terminal | `verify` conn allow, inventory `allowed` |
| `checkup.accept`, `checkup.rollback`, `checkup.send_to_admin`, `checkup.reject` | proposal buttons | `<id>@<hash>` (proposal.md) / id | page | proposal `steps` |
| `ticket.verdict` | Looks good / Send back (dashboard, Focus); phone review | ticket | page, phone | `verify` ticket verdict |
| `ticket.answer` | answering a Needs-you question | `<ticket>:<question>` | page, phone | `verify` ticket answer |
| `relay.connect` | `orch relay connect`, changing the relay address | relay host | page, terminal | `verify` relay connect |
| `private.allow` | `orch private allow <name> --key <hash>` (approves an agent command on this machine) | `<name>:<hash>` | page, terminal | `verify` private allow |
| `private.move` | `orch private move` | name | page, terminal | – (same class) |
| `config.agent_add` | `orch config agent add` by a person (an agent's entry needs a person's OK) | agent name | page, terminal | – |
| `check.wont_do`, `check.wont_do_undo` | `orch check wont-do <id> <c> [--reason]` and undo | `<ticket>:<check>` | page, terminal | – |
| `chat.make_ticket` | `orch chat make-ticket <id>` | chat id | page, terminal | – |
| `chat.send`, `chat.sync`, `chat.contacts`, `chat.thread_sync` | `orch chat send/sync/contacts`, `thread --sync`; dashboard `chat.send_ws`, `chat.sync_ws` | chat / workspace | page, terminal | – |
| `update` | `orch update` | – (target `orch`) | page, terminal | – |
| `run.stop` | Focus Stop / Stop all (today `by=focus`) | ticket or `all` | page | – (an agent may still stop its own run, `ORCH_RUN` = that run) |
| `relay.allow` | `orch relay allow <id> --once\|--permanent` (cli_clients.py 587): lets another workspace delegate or start work here | `<message id>:<once\|permanent>` | page, terminal | `verify` relay allow |
| `group.remove_member` | remove a workspace from a group chat (cli_clients.py 283) | `<group>:<workspace>` | page, terminal | – |
| `group.write_as_person` | write into a group as yourself (cli_clients.py 294, chat_groups.py 1337, 1361) | group | page, terminal | – |
| `group.share_file` | share a file with a group, checked or not checkable (cli_clients.py 250/252, chat_groups.py 1505, 2656) | `<group>:<file sha256>` | page, terminal | – |
| `group.readd_member` | re-add a removed member (chat_groups.py 1049) | `<group>:<workspace>` | page, terminal | – |
| `config.share` | `orch config share on\|off` (cli_config.py 270): the marked block in the team's AGENTS.md | `on` / `off` (off needs no proof) | page, terminal | – |
| `config.agents_may_finish` | `orch config set workflow.agents_may_finish on` (cli_config.py 210) | setting (off needs no proof) | page, terminal | `settle` class |
| `look.shared_pages` | show the workspace name and icon on shared file pages (look.py 229) | setting | page | – |
| `ticket.finish` | a person sets Done / Review without the checklist (tickets.py 615) | ticket | page, terminal | – |
| `run.human_input` | input that counts as a person's and may start a run (runs.py 375-397 `human_waiting`: today any `human:` by or phone line in the agent-writable `.orch/run/pending/<tid>.jsonl`) | ticket | page, phone | `pending` |
| `addon.act` (`who: people`) | an add-on button the manifest marks for people only (addons.py 599, 1051) | `<add-on>:<verb>:<ticket>` | page | – |
| relay admin switch / lock | `/admin/api/policy`, `PATCH /admin/api/workspaces/<id>` | – | the relay's own admin auth (`X-Orch-Admin`, private network), never a workspace token | – |

*Implementing slice 1.0a must* (N8) find "the caller's own run" (for `run.stop` of its own run and for the check-up's
`propose`) as a run whose recorded agent process (pid + start time) is an ancestor of the caller, not from `ORCH_RUN`; and
(N12) treat a missing or unreadable `human-settings.json` as every widening off, and write the tombstone at once when a
lowering comes through the CLI or the page.

**Read-back rule (pending input, synced ticket data).** A line in `.orch/run/pending/<tid>.jsonl` counts as a person's (and
may make a background host start a run) only when it carries `mac` = HMAC-SHA256(`human.key`, `"pending1." + workspace id + "." + ticket id + "." +
canonical JSON of the line` without `mac`, `delivered_at` and `human`; canonical = sort_keys, separators `,` `:`, UTF-8). The core writes the MAC when it
accepted the input with a valid proof (page) or from its own phone channel (above), and **verifies it on every read**,
not only when writing. `by`, `via` and the `human` field are informational and never trusted: a line without a valid MAC is
agent input. Binding ticket and workspace means a valid line copied into another ticket or workspace is agent input.
`delivered_at` is outside the MAC and informational only: consumed line ids are recorded under the key lock in
`<guarded orch home>/keys/<ws>/delivered.json`, checked and written atomically on consume, so deleting `delivered_at` or
re-appending a consumed line never delivers it again (reference `pending_is_human`,
`pending_deliver`, vectors `pending`, `deliver`).
**Synced "won't do"** (`check.wont_do` arriving through a sync merge): another machine's human key cannot be checked here, so it
counts as a person's only when the receiving core's relay client recorded it from a relay-authenticated sender (a phone, or a
person-attributed message the relay authenticated), or when it carries the receiving core's own MAC = HMAC-SHA256(`human.key`, `"wontdo1." + workspace id + "." + canonical JSON
of the item`), a different prefix from the pending MAC so the two can never be confused. Anything else is an agent's
(reference `wontdo_is_human`, vectors `wont_do`).

How the list was made (re-run before 1.0a closes): `grep -rnE 'require_human\(|agent_tool\(\)|startswith\("human:"\)|who.*people|Only a person|Only a human|only a person' workspace/src/orch workspace-addons/*/src`
(every hit was reviewed; display-only uses such as labels and history parsing are not ops).

The rows from `ticket.verdict` down exist in v2 today and still trust `--by human:` / person detection: making them check a
proof is **W2b slice 1.0a** (tracked follow-up); this contract is its spec.

## Level 2 later (consciously left out)

- Direct reads of `human.key`, `dev-human.key`, launch tokens or the key store by an agent (same OS user).
- Editing orch-home records (`human-settings.json`, `proposals.json`, the relay record, the dev record, the nonce store).
- Patching the orch install, its Python environment, or tracing orch processes.
- An agent scripting HTTP against the local page with a token it read from the orch home.
- Phone verdicts signed with a device key enrolled at pairing and pinned in the orch home (today the relay channel proves them).
- An OS sandbox for agents (Level 2 epic, owner decision R1).

## Honest limit (Level 1, owner decision R1)

An agent runs as the same OS user. One that deliberately reads `human.key` despite the deny rules can mint proofs, the same
way it could read keys. H1 removes the trivial paths (flags, env, workspace files, argv, a forged click from another
origin); it is not a wall against a hostile agent. An agent that scripts HTTP against the local page (reading the launch
token from the key folder, or racing the person for it) can get proofs the same way. No OS sandbox is planned.
