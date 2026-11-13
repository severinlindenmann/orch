# Keys: `orch secret` (Level 1)

Keys (tokens, passwords, key files, JSON credentials) live outside the workspace in orch's own per-user folder. They go
straight to the command that needs them (as a variable, a temporary file, or a whole command run by orch), never through
the agent's chat. Every use is recorded (which key, profile, ticket, skill), never the value. Every record writer hides the
exact key values.

Schema: `secrets.schema.json` (`$defs/profiles`, `keys_file`, `key_entry`, `list_answer`). Examples: `examples/secret-profiles/`
(TOML), `examples/secret-keys/`, `examples/secret-list/`. Vectors: `vectors/secrets-v1.json` (hiding incl. chunk
boundaries, encodings and error text; `get` rules; name resolution). T0: `… contracts/validate.py secrets`.

## Honest threat model (owner decision R1: Level 1, no OS sandbox)

The boundary of human-proof.md applies (goal: no acting as the person through orch's own interfaces; non-goal: direct
tampering with orch-home files or the install).

Level 1 **stops accidents and leaks**: a key pasted into a chat, printed in a log, written into the record, synced to a cloud
drive with the workspace, committed to git, shown on a page or sent to the phone. It **does not stop an agent that
deliberately searches the disk**: an agent runs as the same user and can read the key folder despite deny rules, can run
`orch secret env <profile> -- sh -c 'echo $X | base64'`-style tricks around value hiding, or can send a key to a server.
No OS sandbox is planned. The wording on screens and in skills never says keys are "safe from agents"; it says "kept out of
the workspace, records and chats".

What Level 1 does:
1. Keys outside the workspace, owner-only rights (below). Never in `.orch/`, never in git, never in a synced folder.
2. Keys go to the command, not to the agent: `env`, `file`, `exec`. `get` (prints a value) is off by default per profile.
3. The child's stdout and stderr pass through the hider before the agent sees them.
4. Every writer (record, detail files, logs, run logs, errors, pages, screen stream, phone snapshots) hides exact values.
5. Deny rules for the key folder in the agent tools' own permission settings (agents.json data, written per run).
6. Every use is a `key.use` event (activity.md). A refusal is one too.

## Deny rules (slice 1.4, Level 1)

orch adds deny rules to the agent tool's own permission flags on **every start** (fresh and resume, oneshot and live, every
permission mode including `full`), generated for the workspace from the data in `agents/deny.json` (`deny` of the adapter).
The deny **set** is the same for every adapter; an adapter only says how its tool can be told (`deny.format`).

| root | path | agent's own file tools | agent's shell (command text naming it) |
|---|---|---|---|
| `home` | every guarded orch home candidate: `humanproof.guarded_home`, `ORCH_HOME`, `<account home>/.orch-tool` | no read, no write | refused |
| `secrets` | `<workspace>/.orch/secrets/` (old key files) | no read, no write | refused |
| `record` | `<workspace>/.orch/record/` | write refused, read allowed | refused (reading goes through `orch record ...`) |
| `local-id` | `<workspace>/.orch/.local-id` | write refused, read allowed | refused |

`home` covers the key store, key files, `profiles.toml`, `human.key`, the nonce store, `human-settings.json`,
`proposals.json`, `permissions.json`, `agent-approvals.json` and the relay and dev records. Never denied: the workspace
itself, `.orch/` tickets, `.orch/run/`, anything `orch ...` prints. A shell command is refused when its **text** contains
a path form; orch commands never contain one, so `orch record query` and `orch secret env <profile> -- ...` work.

