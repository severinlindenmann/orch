# Keys: `orch secret` (Level 1)

Keys (tokens, passwords, key files, JSON credentials) live outside the workspace in orch's own per-user folder. They go
straight to the command that needs them (as a variable, a temporary file, or a whole command run by orch), never through
the agent's chat. Every use is recorded (which key, profile, ticket, skill), never the value. Every record writer hides the
exact key values.

Schema: `secrets.schema.json` (`$defs/profiles`, `keys_file`, `key_entry`, `list_answer`). Examples: `examples/secret-profiles/`
(TOML), `examples/secret-keys/`, `examples/secret-list/`. Vectors: `vectors/secrets-v1.json` (hiding incl. chunk
boundaries, encodings and error text; `get` rules; name resolution). T0: `… contracts/validate.py secrets`.

## Honest threat model (owner decision R1: Level 1, no OS sandbox)

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

## Where

```
<orch home>/keys/                         0700. <orch home> = addons.home() (~/.orch-tool, or a trusted ORCH_HOME)
  <workspace local id>/                   0700, one folder per workspace (.orch/.local-id); a copy or clone has none
    keys.json                             0600, $defs/keys_file: {"schema": "orch.keys/1", "keys": {"<name>": {type, source, value|file, added_at}}}
    files/<name>                          0600, key-file values (≤ 1 MB)
    profiles.toml                         0600, $defs/profiles: names only
```

- POSIX: folders 0700 and files 0600, checked on every read; looser rights, another owner, or a symlink anywhere on the path
  → refused (`Refused: the key folder has the wrong rights. Fix: orch doctor`). Windows: an ACL with only the user and
  SYSTEM, set at creation, checked the same way.
- Writes: new file + rename, under `keys.lock` (O_EXCL). Read once per command; never cached on disk elsewhere.
- **Sources.** `workspace` = added by a person on this computer. `admin` = assigned by the relay admin and written by
  `orch relay refresh` straight into this folder (replacing `.orch/secrets/credentials.json`, slice 1.1; an interrupted
  refresh keeps the old keys: write all into `keys.json.new`, rename once). Admin keys are read-only here ("Managed by your
  admin"). Same name in both: the workspace key is used and `list` shows the admin one as `shadowed`.

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
plain non-secret variables (`set`), may name its one command (`run`), and may allow `get` (`allow_get`, default false).
Variables that change how programs load are refused (`$defs/env_name`: PATH, LD_*, DYLD_*, GIT_*, ORCH_*, …). Profiles are
made by a person (dashboard, or `orch secret profile`); an agent may not change them.

## Commands

All take `--json` and follow the CLI contract (cli-answer.schema.json). The child's exit code is passed through.

| Command | Does |
|---|---|
| `orch secret env <profile> -- <command> [args…]` | Runs the command with the profile's `env` + `set` variables. |
| `orch secret file <profile> -- <command> [args…]` | Writes each `files` key to a temp file (0600, in `<orch home>/keys/tmp/<random>/`, deleted when the command ends, also on Ctrl-C; stale ones are swept on the next call), sets the variables to the paths, then runs the command. `{file:VAR}` in an argument is replaced by that path. |
| `orch secret exec <profile> [-- extra args…]` | Runs the profile's own `run` command with `env`, `files` and `set`; extra args are appended. Refused when the profile has no `run`. Every connection (MCP server) orch starts goes through this (inventory.md). |
| `orch secret list [--json]` | Names, types, sources, profiles, state, last use: `$defs/list_answer`. Never a value. |
| `orch secret get <profile> <key>` | Prints the value on stdout, for scripts. Refused unless the profile has `allow_get = true`, the key is in that profile, and stdout is **not** a terminal (a live session's screen would show it). |

Person-only (refused for agents; also in the dashboard): `orch secret add <name> --type T [--file F]` (value from stdin, never
an argument), `orch secret remove <name>`, `orch secret profile <name> …`. These are additions to the five agent commands.

- **Hiding the child's output.** stdout and stderr of the child go through pipes and the streaming hider (below) before they
  reach the caller. Interactive programs see pipes, not a terminal; that is accepted.
- **No shell.** argv is run as given; orch never builds a shell line from a key.
- **key.use.** One event per key per call, written before the child starts (activity.md `key.use`: `used.action` = env ·
  file · exec · get, `data.profile`, `data.command` = the program's base name, `data.skill` from `ORCH_SKILL` when set).
  A refused call writes `outcome.ok: false` with `data.refused`: `not_in_profile`, `get_off`, `get_to_terminal`, `missing`.
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
- **Error paths**: exception messages, tracebacks (exit 1), stderr of failed children, refusals and HTTP error bodies go
  through the same hider before they are printed, logged or recorded. A writer that cannot get a hider refuses
  (activity.md, Fail closed).
- Known limits (Level 1): a value transformed in another way (encrypted, compressed, reversed, other encodings, split by colour codes or line wrapping on a
  terminal) is not found; the screen stream hides values before the terminal draws them, not inside escape sequences.

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
