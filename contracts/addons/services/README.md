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
  service when the platform does not say it).

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
| `list` | `{"services": [row], "unreadable": n, "note"?}`; row = `id, name, state ("running" \| "stopped"), since (RFC 3339 UTC), auto, made_by, port, command, cwd, pid?` |
| `add <name> --id <slug> [--port N] [--ticket ID \| --addon NAME] [--cwd DIR] [--auto] [--start] -- <command...>` | `{"service": row, "next"}`; installed stopped unless `--start` |
| `start \| stop \| restart <id>` | `{"service": row, "next"}` |
| `auto <id> on \| off` | `{"service": row, "next"}` |
| `remove <id>` | `{"removed": id, "next"}`: stops it, removes the platform entry and the record, keeps the log |
| `log <id> [--lines N]` (default 20, max 1000) | `{"id", "lines": [...]}`; every line goes through the core secret scan, a hit shows `••••••` in place of the value (the whole line when the value cannot be told apart) |
| `act <verb> [--by X] -- <id>` | verbs `start, stop, restart, auto-on, auto-off, remove`; same answers as the commands |
| `view` | `orch.addon-view/1`, one `list` block (the real page is ORCH-272) |

`failing` (a service that keeps crashing), found services and the health check come in ORCH-270 / ORCH-271.

## Turning it off
`orch addon remove services` removes the skill and AGENTS block and the command; tickets and the core keep working.
Records and logs stay (unless `--purge`), and services already handed to the computer keep running: remove them
first (`orch services remove <id>`) if they should stop.
