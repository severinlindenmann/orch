# Documentation pages (`orch.docs/1`)

The dashboard's Documentation page (the book icon next to Settings) explains how orch and each add-on work in
pictures: flows in lanes, state diagrams and side-by-side flows, with little text. Each page ends with "Under the
hood": live facts of this workspace, the commands behind it and where it lives.
Schema: `docs-pages.schema.json`. Checker: `workspace/src/orch/docs.py` (`docs.load`, `docs.check`).
Drawn by the master `workspace/src/orch_ui/static/docs.js` (`UI.docs`). How a page is written and kept current:
the dev skill `orch-docs-page`.

## Where the pages come from

| Source | File | Group on the page |
|---|---|---|
| orch itself | `workspace/src/orch/docs.json` (also holds `actors`) | orch |
| built-in add-ons (relay, publish) | `docs = "docs.json"` in `orch/builtin/<name>/orch-addon.toml` | Turn on when needed |
| every other add-on | `docs = "<file>"` in its `orch-addon.toml` | Add-ons |

`orch.docs.collect` puts them together: orch first, then relay, publish, then add-ons by name. An add-on that is
installed or shipped but off here still shows its pages, marked Off. A page id that is already taken is skipped
(an add-on never replaces another page). Related ids that name no shown page are dropped.

## File

```json
{"schema": "orch.docs/1", "pages": [ { "id": "focus", "icon": "target", "title": "Focus", "one": "…", "steps": [ … ],
  "good": ["…"], "related": ["helper-run"],
  "tech": {"cmds": [["orch focus open <id>", "the live page of one ticket"]], "files": [], "live": ["self"]} } ]}
```

| Key | Meaning |
|---|---|
| `id` | `[a-z][a-z0-9-]{1,40}`, unique over all pages; the address is `#docs/<id>` |
| `icon` | one of the docs icon set (`docs.ICONS`) |
| `title`, `one` | page title (≤ 60) and one plain sentence under it (≤ 200); no `<` or `>` |
| `kind` | `flow` (default: `steps`), `states` (`states` + `moves`), `compare` (2-4 flows, each `title`, `tone`, `steps`) |
| step | `who` (`you`, `orch` = the program, `helper` = an AI helper, `other` = another workspace, a phone or a service, `server` = the relay or publish server), `text` (≤ 110), optional `detail` (≤ 260), `decision`, `end`, `proposed`, `branch` (≤ 4 of `if`, `then`, `stop`: `stop: true` ends the flow there) |
| `good` | at most 5 short lines under the picture |
| `related` | at most 8 page ids it works with (drawn as links and, on the overview, as lines) |
| `tech.cmds`, `tech.files` | `[text, what it does]` rows (≤ 6 commands, ≤ 4 places); commands may hold `<placeholders>` |
| `tech.live` | live facts the dashboard reads itself, no network, no AI: `relay`, `phone`, `publish`, `helper-limit`, `reviewer`, `addons`, `self` (the add-on's own state: on, running) |

Rules for the words: every step was checked against the code; mark who does it (person, program, AI) honestly;
no "classify" or other step that does not exist; plain words, one idea per box.
