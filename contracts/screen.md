# Live session: `orch run screen` and `orch run type` (`orch.screen/1`)

A live run already sits in its own tmux session on orch's own tmux server (`tmux -L orch-<hash>`, session = ticket id,
run.schema.json `tmux`). Focus shows it on the ticket page (Session tab, one click away from Steps, owner decision 1A): watch it
read-only, or take it over to type, only from the dashboard on this computer (2A). No phone version. Windows (no tmux) and
runs without a live mode have no Session tab.

Schema: `screen.schema.json` (stream lines; `$defs/takeover`, `$defs/type_input`), `run.schema.json` `takeover`. Examples:
`examples/screen/` (each file is one stream), `examples/type-input/`, `examples/run/valid-live-takeover.json`. Vectors:
`vectors/screen-v1.json`: control-mode lines → stream lines on the **real capture** (`workspace/tests/fixtures/w2b/screen/`,
tmux 3.8, lines copied verbatim), UTF-8 split across chunks, hiding across `%output` lines, take-over decisions.
T0: `… contracts/validate.py screen`.

## Switches (owner decision 3C)

`.orch/config.toml` `[focus] live_session = true` and `[focus] session_typing = false` for a new workspace. `session_typing = true`
counts only with a settings record made through a `focus.settings` proof (human-proof.md, Settings: records and tombstones): an agent editing
the file cannot turn typing on. The relay admin
can lock live sessions off for all its workspaces (usage-counts.md, policy `live_session: "locked_off"`). **Off means off:**
the core refuses `orch run screen` and `orch run type` (exit 2, `code: switched_off` / `locked_by_admin`), not only the tab.
Turning either switch off during a take-over releases it at once; turning `live_session` off ends open streams
(`end` `switched-off`).

## `orch run screen <ticket> --follow --json`

Read-only: a tmux control-mode client attached with `-r` (`tmux -u -L <socket> -C attach -r -t <session>`), which cannot send
keys. Any person or add-on on this computer may watch while `live_session` is on (agents are refused: `not_allowed`).
Refused with `not_available` when the ticket has no live run with a tmux session.

Lines (one JSON object each, `seq` 1, 2, 3 …):

| type | When | Fields |
|---|---|---|
| `hello` | first | `ticket`, `run`, `cols`, `rows`, `at`, `typing_switch`, `takeover` (null or `$defs/takeover`) |
| `snapshot` | second, and after a reconnect of the control client | `cols`, `rows`, `alt`, `cursor {x, y, visible}`, `data` = `capture-pane -p -e -J` lines joined by CR LF (wrapped lines joined, so a wrapped value is still hidden) |
| `output` | per `%output %<pane> <data>` of the session's pane | `data`: tmux's octal escapes (`\ooo` for bytes below 0x20 and `\`) decoded, bytes decoded as UTF-8 with an incremental decoder (an incomplete sequence at the end of a chunk waits for the next; invalid bytes become U+FFFD) |
| `resize` | `%layout-change` with a new size | `cols`, `rows` (from the first `<W>x<H>` of the layout) |
| `alt` | after an `output` that enters or leaves the alternate screen (`ESC[?1049h/l`, `?1047`, `?47`) | `on` |
| `takeover` | the lock was taken or released | `state`, `by`, `since`, `expires_at`, `reason` |
| `ping` | every 15 s without other lines | `at` |
| `end` | last line | `reason`: `run-ended`, `switched-off`, `locked-by-admin`, `session-gone` |

Other control-mode lines (`%begin`/`%end`, `%session-changed`, `%window-renamed`, …) are ignored. Producers may join
consecutive `output` lines within 30 ms; readers never depend on chunk boundaries. One `data` ≤ 64 KB (a larger chunk is split
at a character boundary).

**Hiding.** Every `data` passes through the streaming hider of secrets.md before the line is written: one hider per stream,
fed in order, so a value split over two `%output` lines is still hidden (vectors `hide`). To keep the screen live, the
producer holds back only a tail that is a prefix of some hidden form (at least 4 characters long); a shorter tail is
flushed after 200 ms. The result equals hiding the whole text at once, except that at most 3 characters of a value that
arrives more than 200 ms apart may show. Known limit (Level 1): a value split by colour codes or cursor moves is not found.

## `orch run type <ticket>` (take-over)

A person only, only from the local dashboard, proven by the human channel (invariant H1, human-proof.md): the page server
mints a proof for `run.takeover` / `run.release` and this ticket and passes it as the first stdin line with `--proof-stdin`.
The core reads `by` from the proof; `--by` / `--from` flags are never trusted (a different `--by` is refused). A remote
browser never gets a proof, so it can only watch. The core also refuses when an agent tool is in the environment and while
a switch is off.

- `--takeover --json` → takes the lock: run record `takeover` = `{by, from, since, last_input_at, expires_at = last_input_at + 120 s, keys}`
  (written under the ticket lock), answer `{"takeover": {...}}`. Held by another person and not expired → `conflict`
  ("Someone else is typing in this session."). The same person again → the lock is refreshed.
- keys on the following stdin lines of the same process (`$defs/type_input`, one JSON object per line: `{"text": "…"}` typed literally with `send-keys -l`, or
  `{"key": "Enter" | "Escape" | "C-c" | …}`): accepted only while this person holds the lock; each line updates
  `last_input_at`, `expires_at` and `keys`. The text is never logged or recorded.
- `--release --json` → removes the lock, answer `{"takeover": null}`.
- **Pending input is held.** While a `takeover` is present and not expired, the paste-when-idle queue (run-pending.schema.json)
  does not deliver; messages wait and are delivered after release, as today.
- **Auto release** after 120 s without a key (checked by the run's watcher every 10 s and on every `run` call), when the run
  ends, when a switch goes off, or on an admin lock. Every release writes one `takeover` line to open streams and one
  `session.input` activity event (activity.md: `by`, `from`, `since`, `ended`, `reason`, `keys`; never the text).

Decisions (reference `scr_takeover` in validate.py, vectors `takeover`): switch off → `switched_off`; admin lock →
`locked_by_admin`; proof not valid (missing, forged, expired, other ticket or action, replayed) → `not_allowed`; no live
session → `not_available`; held by someone else and not expired → `conflict`; else `ok`.
