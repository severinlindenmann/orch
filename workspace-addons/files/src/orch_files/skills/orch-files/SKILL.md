---
name: orch-files
description: Use when you need to find a file in this workspace by its name or by words inside it (a document, sheet, note, code, a file a helper made for a ticket), or when a person asks where a file is or wants the Files page. Searches one fast index; no AI call. Not for sharing a file by link (that is publish) and not for files outside this workspace folder.
---
# orch files

Files lists every file in the workspace folder (your folders) and the files helpers made for tickets (shown under
their ticket). It searches names and the text inside files with one index in `.orch/cache/files/`, and only reads
files again that changed. Private files (secret-looking names, key files, environment files) are found by name
only; their content is never read or shown.

## Recipes

**Find a file** (any helper, no page needed)

    orch files search "price check" --json     # name hits first, then files that hold the words
    orch files search muller                   # accents do not matter: finds Müller
    orch files search invoice --limit 50

Each item: `path` (from the workspace folder), `title`, `kind`, `size`, `changed` (seconds), `ticket` (for a
ticket file), `found` (`name` or `text`) and for a text hit the matching `line`. Any part of a word matches
("invo" finds Invoice-2026.pdf). The search first checks for changed files; `--no-refresh` skips that.
`unread` > 0 means the text of some files is still being read the first time: run `orch files index` to finish.

**Bring the index up to date now**

    orch files index --json

**The page** (only when the person asks)

    orch files open              # starts the page and opens it
    orch files status --json

## Naming files you make
Plain words and the day: `<what>-<yyyy-mm-dd>.<ext>` (`price-check-2026-11-18.md`). Versions of one file end in
`-v2`, `-v3` (`catalogue-draft-v2.pdf`): Files stacks them into one card. Give a file a title when you attach it as
evidence (`orch check done ... --file <path> --title "<short name>"`): Files shows that title.

## Not here
- Sharing a file by link: the publish skill.
- Changing, moving or deleting files: Files only reads.