**Format `patterns/1`** (tools with `--disallowedTools`, i.e. Claude Code): one comma-joined value merged into the tool's
disallowed-tools flag (any spelling in the existing flags, `--disallowedTools X`, `--disallowed-tools X`, `--disallowedTools=X`, is
merged into one; an existing list is extended, never replaced; added when there is none). The rules are added whatever the permission
mode, including `full`. Without a workspace orch **refuses to start** such a tool. The tool that is really started must be found and report a version of
2.0.0 or newer (patterns with `*` inside, `Read(//..)`); not found, no output, unreadable output and older all **refuse** (deny by
default, no override): `Claude Code is missing or too old on this computer. Install or update it, then press Continue.` The one flag is placed
**last** before the `--` that precedes the prompt (it takes a list, so nothing positional may follow it).
- Candidate homes, always: `<account home>/.orch-tool` and `ORCH_HOME` (when set), plus the guarded/trusted home when it resolves. A
  candidate that is or contains the workspace **refuses the start** (`orch's folder contains this workspace: move the workspace out of it,
  then try again.`): it cannot be denied without denying the workspace. A home inside the workspace is fine (only that folder is denied).
- file tools, per root path P (`/**` and P itself): `Read(f)` (rows with read denied only) and `Edit(f)` (every row; it covers
  every tool that changes a file, so there is no `Write` rule) for each form f of P: absolute `//<P without its leading />`; Windows
  drive form `//c/Users/..` and `C:/Users/..`; `~/<rest>` when P is under the account home; `./<rest>` when P is under the workspace
  (no `../` forms: not valid file patterns). Real path and as-given path (symlinked temp folders) both.
- shell: `Bash(*<text>*)` for each text form of P: forward-slash and backslash absolute, `~/<rest>`, `$HOME/<rest>`,
  `${HOME}/<rest>`, `$env:USERPROFILE\<rest>` and `%USERPROFILE%\<rest>` (PowerShell, cmd), relative to the workspace (incl. `../..`),
  and for `home` the folder's own name (at least 6 characters, e.g. `.orch-tool`, `orch-tool`) and `<parent>/<name>`.
  `record`/`local-id`/`secrets` also the workspace-relative text `.orch/record` (and `.orch\record`, ...).
- `,` `(` `)`, spaces and control characters in a path become `*` (a wildcard in both rule kinds: never a split list, never a
  literal). That over-blocks a few look-alike paths and never under-blocks the real one. Nothing is read from the workspace's own settings.
- **Over-blocking:** a shell command that mentions the home folder's own name (any text containing `orch-tool`) or merely mentions `.orch/record` or the home folder's name (an `ls`, a `grep` for it) is
  refused. **Under-blocking:** matching is exact text and case-exact (a case-insensitive file system lets `.ORCH-TOOL` through),
  a symlink inside the workspace that points at the home is not followed, and variables, globs, `cd` plus a short name, or a built path
  are not seen.

**Format `none`** (`codex`, generic commands): orch cannot tell the tool. codex's own `workspace-write` sandbox keeps *its
writes* inside the workspace (and `store_args`): only that sandbox protects the home from writes, and only while it is on (a
person's own config can change it). **Reads of `home` and writes of `.orch/record` are not enforced** (Level 1: stops
accidents, not a tool that deliberately goes there). Vectors: `vectors/deny-v1.json`.

## Where

```
<orch home>/keys/                         0700. <orch home> = the guarded orch home of the workspace (below)
  <workspace local id>/                   0700, one folder per workspace (.orch/.local-id); a copy or clone has none
    keys.json                             0600, $defs/keys_file: {"schema": "orch.keys/1", "keys": {"<name>": {type, source, value|file, added_at}}}
                                          the keys a person added (source workspace)
    admin-keys.json                       0600, same shape, source admin: written only by `orch relay refresh`
    files/<name>                          0600, key-file values (≤ 1 MB)
    profiles.toml                         0600, $defs/profiles: names only
    record-heads/<run>.json               0600, the chain head of one run's record (activity.md, Authenticated record), MACed with the record
                                          subkey derived from human.key (HKDF-SHA256, domain orch.record/1), never with human.key itself
```

