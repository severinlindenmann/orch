# Blocks: `orch.blocks/1`

Results that stay (ticket Work tab, Check result, Focus job view, the phone) are drawn from the same 10 blocks on every
surface: the web kit (both copies: `workspace/src/orch_ui/static/` and the dashboard's `web/kit/`) and SwiftUI.

Schema: `blocks.schema.json`. Shared fixtures: `vectors/blocks/*.json` (one file per case, used by validate.py, the web kit
tests and the SwiftUI tests; both renderers must pass all of them to release). T0: `… contracts/validate.py blocks`.

## The document

`{"schema": "orch.blocks/1", "from": "job" | "agent" | "orch", "title"?, "blocks": [ … ]}`, at most 50 blocks and 64 KB
(compact UTF-8 JSON). `from` decides the label: `job` → "reported by the job" (never a passed check, never a Needs-you card,
job-events.md), `agent` → the agent's proof (Check result, where the person decides Looks good / Send back), `orch` →
computed by orch.

| type | fields | limits |
|---|---|---|
| `summary` | `text` (may have line breaks), `tone`? | 2000 characters |
| `steps` | `items: [{label, state: waiting · running · done · failed · skipped, note?}]` | 100 items |
| `progress` | `label`, `done`, `total` (null = unknown), `unit`? | – |
| `stat` | `label`, `value` (number or short text), `unit`?, `tone`?, `delta`? | value text 64 |
| `kv` | `items: [{key, value}]` | 50 items |
| `table` | `title`?, `columns: [{key, label, kind?: text · number · duration · date · tone}]`, `rows: [{<key>: cell}]`, `total_rows`? | 12 columns, 200 rows, cell 200 characters |
| `file` | `path` (inside the workspace), `label`?, `size`?, `preview`?: `image` | picture ≤ 2 MB and ≤ 4096 px a side, png/jpeg/gif/webp |
| `link` | `url` (https only), `label` | 2000 characters |
| `log` | `title`?, `lines: [text]`, `cut`? | 200 lines of 500 characters (tabs allowed, no line breaks inside a line) |
| `chart` | `kind: line · bar`, `title`?, `x_label`?, `y_label`?, `series: [{name, points: [[x, y]]}]` | 4 series, 200 points; x number or short text, y number or null (a gap) |

Tones: `neutral` · `good` · `warn` · `bad` (the dashboard's design-system tones). Durations are seconds, dates RFC 3339.

## Rules

- **Plain text only.** Every string is drawn as text (`textContent`, SwiftUI `Text(verbatim:)`); `<b>` stays the four
  characters `<b>`. No markup, no Markdown.
- **Links:** `https://` only, no user name or password before the host; anything else makes the document invalid. Opened in a new tab / the system browser.
- **Files:** a relative path inside the workspace (no `/` at the start, no `\`, no drive letter, no dot file or dot folder at
  any depth, so no `..`, `.git`, `.env`, `.orch`), except a ticket's own `.orch/tickets/<id>/artifacts/`. The renderer resolves
  it against the workspace root and refuses a symlink that leaves it ("file not available"). The phone gets no file bytes
  through blocks: it shows the name and size (snapshots, below).
- **Unknown block type** (a newer producer): valid, drawn as one muted row "can't show this here". A known type that breaks
  its rules makes the whole document invalid: the surface shows "These results can't be shown" and the raw JSON only under
  Details. Producers check before writing; `orch job table` refuses an invalid block with plain words.
- **Versioning:** a new optional field keeps `orch.blocks/1`; a new block type keeps it too (old renderers fall back). A
  changed meaning gets `orch.blocks/2`; renderers refuse a schema they do not know.
- **`from` is set by the core** from the channel (orch job → `job`, the agent's proof → `agent`, computed → `orch`); a
  producer's own value is overwritten, so a job cannot present its result as the agent's proof.
- **Phone:** the workspace sends block snapshots inside the ticket's `ticket_view.results` through the relay (section
  Phone results below); every string passes the value hider (secrets.md) before it leaves the computer.

## Phone results (`ticket_view.results`, message.schema.json)

Decided by the W2b contract owner, 11 Nov (lane D 2.6). Vectors: `vectors/phone-results-v1.json` (trim, in → out) and the
`results-*` cases of `vectors/ticket-view-v1.json` (relay, workspace and validate.py replay them). T0:
`… contracts/validate.py phone-results blocks`.

- **Shape:** `results: [{id, from: job · agent · orch, title?, at, checked?: true, doc: <orch.blocks/1>}]`, only in a full
  snapshot. `id` = the job id (`j_…`) for a job result, else the artifact id (`a_…`, derived like attachment ids) of the
  evidence that holds the document. `from` equals `doc.from` (the schema refuses a mismatch, so a job cannot pose as the
  agent's proof). Unknown fields are refused at the result and document level.
- **Count and order:** the ticket's newest results, **newest first** by `at`, **at most 5**, ids unique. A full snapshot
  without `results` means none.
- **Labels** (the same words on the web, 2.4/2.5): `job` → "Reported by the job"; `agent` with `checked: true` → "Checked
  by the agent"; `agent` without → "From the agent"; `orch` → "Worked out by orch". `checked` exists only with `from:
  agent` and means the proof belongs to a step that is done with proof (`checklist[].done`); it is `true` or absent, never
  `false`. A job result is never shown as a passed check.
- **No new phone actions.** A result is display only. Looks good / Send back stay on the existing Result card
  (`body.feedback` on an attachment); `id` and `checked` are never sent back and approve nothing.
- **Light updates** (`light: true`) carry no `results` (the schema refuses them); the phone keeps the results of its last
  full snapshot and a newer full snapshot replaces them.
- **Trim** (the sender, per result, then the value hider): (1) drop `log` blocks and block types the sender does not know;
  (2) cut a table over 20 rows to its first 20 and set `total_rows` (kept if already set, else the original row count);
  (3) send a link without query and fragment; (4) send a `file` block's `path` as the base name only; (5) if (1) or (2)
  removed anything, end with a `summary` "More on the computer"; (6) while the result is over 2560 bytes (compact UTF-8
  JSON) or 50 blocks, drop the last block before that summary (adding it if missing). The result must still be a valid
  orch.blocks/1 document; the sender checks it against blocks.schema.json and drops a result that fails rather than
  sending it. A trimmed result is a fixed point (trimming again changes nothing; validate.py checks this).
- **Budget** (relay cap 16384 bytes for the whole `ticket_view`; the workspace aims at 15000): each result at most 2560
  bytes, all results together at most 8192 (the sender keeps the newest and drops the oldest past that). So 3 results of
  full size always fit, 5 when they average 1.6 KB (the vector's trimmed job result with a 20-row table is 2074 bytes, an
  agent proof with a kv and a picture 441); the rest of the snapshot keeps at least 6808 bytes before the existing fit
  sheds history, attachments, refs and task text; only then are results dropped, oldest first, never the newest one.
- **File tap:** a `file` block opens the matching `ticket_view.attachments` entry like file names in texts (#335): the
  first `image` or `file` attachment (list order, newest first) whose `name` equals the block's base name, ignoring case;
  `preview: image` draws that attachment's picture. No match: a plain row with name and size, not tappable. No new field;
  the phone never gets file bytes or a path through blocks.
- **Renderer:** the phone checks each document against the fixtures' rules; an invalid one shows "These results can't be
  shown" for that result only. The relay checks only the envelope in message.schema.json (it compiles that one file) and
  is otherwise pass-through: no relay code change; the existing 16 KB cap and the vector replay
  (relay/tests/ticket_view.rs) cover it. Subscribers get no results (relay subs view is unchanged).
- **Rollout:** the relay reads message.schema.json at build time, so it is rebuilt and deployed with this schema before a
  workspace sends `results`; an older relay answers `422 invalid`, and the 2.6 sender then resends the same update once
  without `results`.

## Fixtures (`vectors/blocks/`)

Each file: `{"name", "doc", "valid": bool, "shows": [text the renderer must show], "fallback": <count of "can't show this
here" rows>}`. `valid-*` files have `valid: true`, `invalid-*` files `false`. A renderer test loads every file, renders
`doc`, and checks that each `shows` string is visible (as text) and that exactly `fallback` fallback rows appear; for invalid
ones it checks the "can't be shown" state.
