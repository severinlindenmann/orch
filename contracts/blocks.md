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
- **Links:** `https://` only; anything else makes the document invalid. Opened in a new tab / the system browser.
- **Files:** a relative path inside the workspace (no `/` at the start, no `..`, no `\`, no drive letter). The renderer resolves
  it against the workspace root and refuses a symlink that leaves it ("file not available"). The phone gets no file bytes
  through blocks: it shows the name and size (snapshots, below).
- **Unknown block type** (a newer producer): valid, drawn as one muted row "can't show this here". A known type that breaks
  its rules makes the whole document invalid: the surface shows "These results can't be shown" and the raw JSON only under
  Details. Producers check before writing; `orch job table` refuses an invalid block with plain words.
- **Versioning:** a new optional field keeps `orch.blocks/1`; a new block type keeps it too (old renderers fall back). A
  changed meaning gets `orch.blocks/2`; renderers refuse a schema they do not know.
- **Phone:** the workspace sends a block snapshot inside the ticket's `ticket_view` through the relay (≤ 16 KB with the rest
  of the snapshot, relay-api.md); the sender drops `log` blocks first, then cuts tables to 20 rows (setting `total_rows`), then
  drops blocks from the end, and adds a final `summary` "More on the computer". Every string of the snapshot passes the
  value hider (secrets.md) before it leaves the computer; a `file` block carries name and size only, never bytes or a path
  outside `.orch/tickets/<id>/artifacts/` (other paths are sent as the base name only).

## Fixtures (`vectors/blocks/`)

Each file: `{"name", "doc", "valid": bool, "shows": [text the renderer must show], "fallback": <count of "can't show this
here" rows>}`. `valid-*` files have `valid: true`, `invalid-*` files `false`. A renderer test loads every file, renders
`doc`, and checks that each `shows` string is visible (as text) and that exactly `fallback` fallback rows appear; for invalid
ones it checks the "can't be shown" state.