- **Guarded orch home (decision N11/N14, rationale below).** The key store, the hider, `human.key`, the nonce store,
  `human-settings.json`, `proposals.json`, the relay record and the dev record live in the *guarded home* of a workspace:
  - a **real workspace** uses only the account's default home, `<account home>/.orch-tool`, where the account home comes
    from the account database (`pwd.getpwuid`; Windows: the profile folder from the OS), never from `HOME` or `ORCH_HOME`;
  - a **test workspace** uses only a test home (`ORCH_HOME`, else `HOME/.orch-tool`, that is itself a test path);
  - any other pairing → guarded operations are refused (`Refused: this workspace and this orch home don't belong
    together.`); there is no silent fallback in either direction.
  **Test paths exist only on a test or dev install.** The install record inside orch's own tool environment says `normal`,
  `dev` (the dev kit's installer) or `test` (running from the source tree, as the test suite does). On a **normal install there
  is no test path at all**: every workspace is real and only the default home is guarded. On a dev or test install the one test
  prefix is the literal `<account home>/.orch-test/`, and it counts only when it `lstat`s as a real directory (not a symlink)
  owned by the user. A workspace or home is a test path when its **realpath** lies under that literal prefix, compared
  path component by component (`~/.orch-testX/` is not under it; the prefix itself is not resolved, so a `.orch-test`
  symlink to `~` makes nothing a test path). Reference `home_ok`, vectors `home` (human-proof-v1).
  **Rationale.** Tests and e2e keep isolating with `env -i HOME=~/.orch-test/… ORCH_HOME=…` and never read or write the real
  `~/.orch-tool` (owner rule): they run from the source tree or a dev install, and their workspaces and homes are real
  directories under the prefix; the check reads nothing in the real home. Home pinning always has a test-safe mode that is on in the test environment: on a test install a real workspace never pairs with the account's orch home (guarded ops refused), and the test suite fails on any change under the real orch home. On a pilot user's normal install an agent cannot
  get a second, agent-made human key by moving a workspace under `~/.orch-test`, linking paths, or setting `HOME`/`ORCH_HOME`:
  there is no test path, so a non-default home is simply refused. **It does not stop** editing the install record or files in
  the default orch home directly (outside the boundary above); on a dev or test install, a workspace under the prefix is a
  test workspace by design.
- POSIX: folders 0700 and files 0600, checked on every read; looser rights, another owner, or a symlink anywhere on the path
  → refused (`Refused: the key folder has the wrong rights. Fix: orch doctor`). Windows: an ACL with only the user and
  SYSTEM, set at creation, checked the same way.
  (orch.winacl; the ACL is set before any secret is written). A loose key file is set aside, never trusted.
- *Implementing slice 1.1 must* bind `.orch/.local-id` to the workspace's real path in the guarded orch home and refuse a
  mismatch (the id file is workspace-writable).
- Writes: new file + rename, under `keys.lock` (O_EXCL). Read once per command; never cached on disk elsewhere.
- **Sources.** `workspace` = added by a person on this computer. `admin` = assigned by the relay admin and written by
  `orch relay refresh` straight into this folder (replacing `.orch/secrets/credentials.json`, slice 1.1; an interrupted
  refresh keeps the old keys: write all into `admin-keys.json.new`, rename once; workspace keys stay in `keys.json`). Admin keys are read-only here ("Managed by your
  admin"). Same name in both: both are stored, the workspace key is used and `list` shows the admin one as `shadowed`; removing the workspace key makes the admin one active again.

## Key types

| type | value | delivered as | hidden forms |
|---|---|---|---|
| `token` | one line, 8–65536 characters | variable or temp file | the value + its encodings (below) |
| `password` | one line, 8–65536 characters | variable or temp file | same |
| `key-file` | file bytes ≤ 1 MB (PEM, p12, ssh key) | temp file | each text line of ≥ 16 characters, and the whole file when it is text |
| `json` | a JSON object (service account), stored as JSON text in `value` | temp file, or compact JSON in a variable | every string leaf of ≥ 8 characters + its encodings, and the compact JSON |

Values shorter than 8 characters are refused when stored ("This key is too short to hide safely in records: at least 8
characters."), because hiding a short value would garble normal text.

## Profiles (`profiles.toml`, names only)

```toml
schema = "orch.secret-profiles/1"

[profile.databricks]
env = { DATABRICKS_TOKEN = "databricks-token" }
set = { DATABRICKS_HOST = "https://adb-1234.azuredatabricks.net" }
run = ["databricks"]
skills = ["databricks-jobs"]

[profile.google]
files = { GOOGLE_APPLICATION_CREDENTIALS = "google-sa.json" }

[profile.proton]
env = { PROTON_PASS_PERSONAL_ACCESS_TOKEN = "proton-pat" }
run = ["pass-cli"]
```

A profile maps variables to key names (`env`: the value in the variable; `files`: a temp file path in the variable), may set
plain non-secret variables (`set`), may name its one command (`run`), and may allow `get` (`allow_get`, default false), and may let agents use its keys in any command (`agents_may_env`, default false).
Variables that change how programs load or where they connect are refused (`$defs/env_name`: PATH, LD_*, DYLD_*, GIT_*,
ORCH_*, PATH*, PYTHON*, PERL*, RUBY*, NODE_*, LUA_*, BASH*, XDG_*, SSH_*, GPG_*, SUDO_*, `*ASKPASS*`, `*_OPTIONS`, SHELLOPTS, PS4,
ENV, IFS, HOME, EDITOR/VISUAL/PAGER/MANPAGER/BROWSER, LESS, LESSOPEN, LESSCLOSE, LESSKEY, LESSKEYIN, LESSKEYIN_SYSTEM, LESSKEY_SYSTEM, LESSKEY_CONTENT, LESSEDIT, LESSSECURE, LESSHISTFILE, PSModulePath, CLASSPATH, PHPRC, TCLLIBPATH, R_PROFILE*, GNUPG*, NPM_CONFIG*, TMPDIR, COMSPEC, proxies, CA bundles, …; see `keystore.ENV_DENY`; matched in
any letter case; `set` names are also structural: `^[A-Z][A-Z0-9_]{0,63}$` (a `set` or `files` name must also be one the profile's own `env` declares or one a person approved in `extra`: `profile set --extra NAME`, each
matching the structural rule and the hard-deny, part of the body MAC; else `NAME is not an approved variable for this profile; add it with --extra`, at set, on every read and at run time; ordinary secret names NPM_TOKEN, NODE_AUTH_TOKEN, CARGO_REGISTRY_TOKEN, CARGO_REGISTRIES_*_TOKEN and GPG_PASSPHRASE are allowed in `env` only, never in `files` or `set`; the deny list is not complete, and the `extra` allowlist is the real control), at `profile set` AND again every time the profile is read or run). Profiles are
made by a person (dashboard, `secret.profile` proof, invariant H1); an agent may not change them. `allow_get = true` counts
only with a matching settings record (human-proof.md, Settings: records and tombstones), so editing the file alone does not enable `get`.

**The profile body is MAC-bound (W2b).** `profiles.toml` is editable by anything running as the user, so it is not trusted for
what a profile runs or receives. `profile set` (a `secret.profile` proof) stores `profile1.<workspace id>.<profile name>.<canonical
{env, files, set, run, extra}>` under the guarded human key (HMAC-SHA256, base64url) as the profile's entry in the ledger
`<guarded orch home>/keys/<workspace>/profile.json` (human-proof.md, Ledgers; `profile remove` tombstones it with `null`).
`run`, `env`, `file`, `exec` and `get` recompute it and **fail closed** on a missing or different MAC (and a missing or damaged
ledger) with `Refused: this key profile was changed outside orch; set it up again.` The switches (`allow_get`, `agents_may_env`) keep their
own settings records and are not part of the body; rewriting a switch never signs a body that was edited outside orch. `exec` also re-runs
the `run` program approval (absolute path, outside the workspace, not changeable by others, exists) when it starts.
The MAC protects against an attacker who can write `profiles.toml` but can neither read `human.key` nor write `profile.json` (same folder, same
rights: the guard is the boundary). Only the profile a person is setting (with proof) is signed; every other profile keeps its ledger entry,
and `profile remove` always writes the tombstone, even when the file has no such profile. A profile that fails verification is shown as unusable. `profile remove` first turns both switches off and writes the tombstone, then touches the file (a damaged file refuses after that). `skills` is outside the MAC (not used to decide anything).
**No legacy:** profiles saved before this change have no MAC and are refused until a person sets them up again (owner rule: no
compatibility code until the pilot cut).

## Commands

All take `--json` and follow the CLI contract (cli-answer.schema.json). The child's exit code is passed through.

| Command | Does |
|---|---|
| `orch secret env <profile> -- <command> [args…]` | Runs the command with the profile's `env` + `set` variables. |
| `orch secret file <profile> -- <command> [args…]` | Writes each `files` key to a temp file (0600, in `<orch home>/keys/tmp/<random>/`, deleted when the command ends, also on Ctrl-C; stale ones are swept on the next call), sets the variables to the paths, then runs the command. `{file:VAR}` in an argument is replaced by that path. |
| `orch secret exec <profile> [-- extra args…]` | Runs the profile's own `run` command with `env`, `files` and `set`; extra args are appended. Refused when the profile has no `run`. Every connection (MCP server) orch starts goes through this (inventory.md). |
| `orch secret list [--json]` | Names, types, sources, profiles, state, last use: `$defs/list_answer`. Never a value. |
| `orch secret get <profile> <key>` | Prints the value on stdout, for scripts. Refused unless the profile has `allow_get = true`, the key is in that profile, and stdout is **not** a terminal (a live session's screen would show it). |

Person-only, proven by the human channel (invariant H1, human-proof.md: a proof on stdin with `--proof-stdin`, minted by
the local page; done from the dashboard): `orch secret add <name> --type T [--file F]` (value from stdin, never
an argument), `orch secret remove <name>`, `orch secret profile <name> …`. These are additions to the five agent commands.

- **Who may run what (Level 1, stated plainly).** `env` and `file` hand the profile's keys to **whatever command the
  caller names**, including an interpreter (`python -c`, `sh -c`, `env`, `curl`) that can write a key to a file or the
  network. Output hiding cannot stop that; it is a best-effort safety net for accidents (a CLI that echoes its token),
  not a control against a caller that deliberately exfiltrates. Only `exec` is bound to a command a person approved
  (the profile's `run`, set with a `secret.profile` proof). Skills and screens say so in plain words. To limit this
  by default, a profile has the switch `agents_may_env` (screen wording: **"Let agents use these keys in any command"**),
  **off for every new profile and for every profile without a matching record** (deny by default). While it is off, an
  **agent** caller (an agent tool in the environment, or `--by agent:...`) of `env`, `file` or `exec` is refused unless its whole
  command equals the profile's `run` exactly: same argv, the program an **absolute path**, no extra arguments (for `exec`:
  the profile's `run` plus the arguments the agent gave; vectors `agent_env`). One gate, applied before any key is read. Otherwise: `Refused: agents may only run this profile's own command. Ask the person to allow any command, or use orch secret exec <profile>.`
  (`data.refused` = `agent_command`). An agent calling `exec` may not add arguments unless `agents_may_env` is on; a person or script caller is not restricted (exec with extra arguments stays allowed). The switch counts
  only with a settings record (secret.agents_may_env.<profile>, like `allow_get`), set by a person with a `secret.profile`
  proof, target `<profile>:agents_may_env`; `profile set` and `profile remove` turn it off. Turning a switch **off**
  (`profile get-disable`, `profile agents-disable`) needs no proof: anyone may lower it, and the record then says `reset`.
  Removing a profile has its own target `<profile>:remove` (a proof for `profile set` does not remove it). An agent that hides its
  identity looks like a script (Level 1: not a sandbox).
- **The profile's program is a full path.** `profile set` looks the program of `run` up once (the fixed system
  folders and the caller's safe `PATH` entries, never the workspace or cwd) and stores its absolute path; `exec` and the
  agent rule above never search `PATH` and refuse a stored name that is not a full path.
- **Hiding the child's output.** stdout and stderr of the child go through pipes and the streaming hider (below) before they
  reach the caller. Interactive programs see pipes, not a terminal; that is accepted.
- **No shell.** argv is run as given; orch never builds a shell line from a key.
- **key.use.** One event per key per call, written before the child starts (activity.md `key.use`: `used.action` = env ·
  file · exec · get, `data.profile`, `data.command` = the program's base name, `data.skill` from `ORCH_SKILL` when set).
  A refused call writes `outcome.ok: false` with `data.refused`: `not_in_profile`, `get_off`, `get_to_terminal`, `missing`, `agent_command`.
- Refusals are exit 2 with plain words: `Refused: the profile "billing" does not allow printing keys. Use orch secret env billing -- <command>.`
  The text names keys and profiles, never values.

## Hiding (exact values)

The hider knows every value of this workspace's key store (both sources) and runs on every string any writer writes.
**A safety net, not a guarantee.** Value hiding is best effort. The guarantee of Level 1 comes from keys going straight
to the command, never through the agent; hiding only catches what slips through (a CLI that echoes its token, an error that
prints a header).

- **Forms** (every one is required; applied once, the only nested form is url-quoted base64), for the value as UTF-8:
  1. the value itself;
  2. JSON-string escaped (`json.dumps(v)[1:-1]`);
  3. URL-quoted (`quote(v, safe="")`);
  4. hex, lower case and upper case;
  5. base64 and base64url at all three byte alignments: encode the value with 0, 1 and 2 bytes before it, drop the
     padding, and keep only the characters whose 6 bits lie wholly inside the value (characters at both ends that depend
     on neighbouring bytes are trimmed). So the value is found at any offset inside a longer encoded string, e.g. HTTP
     Basic `base64("user:token")`; the 1-2 trimmed characters at each end stay visible (at most 12 bits);
  6. URL-quoted forms of the base64 forms of 5.
  For `json` keys: the compact JSON plus every string leaf with all forms. For multi-line values: also each line of at
  least 16 characters. Reference: `sec_forms` / `sec_b64_forms` in validate.py, vectors `hide`.
- **Minimum length.** A value or form shorter than 8 characters is never hidden by exact value: hiding a short string
  would garble normal text (every "12345" in a log) and protects nothing, because a short secret is guessable anyway. The
  store refuses such values (Key types, above; vectors `min_len`, `too_short`).
- **Replacement**: `[hidden: <key name>]`. Longest match first, scanning left to right; matches never overlap.
- **Streams**: the hider keeps back the last `L-1` characters (L = longest needle) until more text comes or the stream
  ends, so a value split across chunks (pipe reads, `%output` lines, log lines) is still hidden. The streamed result equals
  hiding the whole text at once (vectors `hide`, each case is checked both ways).
- *Implementing slice 1.3/1.5 must* always hide **before** cutting (detail 1 MB cap, `text` 200/500, the 8 KB line, `log`
  cuts), then drop a trailing prefix (4+ characters) of any hidden form; add the forms `\uXXXX` (ensure_ascii), `\/`,
  lowercase `%xx` and `quote_plus`; add `human.key`, the relay workspace token and the page session cookie as needles; and
  hash or refuse an identifier field (`command`, ids) that matches a needle instead of breaking its pattern.
- **Error paths**: exception messages, tracebacks (exit 1), stderr of failed children, refusals and HTTP error bodies go
  through the same hider before they are printed, logged or recorded. A writer that cannot get a hider refuses
  (activity.md, Fail closed).
- **What approving a `run` command means.** `profile set` stores the real path of the program and refuses one inside
  the workspace or changeable by other users. It only warns when the program is an interpreter or a tool that runs
  arbitrary code (sh, bash, python, node, env, git, npm, curl, ssh, ...): approving one as `run` is the same as
  approving any command. `exec` takes extra arguments from a person or script (they are appended to the approved command); an agent
  may add none unless `agents_may_env` is on (the same exact-argv gate as `env`/`file`). Command and path are shown in the answer.
- **The command's processes end with the call.** On POSIX the child runs in its own session (when stdin is not a terminal) and,
  when the call ends or is interrupted (TERM, HUP, QUIT), everything it started is ended too (TERM, then KILL).
  Further signals during that cleanup are ignored. Pipes held by a leftover process cannot hang the call.
- **Where a use is recorded.** A use is recorded in the record of the orch run that makes it (`ORCH_RUN` +
  `ORCH_TICKET`), or in the unattributed run (below). An **agent** caller (agent tool in the environment, or
  `--by agent:...`) must be inside a live run whose run and ticket belong together (the same claim orch's own runs
  use); otherwise `env`, `file`, `exec` and `get` are refused before any key or file is touched (`Refused: an agent
  can use keys only inside an active orch run, where the use is recorded.` / `Refused: this run is not active, so the
  use cannot be recorded.`). A script that names a run that is not live is refused.
- **The unattributed run.** A person or script **without** a run is recorded in the workspace's unattributed run of
  the day: run `r_outside_<yyyymmdd>` (UTC), ticket `t_outside`, agent `main`, harness `generic`, same fail-closed
  rule. The ticket id `t_outside` is **reserved** (a follow-up makes ticket creation refuse it). A record view shows
  `r_outside_*` / `t_outside` as **"Outside a run"**. Retention ends such a run at the next 00:00Z taken from its
  **id**, never from lines in the file, so it is deleted after the keep time like any run; a day's run takes at most
  5000 lines, then further uses outside a run are refused until the next day.
- **Level 1 limits of the record.** An agent that hides its identity (no agent tool in the environment, no
  `--by agent:`, no run variables) looks like a script: its uses are recorded in the unattributed run, not limited. An
  agent can read another ticket's claim and frame its uses into that run (the record has no MAC chain). Planting a
  file at tomorrow's `r_outside_*` path stops terminal key use for that day. A switch turned off by a caller with a
  stale `ORCH_RUN` may go unrecorded (best effort). No pid-ancestor check is made.
- **Streams are not delayed.** Only the tail of the output that could still become a key is held back; the rest is
  passed on at once (an MCP server on stdio keeps working). A child without a terminal on stdin gets its own session.
  Binary key files (no text form) are hidden by the lower-case hex and the padded base64 / base64url of the
  whole file; raw bytes, upper-case hex, unpadded or line-wrapped base64 of such a file are **not** hidden (Level 1).
- Known limits (Level 1): a child can still open `/dev/tty` itself; a value transformed in another way (encrypted, compressed, reversed, other encodings, split by colour codes or line wrapping on a
  terminal) is not found; the screen stream hides values before the terminal draws them, not inside escape sequences. The approved command also reads the caller's input, folder and the user's config files (Level 1).

## Wrapper examples (a skill ships them; `orch-wrapper-maker` teaches agents to write them)

```sh
#!/bin/sh
# .agents/skills/databricks-jobs/run.sh: the agent calls this, never the CLI with a token
exec orch secret exec databricks -- "$@"          # e.g. ./run.sh jobs list --output json
```

```sh
#!/bin/sh
# .agents/skills/proton-pass/item.sh
exec orch secret exec proton -- item view --vault-name "$1" --item-title "$2" --output json
```

Values that a wrapped CLI fetches from another vault (the item above) are not in orch's key store, so orch cannot hide
them: a skill should pipe such a value into the next command instead of printing it.

```sh
# a script that needs a raw value (profile with allow_get = true), output piped, never to a terminal:
orch secret get ci-deploy deploy-token | some-tool --token-stdin
```
