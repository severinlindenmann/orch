# Services add-on contract (`orch services`)

Background jobs a workspace needs (a web preview, a local server, a watcher) kept running by the computer's own
service tool, under the person's own account: launchd on macOS, systemd user units on Linux (Windows comes later).
The add-on has no background process of its own. Parent plan ORCH-23; the page follows the mockup
`workspace-addons/dashboard/mockup/services/` (layout C).

Schema: `service.schema.json` (one record). Example: `files/web-preview.json`.

## Manifest (`workspace-addons/services/src/orch_services/orch-addon.toml`)
`name = "services"`, not recommended (off until `orch addon add services`), no `background`, no `needs`,
`gitignore = [".orch/addons/services/"]`, `[dashboard] label = "Services"`, `icon = "box"`.

## Files (all under `.orch/addons/services/`, gitignored, local to this computer)
- `services/<id>.json`: one record per service (`orch.services.service/1`), written as a new file + rename (R8.2).
  Fields this version does not know are kept on rewrite. A file that cannot be read is skipped and counted.
- `logs/<id>.log`: stdout and stderr of the service, appended. Kept when the service is removed.
- `state/<id>.json`: `{"running", "since"}` of the last start or stop through orch (the `since` of a stopped
  service when the platform does not say it; `running` = what the person last asked for), and `watch` written by
  `check`: `events` (times of failures in the last 10 minutes), `runs` (the platform's start count at the last pass),
  `healthy_since`, `failing`, `question` (`{ticket, id, open, asked_at, answer?}`). Fields are merged on every write
  (new file + rename). Never log text: names and counts only.

## Platform entries (never sudo, never `User=`, never a system-wide folder; home = `Path.home()`)
- macOS: `~/Library/LaunchAgents/ch.orch.svc.<workspace id>.<id>.plist` (workspace id = the core's `.orch/.local-id`).
  `ProgramArguments` (the program's full path, found at add time), `WorkingDirectory`, `StandardOutPath` and
  `StandardErrorPath` = the log, `KeepAlive = true`, `RunAtLoad` = starts by itself, `EnvironmentVariables.PATH`.
  Starts by itself off also runs `launchctl disable gui/<uid>/<label>` so the plist is not loaded at the next login;
  start = `enable` + `bootstrap` (+ `disable` again when off), stop = `bootout`, restart = `kickstart -k`, state from
  `launchctl print`.
- Linux: `~/.config/systemd/user/orch-svc-<workspace id>-<id>.service`, `Restart=on-failure`, output
  `append:` to the log, `WantedBy=default.target`; starts by itself = `systemctl --user enable|disable`; state from
  `systemctl --user show` (`ActiveState`, `MainPID`, `ActiveEnterTimestamp` / `InactiveEnterTimestamp`).
  `ExecStart` words are double-quoted (`\` and `"` escaped, `$` → `$$`, `%` → `%%`). `WorkingDirectory=` and
  `append:` take the rest of the line as the path, so those are written unquoted with `%` escaped.
- Missing tool or no session: refused with "This computer cannot keep services running for you: <reason>."

## Commands (every one takes `--json`; exit 2 = refused, `{"error": "<one sentence with the next step>"}`)
| Command | Answer (`--json`) |
|---|---|
| `list` | `{"services": [row], "unreadable": n, "note"?}`; row = `id, name, state ("running" \| "stopped" \| "failing"), since (RFC 3339 UTC), auto, made_by, port, command, cwd, pid?, health, failing, question`; `health` = `{"ok", "how": "process alive" \| "answers on its address", "text"}`, `question` = `{ticket, id, title, text}` while one is open, else `null`. Reads only |
| `check` | `{"checked": [{id, name, health, failing, did?, error?}], "unreadable": n}`: one pass, no loop (see Health check) |
| `add <name> --id <slug> [--port N] [--ticket ID \| --addon NAME] [--cwd DIR] [--auto] [--start] -- <command...>` | `{"service": row, "next"}`; installed stopped unless `--start` |
| `start \| stop \| restart <id>` | `{"service": row, "next"}` |
| `auto <id> on \| off` | `{"service": row, "next"}` |
| `remove <id>` | `{"removed": id, "next"}`: stops it, removes the platform entry and the record, keeps the log |
| `log <id> [--lines N]` (default 20, max 1000) | `{"id", "lines": [...]}`; every line goes through the core secret scan, a hit shows `••••••` in place of the value (the whole line when the value cannot be told apart) |
| `found` | `{"found": [item]}`; item = `id` (`launchd:<label>` \| `systemd:<unit>` \| `process:<pid>`), `name`, `running`, `since`, `what` (one plain line), `how` (`kind`, `label`/`unit`, `path`, `pid`?), `command` (secret scan hits as `••••••`), `auto`. Nothing found = `[]` and one plain sentence. Reads only |
| `adopt <found-id> [--name X] [--id SLUG] [--ticket ID]` | `{"service": row, "next"}`: Manage with orch (see below) |
| `act <verb> [--by X] -- <id>` | verbs `start, stop, restart, auto-on, auto-off, remove, adopt` (adopt takes a found id); same answers as the commands |
| `view` | `orch.addon-view/1`, one `list` block (the real page is ORCH-272) |

## Found on this computer and Manage with orch
`found` lists background jobs of the person's own account that orch did not make; it only reads, nothing about a
found job changes until the person chooses Manage with orch (`adopt`).
- macOS: plists in `~/Library/LaunchAgents` (Label, `ProgramArguments`/`Program`, `RunAtLoad`) plus
  `launchctl print gui/<uid>/<label>`; labels `ch.orch.svc.*` (orch's own) and `com.apple.`, `com.google.`,
  `com.microsoft.` are left out (one list in `found.py`).
- Linux: `systemctl --user list-units --type=service --all` and `~/.config/systemd/user/*.service`, then one
  `systemctl --user show`; only units whose file is in `~/.config/systemd/user` or `~/.local/share/systemd/user`, never
  `orch-svc-*`.
- Processes: programs of this user without a terminal, not started by orch, whose working folder is inside this
  workspace (`ps`, folder from `/proc/<pid>/cwd` on Linux, `lsof` on macOS; no lsof = no processes listed).
- Never reads environment variables, log or other files of other programs; never prints a secret.

`adopt` writes a record with `made_by: {"found": true[, "ticket"]}` and `adopted: {kind, entry, path}` (schema). It
does not move, rename, rewrite or restart the plist, unit or process: start, stop, restart and auto act on the
existing label or unit (auto = `launchctl enable|disable` / `systemctl --user enable|disable`), `log` reads the plist's
`StandardOutPath` or `journalctl --user -u <unit>`. `remove` on an adopted service only forgets the record (the answer
has `"forgotten": true` and says so). A bare process cannot be adopted: refused with the `orch services add` line to
use instead; it is never stopped by orch.

## Health check and failing (`check`)
One pass over every service, no loop and no sleep (R2.6); a person repeats it with the automation add-on
(`orch automation script add services-check -- orch services check`, then `orch automation repeat <ticket>
"every 5 minutes" --script services-check`).
- Health: the process is alive (driver state); with a `port`, a TCP connect to `127.0.0.1:<port>` within 0.5 s.
  A service the person stopped is not checked (`"Stopped, so not checked"`) and never failing.
- A failure = a failed health check, or a start the platform did by itself since the last pass (driver `runs()`:
  launchd `runs` from `launchctl print`, systemd `NRestarts`; starts through orch move the baseline and do not
  count). 3 failures within 10 minutes = `failing` (row `state: "failing"`).
- Failing raises ONE question with `orch ask --by agent:services` on `made_by.ticket`, else on the add-on's own
  ticket titled `Services: <name> keeps stopping` (found by title, else `orch ticket new`): text `<name> keeps
  stopping: it failed N times in the last 10 minutes. Restart, Stop or Look into it?`, options Restart / Stop /
  Look into it, recommended Restart. No second question while it is open (its id is in the state file).
- Answers (no new act verbs): the next pass reads the question with `orch ticket show` and acts once (the state is
  written before acting): Restart = `restart`, Stop = `stop`, Look into it (or any other text) = nothing, one
  `orch log` line on the ticket. A question taken back by someone ends it too.
- Healthy 10 minutes in a row (alive, answering, not started again) clears failing and takes an open question back
  (`orch ask <ticket> --take-back qN "<name> runs fine again for 10 minutes."`).

## Turning it off
`orch addon remove services` removes the skill and AGENTS block and the command; tickets and the core keep working.
Records and logs stay (unless `--purge`), and services already handed to the computer keep running: remove them
first (`orch services remove <id>`) if they should stop.
