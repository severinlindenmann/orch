# Human-only actions: proof from the human channel (invariant H1)

**Threat-model boundary (owner decision R1: Level 1, no OS sandbox).** An agent runs as the same OS user and can always read
or write anything that user can. **Goal:** no agent can act as the person *through orch's own interfaces*: flags,
environment, workspace files, the local page, the relay client. **Non-goal:** an agent that patches the orch install, edits
orch-home files directly, or traces processes; such findings go to "Level 2 later" (human-proof.md), not into these contracts.

**H1. A human-only action needs proof from the human channel, never caller-asserted flags or environment.**
`--by human:…`, `--from local-page`, "no agent tool in the environment" and a terminal on stdin are information, not proof:
an agent can pass any flag, scrub its environment (`env -i`) and run inside a terminal (its own tmux pane).

Schema: `human-proof.schema.json` (`$defs/payload`, `$defs/settings_record`). Vectors: `vectors/human-proof-v1.json`
(forged flags, missing, expired, wrong ticket, wrong action, replay, bad signature, valid; widening settings; `verdict` MACs). Reference:
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
2. **Who holds it.** Only the page servers a person starts (Focus, dashboard, Insights) read it, at start, into memory. They refuse
   to start when an agent tool is in their environment, and they never pass it to a child (agent runs, add-on commands
   get a cleaned environment as today).
