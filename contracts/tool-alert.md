# Tool warning on the phone (v1, ORCH-47)

The phone shows the same warning as dashboard Home when a tool login, a connection or a key a helper needs runs out
soon or stopped working, and names the tickets whose helpers it stops. Shapes: `message.schema.json`
(`$defs/tool_alert`, the text rules), test vector `vectors/tool-alert-v1.json`. The last check comes from
`orch logins` (`.orch/run/health.json`, `orch.health/1`, workspace/src/orch/health.py).

## What travels, and what never does

One `text` message from the workspace to `phones`, with no `ticket`, no `reply_to` and no `update`. Its body is
exactly `{text, tool_alert}`:

| Field | Value |
|---|---|
| `text` | The warning in plain words, one line, at most 500 characters (built by the workspace, below). The relay pushes it like any workspace text; the phone shows it in the row. |
| `tool_alert.name` | The stable name of the check (`[a-z][a-z0-9-]{0,31}`, the `name` of the health item). The phone keeps one row per name. |
| `tool_alert.label` | The tool's name as dashboard Home shows it ("Claude Code login", "Company wiki connection"), one line, 1 to 60 characters. |
| `tool_alert.kind` | `login`, `connection` or `key`. |
| `tool_alert.state` | `soon` (runs out within 3 days), `renew` (stopped working), `unreachable` (cannot be reached), or `works` (works again: the phone removes the row). |
| `tool_alert.ends_at` | The end date (UTC, `Z`) when the tool tells one, else `null`. |
| `tool_alert.stops` | The display keys of the tickets whose helpers it stops (`ORCH-12`), at most 20, each once. Empty when none. |
| `tool_alert.no_new_work` | `true` when this is the helper chosen here and it stopped working: helpers start no new work. |

Never on the wire: the secret, the key's value, the account, the tool's own answer, the command the check runs,
ticket titles, file paths. `text` and every field go through the outgoing secret scan like every relay text
(R5.2). The check itself already keeps only works / not and the end date (health.py).

## When the workspace sends it

- Only while the relay add-on is on and connected **and** at least one phone is paired with this workspace (the
  `phones` list of the last `orch relay refresh`). Otherwise nothing is sent and nothing is remembered: with no
  phone connected nothing changes. A phone paired later gets the warnings that are open at that moment.
- On every relay inbox pull (the same moment as the phone ticket pages), from the last check when it is at most
  1 hour old. orch never runs a check for the phone; the checks run as before (ORCH-44).
- One text per health item, when its `(state, ends_at)` differs from what was last sent for that name: a new
  warning, a warning that changed (soon → renew, a new end date), and `works` once after a warning was sent. An
  item that works and was never warned about sends nothing. A changed `stops` list alone sends nothing (no second
  push for the same warning).
- What was sent is kept in `.orch/secrets/tool-alerts.json` (`{name: {state, ends_at, id, at}}`); the message id
  and time are fixed there before the send, so a retry sends the same bytes.

## The words (the same as dashboard Home)

`<label>` = the label as above; `<when>` = "Monday 16 November at 22:24" in the computer's local time;
`<keys>` = the `stops` keys joined by ", "; `<n tickets>` = "1 ticket" / "3 tickets".

| state | text |
|---|---|
| `soon` | `The <label> ends on <when>.` + ` After that helpers stop on <n tickets>: <keys>.` when stops + ` Renew it on your computer.` |
| `renew` | `The <label> stopped working.` + ` Helpers stopped on <n tickets>[ and start no new work]: <keys>.` / ` Helpers start no new work.` + ` Renew it on your computer.` |
| `unreachable` | `The <label> cannot be reached.` + the same helper sentence as `renew` + ` Check it on your computer.` |
| `works` | `The <label> works again.` |

## What the phone does

- The relay pushes the text as for any workspace text to `phones` (`type: text`, title = workspace name, body =
  the text, the text push budget and mutes apply); tapping opens the workspace. Nothing in the relay changes.
- A text with `tool_alert` is never a chat bubble and never counts as unread (like `taken_back`).
- The workspace view shows one row per `name` whose newest `tool_alert` is not `works`, above the General card:
  red for `renew` / `unreachable`, the warning tone for `soon`. The row shows `text`. The phone renews nothing;
  the person renews on the computer.
- A malformed `tool_alert` is ignored (no row, no bubble). Every string is plain text, never markup.

## Examples

A login runs out soon and stops two tickets:

```json
{"schema": "orch.msg/1", "id": "m_alert00000000001", "from": "ws_pilatus001", "to": "phones", "type": "text",
 "created_at": "2026-11-17T08:00:00Z",
 "body": {"text": "The Claude Code login ends on Friday 20 November at 22:24. After that helpers stop on 2 tickets: ORCH-12, ORCH-14. Renew it on your computer.",
          "tool_alert": {"name": "claude", "label": "Claude Code login", "kind": "login", "state": "soon",
                         "ends_at": "2026-11-20T21:24:00Z", "stops": ["ORCH-12", "ORCH-14"], "no_new_work": false}}}
```

The same login stopped working (it is the helper chosen here):

```json
{"body": {"text": "The Claude Code login stopped working. Helpers stopped on 2 tickets and start no new work: ORCH-12, ORCH-14. Renew it on your computer.",
          "tool_alert": {"name": "claude", "label": "Claude Code login", "kind": "login", "state": "renew",
                         "ends_at": "2026-11-20T21:24:00Z", "stops": ["ORCH-12", "ORCH-14"], "no_new_work": true}}}
```

A connection cannot be reached (no end date, no helper known to need it):

```json
{"body": {"text": "The Company wiki connection cannot be reached. Check it on your computer.",
          "tool_alert": {"name": "wiki", "label": "Company wiki connection", "kind": "connection",
                         "state": "unreachable", "ends_at": null, "stops": [], "no_new_work": false}}}
```

Renewed: the row goes away.

```json
{"body": {"text": "The Claude Code login works again.",
          "tool_alert": {"name": "claude", "label": "Claude Code login", "kind": "login", "state": "works",
                         "ends_at": "2026-12-17T21:24:00Z", "stops": [], "no_new_work": false}}}
```
