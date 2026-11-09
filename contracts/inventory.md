# Inventory: skills, connections, keys (`orch.inventory/1`)

What a workspace can use, with where it comes from, by name. Focus's Used tab, Insights and the check-up read it; the
counts (counts.md) join it so that something never used shows as "not seen" instead of disappearing.

Schema: `inventory.schema.json` (`$defs/inventory`, `connection`, `conn_page`, `mcp_file`). Examples: `examples/inventory/`,
`examples/mcp-file/`. Vectors: `vectors/inventory-v1.json` (version hashes, precedence). T0: `… contracts/validate.py inventory`.

Words on screens (owner decision R4): Skill · Tool · Connection · Key. "MCP" and raw names only under Details.

## Names only

The inventory never holds a key value, an environment value, a header, a URL path or query, or a full command line. A
connection shows the program's base name (`npx`, `uvx`, `gdrive-mcp`) or, for http, the host. Keys show name, type and source
(secrets.md).

## Sources and precedence

| Thing | Sources (winner first on the same name) | Where orch reads them |
|---|---|---|
| Skill | `workspace` > `admin` > `marketplace` > `builtin` > `harness` | `.agents/skills/*` (admin ones carry `.orch-shared`, orch's own are `orch`/`orch-<add-on>` = builtin or marketplace), the agent tool's own user skill folder (names only, read only) |
| Connection | `workspace` > `admin` > `harness` | `.orch/mcp.json` (`$defs/mcp_file`); admin: the relay refresh, stored in the key folder (`<orch home>/keys/<ws>/connections.json`, because admin configs may carry keys); harness: the agent tool's own settings (listed, read only, never changed) |
| Key | `workspace` > `admin` | the key store (secrets.md) |

**How a source is decided (P1: anything unproven is `workspace`).** A skill or connection is `admin` only when its name and
version match an item of the last relay refresh as recorded by the core in the trusted orch home (not the workspace's
`.orch-shared` marker, which anyone can write); `builtin` only when its content hash equals the one in the manifest shipped
with the installed orch; `marketplace` only when name and hash match the official public marketplace index (a private or local
add-on is `workspace`); `harness` only when orch read it from the agent tool's own settings. A folder named `orch-x` that orch
did not ship is `workspace`. Since `workspace` and `harness` names stay hidden at the admin (usage-counts.md), a spoofed marker
or name never sends an own name out. Reference `inv_classify`, vectors `classify`.

Both entries of a name are listed; the loser has `shadowed: true`. Insights shows both with the active one marked.

## Connections

- **This workspace** (`.orch/mcp.json`, may be committed): `servers.<name>` = `{command: [argv], profile?, label?}` or
  `{url: "https://…", profile?, label?}`. No `env`, no headers: a key comes only through `profile`.
- **Starting.** Every connection orch passes to an agent (workspace and admin) starts as
  `orch secret exec <profile> -- <argv>` (or with no profile, `<argv>` directly), so no key sits in a config file or on a
  command line. Harness connections are started by the agent tool itself, as before.
- **Allowed actions.** `.orch/mcp.json` `allow.<name>` = `"*"` or a list of action names, for connections of every source.
  A connection without an entry has **no** action allowed in orch-started runs; the Used tab and Insights show "Not allowed
  by this workspace" with a one-click Allow (writes the entry, with a `conn.allow` proof). An `allow` entry an agent writes into
  `.orch/mcp.json` by hand counts only when it matches a grant the core recorded with a proof (`<orch home>/human-settings.json`,
  key `conn.allow.<name>`); otherwise the action stays not allowed. The adapter turns the list into the agent tool's own allowed
  tools list; a call outside it is a `denial` event.
- `orch conn list --json` → `$defs/conn_page` (all sources, `shadowed` marked). `orch conn show <name> [--source S] --json` →
  one `$defs/connection`. `orch conn allow <name> <action>… | --all [--off] --json` → the updated connection (a person only:
  `conn.allow` proof from the human channel, invariant H1, human-proof.md).

## Versions (content hashes)

`version` = `sha256:` + 64 hex. The record stores the version at the time of use (activity.md `used.version`), so a changed
skill starts a new line in Insights and a proposal can be rolled back to an exact version (proposal.md).
- **Skill**: walk the skill folder; skip names starting with `.` (`.orch-shared`, `.orch-copy`, `.DS_Store`) and symlinks;
  sort files by their relative POSIX path (byte order of UTF-8); for each, feed `path` + `\0` + sha256-hex of the file
  bytes + `\n` into one sha256.
- **Connection**: sha256 of the canonical JSON of its server object (`sort_keys`, separators `,` `:`, UTF-8, no ASCII
  escaping), after dropping `env` and `headers` (harness configs may have them; they are never hashed or shown).
Reference: `inv_skill_version` / `inv_conn_version` in validate.py.

## The inventory document

`{"schema": "orch.inventory/1", "generated_at", "skills": [...], "connections": [...], "keys": [...]}`, embedded in
`orch record counts --json` (counts.md) and given to the check-up as data.