3. **Page session.** The session cookie is bootstrapped only from a **one-time launch token**: when a person starts or
   opens the page (`orch start`, the dashboard's Open button, the CLI hand-off below), the core writes a random token to
   `<guarded orch home>/keys/<ws>/launch-<server>.token` (0600, single use, 120 s) and opens the browser at
   `http://127.0.0.1:<port>/#launch=<token>` (a URL fragment, never sent in a request line or logged). The page posts it
   once to `/session`; the server compares it with the file, deletes the file, and sets the cookie (`HttpOnly;
   SameSite=Strict; Path=/`, new on every server start). A first GET without a token gets a read-only page and no cookie.
   The cookie is named per server AND per port, `orch_page_<server>_<port>` (`pageproof.cookie_name`; server name
   `[a-z0-9_]`, port an integer): cookies on 127.0.0.1 reach every loopback port, so one shared name would let opening
   Insights log the dashboard out. A server reads only its own name; another server's cookie is no session.
   **The cookie alone is never a session (#539).** The browser still sends every cookie of 127.0.0.1 to every loopback
   port, so any local page or dev server the person visits receives the value. The `/session` answer therefore also
   carries a **page secret** (`PageSession.secret`, 32 random bytes, new on every server start and on a revoking reuse of a
   link) in its JSON body `{"secret": ...}`, never in a cookie, URL or HTML. The page keeps it in its own `sessionStorage`
   (per origin, so per port) and sends it as `X-Orch-Page` on every same-origin request. `PageSession.authed` and
   `can_mint` require cookie AND secret (constant-time compare); every route that mints or acts with the session (act,
   notices, update status, area clicks; Focus process stop/stop-all stays fence-only as before, it is no proof) asks one of them. An update restart hands cookie and secret over together
   (`humanproof.write_resume_cookie` / `take_resume_session`, one use, 15 min).
   **Mint routes exist only on the loopback listener**; every request, GET included, must carry `Host: 127.0.0.1:<port>` or
   `localhost:<port>`; any `X-Forwarded-*` or `Forwarded` header, or a request that arrived through a remote-access path
   (relay or any proxy, even when the peer is 127.0.0.1), never gets a proof: it is watch-only. Origin is checked on POST as today.
   **Servers that may hold the key:** only the orch-shipped page servers of the Focus, dashboard and Insights add-ons
   (`workspace-addons/focus`, `workspace-addons/dashboard`, `workspace-addons/insights`, installed from orch's own source;
   the core checks the installed manifest hash against the shipped one before it writes a launch token for them;
   `humanproof.LAUNCH_SERVERS`, `pageproof.SERVERS`). A local or marketplace add-on never gets a launch token. (The key
   file itself is protected only by Level 1, below.) The dashboard is a named proof server for the Focus page it embeds,
   and for the Insights page it embeds (v1: Insights runs embedded under the dashboard); a standalone Insights page server
   keeps its own session and mints `insights.settings` and `record.delete_detail` proofs from it, and ONLY those
   (`pageproof.SERVER_OPS`, checked at mint time; Focus and dashboard are not limited by it). Its `insights.settings`
   target is built by `config.insights_target`, the one form the core checks. Until this orch ships the Insights add-on
   (`addons.SHIPPED_ADDONS`), no launch token is written or accepted for `insights`.
4. **Mint.** For a human-only click the server builds `payload = {op, target, by, iat, exp, nonce}` (`$defs/payload`):
   `op` from the fixed table below, `target` the exact ticket / run / setting / key / connection / proposal, `by` =
   `human:<user>` of the OS account the server runs as, `exp − iat ≤ 60 s`, `nonce` 16 random bytes. Proof =
   `hp1.` + base64url(compact sorted JSON of payload) + `.` + base64url(HMAC-SHA256(human key, `hp1.` + that first part)),
   no padding.
   *Implementing slice 4.6 must* add `args_sha256` (sha256 of the canonical JSON of the values set: `keep_days`, the
   connection actions, …) to the payload so a proof also binds the value, not only the target. (`insights.settings`
   is already value-bound without it: its target is `<setting>=<value>`, below; `args_sha256` stays for the other ops.)
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
`[insights] share_names`, `[workflow] agents_may_finish`, `allow_get` of a key profile, connection allow lists) lives in `.orch/config.toml` /
`profiles.toml` / `.orch/mcp.json` as named, and the core also keeps a record in `<guarded orch home>/human-settings.json`,
keyed by the workspace's real path like `permissions.json` (`$defs/settings_record`).
- Setting a value **with a proof** writes the file and the record.
- **Lowering** (turning something off, sharing less) works from the file or the CLI without a proof, and the core writes a
  **tombstone** record (`value: false`) on EVERY lowering, before it touches the file (one writer, `humanproof.record_set`,
  for every key; a grant through it needs a verified `human:` by). A tombstone's `by` is `human:...`, `file`
  (the core saw a lowered file value) or `reset` (a lowering by anything that is not a verified person, or a safe reset), see `$defs/settings_record`.
  Workspace `workflow.agents_may_finish` is one of these keys (default off). `by: file` is written only for a PARSED
  false (or a missing key whose default is off): a config.toml that cannot be read (not valid TOML, mid-write) or a
  value that is not true / false reads off and writes nothing, so a transient bad file never ends a person's grant.
- **Effective = file value AND (record value, or the owner default when no record ever existed).** Defaults: `live_session`
  on, `share_counts` on (owner decisions 3C, I5); everything else off.
For list values (connection allow lists) a narrower file narrows the record (`grant ∩ file`), the list form of a
tombstone (inventory.md).
**Retention numbers** (`[record] keep_days` 30 · 90 · 365 and `[record] max_mb` 512 · 1024 · 2048 · 4096, set as
`insights.keep_days` / `insights.max_mb`, record keys of the same names) are the number form: the record holds the value a
person approved; **effective = the LOWER of the file value and the record** (the default record 90 / 2048 when none exists,
or when the record holds anything but a whole number from the floor to the largest allowed value). A file value is first
snapped DOWN to the allowed list with a **floor of 30 days / 512 MB** (`keep_days = 1` counts as 30, `100` as 90, `99999` as
365; a whole number <= 0 means "as little as possible": the floor; a bool or a wrong type is the default), so an edit of config.toml can never make pruning delete nearly the
whole record; a record value below the floor counts as no record. An unreadable settings record (a home or file that
cannot be read) falls back to the lower of the file value and the default record 90 / 2048: never wider than the
default, though it may be wider than a lowered record that can no longer be read (accepted). Raising above
the record needs an `insights.settings` proof (target = `<setting>=<value>`, below); lowering is open to anyone and writes the lower
record (`by: reset`, or `file` when the core saw a lower file value), so the file alone never keeps records longer or larger
than a person approved. So a READ of a retention value (`orch config get`, `orch record settings`, pruning) may write:
the lower record `by: file`, decided under keys.lock with the file and the record read again there (a person's widening
writes record and file under that same lock, so a reader never writes an older file value over it). A protection reset
keeps a retention record at or below its default (it only ever lowers).
Lowering deletes nothing at once: the next pruning applies it (activity.md, Retention).
CLI (`--json`): `orch config get insights.share_counts|insights.share_names|insights.keep_days|insights.max_mb`
(`record.keep_days` / `record.max_mb` accepted too) answers the effective value (`{"insights.share_names": false}`; a file
`true` without the person's record reads `false`). `orch config set insights.<key> <value> [--proof-stdin]
[--if-current <old>]`: **the core decides** (the UI never does): under ONE lock (keys.lock, the lock of the settings
record and of the nonce store) it reads its CURRENT effective value and compares it with `<value>`. A widening (a share
switch off→`on`, a larger number) by an agent caller is refused before anything else (before any proof is read) and
otherwise needs an `insights.settings` proof that is **value-bound**: target `<setting>=<value>` (`insights.keep_days=365`,
`insights.share_names=on`; booleans `on`/`off`); it is verified and spent (verify_and_consume) in the same critical section
as the record write, so a proof for another value or key, or one already used, is refused (`needs_person`) and nothing
changes. The proof LINE is read from stdin (`--proof-stdin`) before keys.lock is taken, so a caller whose stdin never
closes cannot hold the lock (keys.lock also gives up after 10 s, "The key store is busy"); an agent caller's stdin is
never read. The same value succeeds without a proof and writes nothing (a given proof is not checked or spent). A narrowing needs no proof
and writes the off / lower record. `--if-current <old>` (on/off or the number): if the current effective value is not
`<old>` the command refuses with code `changed` ("This changed in the meantime: now <current>") and writes nothing, so a
page that showed a stale value gets a clean refusal. `insights.share_counts on` is refused with code `not_available`
(a plain message, nothing written, no proof read) while the share state (counts.md `sharing.counts`,
`config.share_counts_state`) is `off_by_admin` or `not_connected`; `off` is always allowed. This check, the widening
decision, the `--if-current` compare and the proof check are all inside the same lock; the page's own check is only a
second layer. A value outside the list is `invalid`. Success answers
`{"<key>": <effective value>, "changed": true|false, "widened": true|false}`.
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
**Test-only exception (launch link).** `orch start --no-open --print-launch-url` prints each page server's
`http://127.0.0.1:<port>/#launch=<token>` (and writes the one-time token as in step 3), so the browser-test lane can open a
page session on the test network. It is honoured **only** when `install_kind() == "test"` (the installer's record, or a
source-tree run) **and** the workspace's realpath is under the literal `<account home>/.orch-test/`; on a normal or dev
install, or for any other folder, it is refused before anything starts ("only on a test install"). It is never offered on a
person's own install, and a dev kit does not get it.

**Windows.** The account home is the profile folder from the process token (winacl `profile_dir`), the test prefix is
`<profile folder>\\.orch-test`, and paths compare component by component, case-insensitively, with both separators; the
prefix must `lstat` as a real folder with no reparse point (junction or symlink).

**Folder add-on snapshots.** A person-allowed folder add-on lives only at exactly `<account home>/.orch-tool/keys/<ws>/addon-snapshots/<content hash>`
(on a test install also under the test home), with no link on the path, and its hash must be on the person-allowed list
`<home>/addons-allowed.json` (written only inside the hand-off). The add-on list is `home()/addons.json` like all other state (a trusted `ORCH_HOME` included). A crafted file cannot steer an
install: `registry()` drops entries with a bad name, built-ins orch does not ship (name not in `SHIPPED_ADDONS`, or on a
dev/test install not inside the local source's `workspace-addons`), and unknown fields; a folder entry installs only from a
snapshot at the exact guarded location AND with a hash on that home's allowed list, which only the hand-off writes. A
folder entry without a hash is installed only on a dev or test install, never because a hand-off is running (a hand-off
allows exactly its one hash). On a **normal** install with an `ORCH_HOME` other than the account's default orch home, every
op that reinstalls the tool environment (update, add-on add/remove) is refused with plain words; list/status still run.
The account's default orch home is READ for trust decisions and is not written by a run that uses another `ORCH_HOME`.
**The one exception:** a person's proven approval (`addon.add_local`) writes the snapshot, `addons-allowed.json` and the
keys (`human.key`, settings, nonces) into the guarded home itself (`<account>/.orch-tool`). An install from before the
record existed counts as `normal` and `orch update` writes that record (never an elevation); the Windows finisher writes
it back and pins `UV_TOOL_DIR` too.

**Install record.** `<sys.prefix>/orch-install.json` = `{"schema": "orch.install/1", "kind": "normal|dev|test", "root": "<real path of the tool environment>"}`; it counts only
when it sits in the running interpreter's environment and `root` equals that environment's real path (no `uv`, no
`UV_TOOL_DIR` / `XDG_DATA_HOME` decides; a reinstall by orch pins `UV_TOOL_DIR` to the dirname of `root`); written
by `install.sh` / `install.ps1` straight into the tool environment after `uv tool install` (default `normal`; `test` or `dev`
only through the installer option the person running it gives: `ORCH_INSTALL_KIND=test sh install.sh`, `-InstallKind test`),
never by an orch command. `orch update` carries the existing kind over a reinstall. No record: a source-tree run is `test`,
any other install is `normal`. `ORCH_REPO` / `ORCH_REF` are honoured only on a dev or test install; on a normal
install they are never honoured (the person is told), and a person's `orch update` uses the official source shown on its card
(repo@ref bound into the proof).

What Level 1 promises: an agent cannot finish a human-only action with flags, environment, a tty or a forged workspace file;
it can ask for a hand-off, which the person sees as a request from a command and has to click.

## Human-only actions (every op that trusts person detection or env today)

Minted by: **page** = the local Focus, dashboard or Insights page (proof on stdin, steps 3–6); **phone** = the relay channel (above);
**terminal** = the CLI hand-off to the page. Vector class: every op is covered by the same `verify` vectors (forged
flags, missing, expired, other target, other op, replay, other key, tampered, untrusted home, dev on real); the op-specific
rows add a named case.

| op | Command / click | target | Minted by | Named vector |
|---|---|---|---|---|
| `run.takeover`, `run.type`, `run.release` | Session tab: Type in the session / Hand back (keys follow the proof on stdin) | ticket | page | screen `takeover` |
| `focus.settings` | Settings > Add-ons > Focus: `live_session` / `session_typing` on | setting | page | `settle` |
| `insights.settings` | Insights > Settings: `share_names`, `share_counts` on, `keep_days`, `max_mb` up; `orch config set insights.<key> … --proof-stdin` (the core decides what widens; lowering and the same value need no proof) | `<setting>=<value>`, value-bound (`insights.share_names=on`, `insights.keep_days=365`, `insights.max_mb=4096`) | page | `settle` |
| `record.delete_detail` | Delete detail for this ticket: `orch record delete-detail <ticket> --proof-stdin --json` (an agent is refused before anything else) | ticket | page, terminal | `verify` delete detail |
| `secret.add`, `secret.remove`, `secret.profile` | key store and profiles, incl. `allow_get`, `agents_may_env` | key / profile (`<profile>`, `<profile>:remove`, `<profile>:allow_get`, `<profile>:agents_may_env`, `<profile>:use:<sha256 of mode and command words>` = a person's own `orch secret env/file/exec/get --proof-stdin <profile>` call, bound to that exact mode and command (minted by the person's key, dev-proof today; the dashboard card that binds the proof to the command follows); any other caller is agent-level; switching a flag off needs no proof) | page, terminal | `verify` key profile, `settle` allow_get; a `profile set` also records the body MAC `profile1.<ws>.<profile>.<canon {env,files,set,run,extra, real_home when true}>` as the current entry of the ledger `profile.json` (tombstoned by `profile remove`; secrets.md, profile body) |
| `conn.allow` | Allow in the Used tab / Insights | connection | page, terminal | `verify` conn allow, inventory `allowed` |
| `checkup.accept`, `checkup.rollback`, `checkup.send_to_admin`, `checkup.reject` | proposal buttons | `<id>@<hash>` (proposal.md) / id | page | proposal `steps` |
| `ticket.verdict` | Looks good / Send back (dashboard, Focus); phone review; `orch ticket status <id> done` and `ticket patch` with a status (cli.py `_is_verdict` is the one decision, `_verdict_who` the one gate) | ticket | page, terminal, phone | `verify` ticket verdict; `verdict` (what makes it Done) |
| `ticket.answer` | answering a Needs-you question | `<ticket>:<question>:<digest>` (digest: sha256 hex of the question as shown, `tickets.question_digest`) | page, phone | `verify` ticket answer |
| `relay.connect` | `orch relay connect`, changing the relay address | relay host | page, terminal | `verify` relay connect |
| `private.allow` | `orch private allow <name> --key <hash>` (approves an agent command on this machine) | `<name>:<hash>` (the key covers adapter, command, live command, prompt; the card's exact block shows all four, and a hand-off is refused at take time if the entry no longer hashes to the key) | page, terminal | `verify` private allow |
| `private.move` | `orch private move` | `move` | page, terminal | – (same class) |
| `config.agent_add` | `orch config agent add` by a person (an agent's entry needs a person's OK) | `<name>:<sha256 (64 hex) of JSON [command, interactive or "", prompt or ""])>` (every saved value; the card's exact block shows them all) | page, terminal | – |
| `check.wont_do`, `check.wont_do_undo` | `orch check wont-do <id> <c> [--reason]` and undo | `<ticket>:<check>` | page, terminal | – |
| `chat.make_ticket` | `orch chat make-ticket <id>` | chat id | page, terminal | – |
| `chat.send`, `chat.sync`, `chat.contacts`, `chat.thread_sync` | `orch chat send/sync/contacts`, `thread --sync`; dashboard `chat.send_ws`, `chat.sync_ws` | chat / workspace | page, terminal | – |
| `update` | `orch update` | – (target `orch`) | page, terminal | – |
| `run.stop` | Focus Stop / Stop all (today `by=focus`) | ticket or `all` | page | – (an agent may still stop its own run, `ORCH_RUN` = that run) |
| `relay.allow` | `orch relay allow <id> --once\|--permanent` (cli_clients.py 587): lets another workspace delegate or start work here | `<message id>:<once\|permanent>` | page, terminal | `verify` relay allow |
| `group.remove_member` | remove a workspace from a group chat (cli_clients.py 283) | `<group>:<workspace>` | page, terminal | – |
| `group.write_as_person` | write into a group as yourself (cli_clients.py 294, chat_groups.py 1337, 1361) | host-side group: the ticket id; joined group: `<host ws id>:<group id>` (an id is only unique per host) | page, terminal | – |
| `group.share_file` | share a file with a group, checked or not checkable (cli_clients.py 250/252, chat_groups.py 1505, 2656) | host side: `<ticket>:<file sha256>`; joined: `<host ws id>:<group id>:<file sha256>` | page, terminal | – |
| `group.readd_member` | re-add a removed member (chat_groups.py 1049) | `<group>:<workspace>` | page, terminal | – |
| `config.share` | `orch config share on\|off` (cli_config.py 270): the marked block in the team's AGENTS.md | `on` / `off` (off needs no proof) | page, terminal | – |
| `config.agents_may_finish` | `orch config set workflow.agents_may_finish on` (cli_config.py 210) | setting (off needs no proof) | page, terminal | `settle` class |
| `config.permissions` | `orch config set workspace.permissions <mode>`, raising only (lowering is free for anyone) | the new `mode` | page, terminal | – |
| `look.icon` | `orch look set` (icon and colour of the workspace, shown to peers and on shared pages) | `look` | page, terminal | – |
| `config.copy_setup` | `orch config set workflow.copy_setup <command>`: a command orch runs in every new separate copy (clearing it needs no proof; an agent is refused) | sha256 of the command (the card shows it in full) | page, terminal | – |
| `copy.remove_orphaned` | `orch copy remove-orphaned <ws8>`: remove copies of a project that is gone (an agent is refused) | ws8; `<ws8>:discard` with `--discard` | page, terminal | – |
| `copy.retry` | `orch copy retry <ticket>`: retry interrupted copy cleanup (an agent is refused) | ticket id | page, terminal | – |
| `look.shared_pages` | show the workspace name and icon on shared file pages (look.py 229) | setting | page | – |
| `ticket.finish` | a person sets Done / Review without the checklist (tickets.py 615) | ticket | page, terminal | – |
| `run.human_input` | input that counts as a person's and may start a run (runs.py 375-397 `human_waiting`: today any `human:` by or phone line in the agent-writable `.orch/run/pending/<tid>.jsonl`) | ticket | page, phone | `pending` |
| `addon.add_local` | `orch addon add ./folder`: code from a folder runs inside orch's tool environment (normal installs only through this hand-off; dev/test installs may add directly) | content hash of a snapshot of the folder (card shows the path and a short hash); the add installs from that snapshot, never the live folder | page, terminal | – |
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
**Synced "won't do"** (`check.wont_do` arriving through a sync merge, and its undo): another machine's human key cannot be checked
here, so a step's decision counts as a person's only when the receiving core's relay client recorded it from a
relay-authenticated sender (a phone, or a person-attributed message the relay authenticated; the hook compares the FULL decision
record, never "this step was touched by a relay sender"), or when it carries the receiving core's own MAC = HMAC-SHA256(`human.key`,
`"wontdo1." + workspace id + "." + ticket id + "." + canonical JSON of {check, wont_do, reason, text, covers, nonce[, person, at, line]}`: `person`, `at` and `line` (the step fields `wont_by`, `wont_at`, `wont_line`) only on an "on" record made from #484 on, the actor label `human:<name>`, the UTC time of the decision and the digest of the history line it writes, inside the MAC; `humanproof.SIGNED_STEP_FIELDS` lists them) (an undo is
the same record with `wont_do` false and `reason`, `text` and `covers` null, so a later rename of the reopened step cannot make the undo stop verifying; the nonce is random and fresh for every signing, so equal decisions get
different MACs), a different prefix from the pending MAC so the two can never be confused, stored on the step as `wont_mac` (+
`wont_nonce`). The MAC binds WHERE the decision belongs (a valid decision copied onto another ticket or step is not the person's) and
WHAT an "on" decision is about (the step's text and covers: only a proven `check edit` of a Won't do step, which re-signs it, changes them). **Freshness is the ledger's job, not the MAC's:** the guarded home keeps
`keys/<ws>/wont.json`, per `<ticket>:<check>` the CURRENT MAC (null = tombstone, written by a proven removal); the verifier accepts a
MAC only when it IS the current entry, so replaying an older signed "on" or "undo" or reusing the id of a removed step does not
verify. A missing, loose or damaged ledger vouches for nobody (fail closed). The text of `by` (`human:...`) is **never** looked at.
The sync merge (`merge_ticket(..., person)`, `person` = the receiving core's verdict, `humanproof.wont_verifier`; no verifier =
nobody is a person) holds ONE invariant: **with a base that holds a person's decision, every step field the signed record covers (`wont_do`, `reason`,
`wont_nonce`, `wont_mac`, and, for an "on", `text` and `covers`: `humanproof.SIGNED_STEP_FIELDS` + the MAC, the same list the signer
uses, a test fails if they drift) differs from the base's only when that side verifies; otherwise it is the base's**, whether the
side dropped the decision, changed it, rewrote only the text or covers, garbled its MAC or replayed an old one, and before any
"newer side wins" pick. A renumbering (both sides added a different step with the same id) never moves an item the core vouches for, whatever `updated_at` says (a peer controls it): the other side's step is renumbered; two vouched items with one id cannot be merged and the caller pauses. A step one side deleted outright comes back (a
deletion carries no proof; a person's removal is proven where it is made). Anything else is an agent's (reference
`wontdo_is_human`, vectors `wont_do` and `ticket-merge-v1.json` rule `wont`).

**Done needs a signed verdict** (`ticket.verdict` that makes a ticket Done, and the agent finish under the recorded `agents_may_finish` grant).
**Invariant V1:** on a machine a ticket counts as Done only when it carries a verdict entry whose MAC is THIS core's own `verdict1` MAC over the
ticket's current state AND is the CURRENT entry of this core's verdict ledger; every other raw `done` (an agent wrote it into the file, a peer
brought it in through sync) is **Review** there. It is decided in one function (`humanproof.verdict_ok`, reference `verdict_is_human`, vectors
`verdict`), applied in ONE read path (`tickets._effective`, called by `load` and `list_all`) and ONE write guard (`tickets._write`). The record
is HMAC-SHA256(`human.key`, `"verdict1." + workspace id + "." + ticket id + "." + canonical JSON of {status, kind, checks, nonce[, person, at, line]}`), base64url:
`status` is always `"done"`; `kind` is `"person"` (a proven verdict: page or terminal proof, the phone through the relay channel, the dev test
human) or `"agent"` (an agent finished while the recorded grant was effective); `checks` is the sha256 hex of canonical JSON
`[[step id, text, done is true, wont_do is true], ...]`, WHAT was accepted (a new, reworded or reopened step makes the verdict stop verifying, so
the ticket is Review again; title, note, summary, outcome, history and evidence are not bound); `nonce` is 16 random hex, fresh per signing; `person`, `at` and `line` (only on a `kind: "person"` entry signed from #484 on, always all three, otherwise absent, never `null`) are the actor (`human:<name>`, at most 64 characters, the pattern `humanproof.ACTOR_PATTERN`) the UTC time of the signing and the digest of the history line the signing operation wrote, **inside the MAC**, so changing, adding or removing any makes the entry stop verifying. A
different prefix from `pending1` and `wontdo1`, so the MACs can never be confused. The ticket stores `verdicts`: a list of at most 8
`{kind, nonce, mac}` plus the optional `person`, `at` and `line` (`humanproof.VERDICT_FIELDS` + `VERDICT_OPTIONAL`, the single source the sync merge copies and a test drift-checks; a list, because a MAC can be checked only by the machine whose key made it: two machines that both accepted keep both
entries, and one machine's signing never erases another's). **Freshness is the ledger's job:** `keys/<ws>/verdict.json` in the guarded home
(`{"schema": "orch.verdict-ledger/1", "entries": {"<ticket id>": "<current mac>" | null}}`, 0600, written under the key lock, separate from
`wont.json`) holds the CURRENT MAC per ticket; a MAC is accepted only when it IS the current entry, so replaying an older signed verdict, or the
same file content after a reopen, does not verify. A missing, loose or damaged ledger vouches for nobody (fail closed); signing into a damaged
ledger is refused with a plain message and nothing is half written. **Leaving Done needs no proof** (more work, never less): whenever the core
writes a ticket whose status is not `done`, and whenever it reads a ticket whose file is not `done` (an agent edited it to active or review),
it tombstones that ticket's entry (null) at that moment, so "edit to active, then back to done with the old verdict" is Review.
Readers never rewrite the file: a raw `done` without a current verdict is shown as `review` with a computed `verdict_needed: true` (never stored);
the writers keep a peer's raw `done` as it is while an unrelated op runs. Who signs: a person with a verified proof (the CLI `_verdict_who`
returns `(who, proven)`; the phone through `relay._apply_review_answer`, the relay channel being the phone's proof), or an agent only while
`agents_may_finish` is effective as a recorded grant (kind `agent`; revoking the grant later does not undo earlier agent Done tickets, new agent
finishes go to Review); everyone else is refused, never an unsigned Done. **Sync:** `merge_ticket(..., verdict)` (`verdict(entry, ticket)` =
`humanproof.verdict_verifier`: `"current"`, `"stale"` for the core's own MAC that is no longer current, else none; no verifier = nobody) never
decides Done. `status` keeps the plain rule (both changed: FINAL wins; done with an open step: active); a peer's reopen wins by the normal
three-way rule (lowering needs no proof, and the write that applies it tombstones the ledger entry). `verdicts`: every entry the core vouches for
is the authority and is always kept, never changed or dropped, whatever a side did; the core's own stale entries are dropped; every other entry
(another machine's, or one that cannot be checked here) is merged three-way by `mac`, deduplicated, sorted by `mac`, and capped so the total is
at most 8, so the output is byte-identical with the sides swapped (vectors `ticket-merge-v1.json` rule `verdict`; a test fails if
`orch_sync.merge` has drifted from `humanproof.VERDICT_FIELDS`). A Done made on another machine is Review here until a person
here clicks Looks good (its MAC cannot be checked here: the same limit as a synced Won't do). A verified Won't do counts as resolved in `checks`;
a Won't do the merge drops reopens its step, so the ticket is active and the verdict stops verifying. A peer agent's `kind: "agent"` entry never
verifies here (the grant is ours).

**Person history lines over sync (#484, F3).** Sync history attribution is directional (upstream = remote, mine = local). A history line that is
in neither the base nor on this machine is **remote-only**; unless its `by` is a plain `agent:` label it is shown as `agent:sync` with the text
prefixed "(synced, not verified here) ", EXCEPT when it is the line of a decision that is **new** in this merge. That means ALL of: (1) a decision
THIS core verifies (a verdict entry the verdict verifier calls `current`, or a Won't do whose MAC is the current ledger entry) that carries a
MAC-bound actor, time and line (`person` + `at` + `line` / `wont_by` + `wont_at` + `wont_line`) and was not already verified in the base or on this machine; (2) the line's
`by` equals that actor; (3) its `{text, via}` is EXACTLY the line the decision's MAC binds (`line` = sha256 hex of canonical JSON `{"text", "via"}`, written by the signer from the history line its own operation adds, `humanproof.history_digest`; any other text, e.g. a "Patched <other fields> (status ... -> done)" line, or another `via` is not attributed); (4) its shape is the writer's exactly (only `at`, `by`, `via`, `text`, `chat_message` false; a `lost` field, `chat_message: true` or any other key means it is not the writer's line); (5) its `at` is within 5 seconds of the decision's `at`, and when several
lines qualify the one closest to it is the decision's; (6) at most ONE line per decision (a replay, or a second line citing it, is demoted).
**Legacy** decisions (no actor: signed before #484) still verify Done and Won't do exactly as before but authorise no history line. No migration:
decisions signed from now on carry the actor. The step's plain `by` and `at` are the peer's input and never decide authorship. **Never demoted:**
the person's own lines already on this machine, even unpushed ones (a returning demoted copy does not erase them). **Known limit (origin
convergence):** a line that cannot be verified keeps its original on the machine that wrote it while the peer shows it demoted, so the two copies
differ in that one line's attribution; history is display only and never an authority. Every other field merges byte-identically with the sides
swapped (vectors `ticket-merge-v1.json` rule `person-history`). No migration: a raw `done` from before this core has no entry and shows as Review once; the person's Looks good
signs it.

**What a machine shows as the person (PR B).** Once sync is enabled for a workspace, every person field of a ticket
(history lines, evidence, Won't do and verdict persons, answers, references, plan and description authors) is shown
through ONE rule, `orch.history.shown_ticket`: as written only when this core created that exact object here (its
digest in the local1-MAC'd own-lines store, registered at core's single append points, never by diffing files) or a
decision this core verifies binds it (the decision's line matched once); otherwise as `agent:sync` "(synced, not
verified here)". A workspace that never enabled sync is shown exactly as before. Full rule: contracts/history.md.

**Action records (PR B).** A record an add-on keeps in the agent-writable workspace about a person's decision carries
this core's MAC: HMAC-SHA256(`human.key`, canonical JSON (sort_keys, `,` `:`, UTF-8, no NaN) of the array
`["action1", workspace id, target, record]`), base64url (`humanproof.action_sign` / `action_is_human`). The array
form leaves no delimiter a target or a record could forge. It is made right after the CLI's gate (`person_by` with
the decision's proof target where the decision needs a person) and checked again EACH time the record is used; an
edited, moved or planted record verifies for nobody. A record that may be used only once carries a random `id`
(16 bytes, base64url); once applied, the id is spent in `<guarded orch home>/keys/<ws>/actions-used.json` (under the
key lock, the newest 5000 kept, `humanproof.action_spend`), and a spent id never counts again, even planted back. An
unreadable store counts every id as spent (fail closed).

The sync add-on's records (`orch_sync.records`, each `{..., kind, target, id, mac}` with the action target
`sync-record:<kind>:<target>`):

| file in `.orch/run/sync/` | kind | target (what it is bound to) | used |
|---|---|---|---|
| `choices.json` `files[<path>]` (keep, at, `covers`, local, incoming, sha256 of the chosen bytes) | `choice` | `<reviewed remote commit>:<path>` | while the remote stays; the chosen bytes must hash to `sha256` |
| `checked-files.json` `[<path>]` | `file` | `<path>:<sha256 of the allowed bytes>` | each scan of exactly those bytes |
| `allow-delete.json` `[<ticket>]` | `delete` | `<ticket>` | once (spent when the removal is staged) |
| `ignored.json` `[<ticket>][<add-on>]` | `ignore` | `<ticket>:<add-on>:<value sha256>` | while that value waits |
| `approved.json` `[<ticket>][<add-on>]` | `allow` | `<ticket>:<add-on>:<value sha256>` | once: approve writes the value and spends the id at once; no merge ever reads it, so an approval is never replayed (#540) |
| `left-out.json` `[<path>]` (path, sha256) | `left-out` | `<path>:<sha256 of the bytes left out>` | each stage of exactly those bytes at that path (an artifact of this computer stays local; changed bytes ask again) |

The dashboard reaches these choices through its one generic op (`orch sync act <verb> -- <target>`, a person's
proof with `--proof-stdin`): `keep-mine` / `keep-theirs` (= `resolve`), `leave-out` (target
`sync:leave-out:<sha256 of path NUL bytes>`), `allow` / `ignore` (= `approve`), `leave-deleted` (= `deleted`) and
`use-public` (target `sync:use-public:<sha256 of the address>`: the person's signed choice to sync to an address the
visibility probe found public; until then that address waits in `pending-public.json`, a local1 record (kind
`sync-pending-public`) only `act set` writes after the person's set-remote proof; an unverified one counts as absent,
and use-public reads it once, under the step lock) and `set` with an address (target
`sync:set-remote:<sha256 of the address>`). Choosing or changing the remote address is always a person's signed
choice, checked in `cli.apply_set` for every path (`orch sync set --remote`, turning remote on with the stored
address, `act set`, `use-public`): the visibility is probed every time (the `visibility.json` cache only words a
notice), a public address needs `sync:use-public:` (plain `set`: `--public`), any other `sync:set-remote:`. Mode
off, mode local and the interval need no proof. The address such a choice applies is recorded in
`run/sync/address.json` (`{sha256: <sha256 of the exact address>, mac}`, a local1 record of kind
`sync-remote-address` only `cli.apply_set` writes, after the proof). `settings.json` is plain JSON any process can
write, so it is checked at the point of use: the sync step and every remote-mode network path (fetch, ls-remote,
push; the history pause's own look; the pause choices) use the remote only when `settings.json`'s address is the one
a verified record names. Else no network call at all: `last_error` is "Sync address not confirmed: choose it again
in Settings" and a `sync:address` Needs row shows (fail closed; the dashboard's same-address shortcut, only how
often, does not apply to an unconfirmed address, so choosing it again is signed).
`orch sync act <verb> --proof-target -- <target>` answers `{target, review}`, changing nothing: the target the proof
must name (or null) and what the sign step shows (`title`, `body`, `here`, `there`, `value`: the address without a
login, the held value as clipped plain text with its byte count, every differing ticket key, the file name and
size, the deleted ticket's title and id), both from the same read of the same bytes. The page shows that review
(never the row's text), then sends the signed click with the target it showed (`seen`); the page server mints only
`addon.act` proofs whose target starts with the add-on's own name AND equals `seen`, and the verb checks the
target again when it runs. A core op in a Needs row (`private.move`, sync rows only) always uses the dashboard's own
wording.

**Local records.** A local integrity record no person signs carries the core's local1 MAC: HMAC-SHA256(`human.key`,
canonical JSON of `["local1", workspace id, kind, record]`) (`humanproof.local_sign` / `local_ok`), a domain that can
never pass as an action record. Kinds: `own-lines` (history.md), `sync-enabled` (the enabled record), `sync-held` (a
held add-on change in `run/sync/held/<ticket>-<digest>.json`: read per ticket, at most 512 in all, an unverified file
is removed and shows nothing; a candidate goes when the other computer goes back to this machine's value) and
`sync-paused` (the pause in `run/sync/state.json`: files, reason, kind, remote; an edited or planted pause is no
pause, so a reason that lowers what needs a proof never counts), `sync-local-ext` (`run/sync/local-ext.json`,
`{schema: "orch.sync-local-ext/1", tickets: {<ticket>: {<add-on>: <value sha256>}}, mac}`: this machine's own
add-on values of every ticket sync received; started empty only when sync is first turned on here, never again
once removed or broken) and `automation-local-blocks` (`addons/automation/local-blocks.json`,
`{schema: "orch.automation-local-blocks/1", tickets: {<ticket>: <block sha256>}, mac}`: blocks the automation
add-on wrote here). The MAC covers the whole file but `mac`. **Pinned (no rollback):** both carry a `counter`, and
the guarded home (`keys/<ws>/record-pins.json`, `humanproof.pin_next` / `pin_ok`) keeps per kind the current counter
(only ever up) and the sha256 of the one current body; a body whose counter or digest is not the pinned one (an older
signed copy, e.g. the empty first-start record; a crash between the pin and the write; a missing pin) does not
count. `local-ext.json` is started only when neither the file nor a pin exists. **Fail closed:** once sync is on,
automation treats a missing, edited, planted, rolled back or unreadable `local-ext.json` as "no synced value is
approved" and starts nothing from an automation block; a ticket not in the current record counts as created here
only when it shows no sync traces (ext.sync, a line by `agent:sync`); an unverified `local-blocks.json` blesses
nothing.

**Answers as authority.** Once sync is on, an answer acts on this machine (`relay.apply_allow_answers`: a
relay:allow question) only when `history.answer_proven`: the "Answered <id>: <answer>" line of exactly
`answered_by` and `via` is in this machine's own-lines store (made here by `tickets.answer`, which the dashboard,
phone and relay paths use), for any label, an agent's too. The proof is for the stored question at the SAME place
as the shown one, of kind relay:allow, with the very same answer word; a ticket with two questions of one id
applies nothing (one note). An allow already given here for that message (`orch relay allow`) only marks the
question applied: it never proves a (maybe synced) answer word. A synced answer is not applied (it shows as
`agent:sync`); the ticket gets one note naming `orch relay allow` / `orch relay done`.
The message an answer allows is never read from the synced `ext.relay`: when the question is asked here with sync
on, the guarded home records `(ticket, question) → allow_message` (`keys/<ws>/relay-allow.json`,
`humanproof.relay_allow_set`; a recorded message is never replaced; enabling sync adopts the questions already asked
here, with the ticket's `allow_applied`) and the answer is applied only when the ticket's `allow_message` is that
one; "applied" is recorded there too, BEFORE anything is applied (never reset; not recordable: nothing applied), so
a peer that swaps `allow_message` or clears `allow_applied` applies nothing. Once sync is on, a question with no
record here applies nothing. Sync-free: nothing is written to the guarded home; `allow_applied` decides, as before.

**take-remote** (`orch sync take-remote --proof-stdin`, a person only, `addon.act`): the way out of a HISTORY pause
(several merge bases, or none outside a machine's first join). It is the normal merge authority with this machine's
HEAD as the base: per ticket `merge_document(head, head, theirs with this machine's key, Done and ext.sync)`, the
counter only up, the reach gate, key renumbering, the tree checks and the deletion gate, ALL before the proof. The
target is `sync:take-remote:<paused remote commit>:<tree>`, the exact tree then committed and applied.

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
- Verdicts verifiable on other machines: per-person or per-device signing keys, public keys pinned in each guarded home (for example Ed25519 enrolled at pairing). Today a Done made elsewhere is Review here until a person here clicks Looks good.
- An agent reading `human.key` or editing `verdict.json` directly (same OS user, the Level 1 honest limit).
- `dropped` is not gated: an agent can still drop a ticket (hides it as closed). It is not a Done; the same signed gate for `dropped` is a Level 1 follow-up.
- An OS sandbox for agents (Level 2 epic, owner decision R1).

## Honest limit (Level 1, owner decision R1)

An agent runs as the same OS user. One that deliberately reads `human.key` despite the deny rules can mint proofs, the same
way it could read keys. H1 removes the trivial paths (flags, env, workspace files, argv, a forged click from another
origin); it is not a wall against a hostile agent. An agent that scripts HTTP against the local page (reading the launch
token from the key folder, or racing the person for it) can get proofs the same way. No OS sandbox is planned.
