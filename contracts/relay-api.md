# orch-relay API (v1)

Base: `https://relay.severin.io` (reverse proxy → `<private-network IP>:8103`). JSON in, JSON out.
Messages follow `message.schema.json` (`orch.msg/1`). Times, IDs, errors and lists follow `common.md`.

**Workspace auth:** `X-Orch-Workspace: ws_…` + `Authorization: Bearer orn_<43 chars>`.
**Phone auth:** `X-Orch-Phone: ph_…` + `Authorization: Bearer orn_<43 chars>`.
Workspace tokens work only on `/v1/` workspace routes, phone tokens only on `/v1/phone/`.

## Rules the relay checks on every message

1. **Sender = caller.** `from` must equal the authenticated workspace, else `403`. Phones never post raw messages; the relay builds them.
2. **Pair rule** (one-way: Pilatus → Reports does not imply Reports → Pilatus). Phones need no pair rule: pairing a phone with
   workspaces (admin "Add phone", or editing its list) is the rule both ways. The phone may send to those workspaces, and they may
   send it text and questions:

| Type | Allowed when |
|---|---|
| text with `body.ticket_view` | as text, and: `body.update` is set (schema), `body.ticket_view` is at most 16384 bytes as compact UTF-8 JSON (else `422 invalid`), and every attachment `blob_id` was uploaded by the sender with that `size` (another sender's or a missing blob → `404`, a wrong size → `422`). The relay never reads the snapshot otherwise |
| text, question | to a workspace: pair rule `text` from → to. `to: "ph_…"`: that phone is paired (signed in) and the sender is on its list, else `403 not_allowed` ("That phone is not paired with <name>. In the relay admin, open Phones and tick <name> …"). `to: "phones"` = every paired phone with the sender on its list (none = stored, reaches nobody). Only text and questions go to phones |
| answer | `reply_to` is a `question` that `to` sent to `from` (questions to `phones` / `ph_…` are answered by phones only, `POST /v1/phone/answer`). `ticket` and `question_id` are copied from that question, not trusted from the sender |
| file | pair rule `files`, and the blob was uploaded by the sender; `size` and `sha256` must match the stored blob |
| delegate / start | pair rule `delegate` / `start`. The relay does **not** check the allow; the receiver does (local-files.md) |
| allow | `reply_to` is a delegate/start that `to` sent to `from` |
| refresh-hint, webhook | only made by the relay itself |

3. **Same id twice:** identical message → `200 {id, duplicate: true}`, nothing new is stored. Same id, different content (or another sender) → `409 conflict`.
4. **Only the receiver** can fetch and ack its inbox messages.

## Workspace API

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/v1/whoami` | – | `{id, name, description, tags, phones: n, pending}`: the approved values, plus `pending` = `{description: string\|null, tags: [..]\|null, at}` (only the proposed fields are set; `rev` identifies this exact proposal) or `null` |
| PATCH | `/v1/me` | `{description?: string ≤ 280, tags?: [string ≤ 24, ≤ 8 items]}` (at least one) | `202 {…whoami, status: "pending"}`. The change is only a proposal: the owner must approve it in the admin panel, and until then the old values stay in effect everywhere (directory, refresh snapshot, phones). One pending change per workspace; a new one replaces it. `description` is one line of plain text, characters from Unicode categories L, M, N, P, S and Zs only (no control, newline, bidi or zero-width characters), NFC-normalised, no Default_Ignorable_Code_Point characters (variation selectors, U+034F, U+3164, ...) or U+2800, at most 2 combining marks in a row; tags are lowercase `[a-z0-9-]`, 1–24 characters. Admin-set values follow the same rules. Writes only the pending fields, only while the calling token is still current (else `401`). Bad input → `422 invalid` |
| POST | `/v1/messages` | one message | `201 {id}` (see rules above) |
| GET | `/v1/inbox?wait=0..30` | – | `{items: [message…], next: null}` not yet acked, oldest first, max 100. `wait` = long-poll seconds |
| POST | `/v1/inbox/ack` | `{ids: [m_…]}` | `204`. Acked messages are no longer delivered (the admin can still read them) |
| POST | `/v1/blobs` | raw bytes, max 100 MB | `201 {blob_id, size, sha256}` |
| GET | `/v1/blobs/<blob_id>` | – | raw bytes; only for the uploader and receivers of a `file` message with this blob, else `404` |
| POST | `/v1/webhooks` | `{mode: "once"\|"permanent", ticket?}` | `201 {id, url}`; `url` = `https://relay.severin.io/webhook/<id>?token=whk_…` (shown once) |
| GET | `/v1/webhooks` | – | list of `{id, mode, ticket, created_at, last_call_at}` (own only) |
| DELETE | `/v1/webhooks/<id>` | – | `204` |
| POST | `/v1/transcribe` | Same as `/v1/phone/transcribe`, with workspace auth (agents transcribe audio files) | Same as `/v1/phone/transcribe` |
| GET | `/v1/refresh` | – | Full snapshot of everything assigned to this workspace now: `{version, skills: [{name, version, files: {"<relative path>": "<base64>"}}], mcp: {"<name>": {…server config…}}, credentials: {"<NAME>": "<value>"}, workspaces: <workspaces.schema.json>}` (its `phones` = the paired phones that may reach this workspace). What is missing was unassigned and gets removed locally (local-files.md) |

## Phone API

| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/v1/phone/pair` | `{code, name}` (no auth; one-time code from the link) | `201 {phone_id, token, workspaces: [{id, name}]}` |
| POST | `/v1/phone/push` | `{apns_token, sandbox: bool}` | `204` |
| GET | `/v1/phone/workspaces` | – | list of `{id, name, description, tags, online, last_seen, open_questions}` (only workspaces this phone may reach) |
| GET | `/v1/phone/questions` | – | list of `{message, workspace_name}`, open questions only (sent to `phones` or to this phone by a workspace on its list) |
| GET | `/v1/phone/messages?after=&limit=` | – | list of `{message, workspace_name}`, newest first: `text` messages that workspaces on its list sent to this phone or to `phones`, and the texts this phone sent to them (`workspace_name` = the other side) |
| GET | `/v1/phone/updates?workspace=&ticket=&after=&limit=` | – | A read view over the same stored `text` messages as `/v1/phone/messages` (no second store, nothing is written): only texts with `body.update` that a workspace sent to this phone or to `phones`, filtered by the phone's workspace list **as it is at read time** (a workspace removed from the list disappears at once). **Grouped** (no `ticket`): one item per (workspace, ticket) with its newest update, newest first, at most `limit` (1–100, default 50) items; no paging, `next` is always `null`; `workspace` optionally narrows it. **One ticket** (`ticket` + `workspace`): that ticket's updates, newest first, `limit` per page; `after` = the `id` of an item of this same filtered view (the last item of the previous page), `next` = the last item's `id` when more exist, else `null`. `ticket` without `workspace` → `422 invalid`; an `after` that is not in this phone's filtered view of that ticket → `422 invalid`; a `workspace` that is not on the phone's list answers exactly like an unknown one: `200 {items: [], next: null}` (never `403`, so nothing tells them apart). Items: `{id, workspace, workspace_name, ticket, kind, title, text, reply_to, at, ticket_view}`; `title`/`text` are plain text from the message, never HTML. `ticket_view` = the message's `body.ticket_view` (message.schema.json), else `null`; in the **grouped** view it is the newest `ticket_view` of that ticket (looked for in the same bounded rows as the title), so a newer update without one keeps the last snapshot. The relay passes it through as stored |
| GET | `/v1/phone/blobs/<blob_id>` | – | raw bytes (`application/octet-stream`) of a proof file a workspace on the phone's list named in a `body.ticket_view` attachment of a text it sent to this phone or to `phones` (the same filter as `/v1/phone/messages`); anything else, an unknown id included, answers `404` |
| POST | `/v1/phone/answer` | `{question_message_id, answer}` | `201 {id}`. The relay builds the `answer` message (`from: ph_…`, `answered_by: human:<phone name>`, routed as above). First answer wins; later answers from any phone → `409 already_answered` |
| POST | `/v1/phone/send` | `{to: ws_…, text, ticket?}` | `201 {id}`. A `text` message from the phone (voice becomes text on the phone). `to` must be on the phone's list |
| POST | `/v1/phone/transcribe` | Body = the audio bytes, `Content-Type: audio/m4a` (also `audio/wav`, `audio/webm`), max 10 MB / 2 min, optional `?language=de` (else the language is detected) | `200 {text, language, duration}` (`duration` in seconds). `503 transcription_off` when the admin set no Deepgram key (the app then uses on-device speech), `502 transcription_failed` when Deepgram fails or is unreachable, `429 rate_limited` after 30 calls a minute per phone, `413 too_large`, `422 invalid` (type, empty, language) |
| POST | `/v1/phone/signout` | – | `204`. Deletes the token and the push registration; the old token gets `401` from now on |

Push for a new question (APNs): `{"aps": {"alert": {"title": "<workspace name>", "body": "<question text, max 120 chars>"}, "sound": "default"}, "message_id": "m_…", "workspace": "ws_…"}`. Tapping opens that question.
Push for a new text to a phone (`ph_…` or `phones`): same `aps`, plus `"type": "text", "text_id": "m_…", "workspace": "ws_…"` (no `message_id`); tapping opens the messages with that workspace.
Work updates (`body.update` on a text, message.schema.json): the relay pushes a text with `update.kind` = `result`, `question`,
`failure` or `stopped` as above (push body = `update.title` + ": " + the first line of the text, max 120 chars); `ack`, `working`
and `note` are stored and listed (`/v1/phone/messages`, `/v1/phone/updates`) but **never pushed**. A text without `update` is
pushed as before. The filter runs in the relay, not in the sender.
**Text push budget** (per sending workspace and phone, kept in the relay's memory): at most 1 text push per 10 s and 30 per hour
window (the window starts with the first push after the last one ended) for each (workspace, phone) pair; a text over the budget is still stored and listed, only its push is skipped.
Questions are not limited by it. The budget applies after the update-kind filter (quiet kinds never use it up).
Pushes go to the phones the message is for: `phones` = every paired phone with the sender on its list, `ph_…` = that phone.

Admin prompt for a workspace (shown once): `orch addon add relay --yes` then `orch relay connect https://relay.severin.io --workspace ws_… --token orn_…`
(+ the `onboarding.sh/.ps1` line for machines without orch). `connect` runs `orch init` if needed, checks `/v1/whoami`,
writes `.orch/secrets/relay.json`, copies the `orch-relay` skill (shipped inside the CLI), adds the AGENTS.md block, then runs `orch relay refresh`.

Phone onboarding link (from the admin portal, also as QR code, valid 24 h, one use):
`orch://pair?relay=https%3A%2F%2Frelay.severin.io&code=pc_<22 chars>`

## Public routes

| Method | Path | What |
|---|---|---|
| GET, POST, PUT | `/webhook/<id>?token=whk_…` | Stored as a `webhook` message to the owning workspace → `202`. A `once` webhook is used up in the same database transaction that stores the message; later calls → `410`. Wrong token `401`. Body max 1 MB, stored as text |
| GET | `/onboarding.sh`, `/onboarding.ps1` | Small scripts: install orch if missing, then `orch addon add relay --yes` and `orch relay connect` |
| GET | `/health` | `200 ok` |
| GET | `/`, any unknown non-`/v1` path | Dark HTML page "This page isn't available" (`200` for `/`, `404` otherwise; no product name). Unknown `/v1/…` paths answer JSON `404 not_found` |

"Online" = the workspace or phone called the relay in the last 2 minutes. Offline workspaces get their messages on the next inbox call.

## Admin API (only on `<private-network IP>:8412`, reached directly from the owner's devices on the private network; never public)

Auth: `X-Orch-Admin: <admin token>` (file `/etc/orch-relay/admin-token`); the portal at `/admin` asks once, keeps a cookie.

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/admin` | – | Portal HTML |
| GET / POST | `/admin/api/workspaces` | POST: `{name, description, tags: []}` | list of `{id, name, description, tags, description_by, tags_by, online, last_seen, unread, pending}` (`last_seen` null until the workspace first calls; `pending` as in whoami, or `null`) / `201 {id, token, prompt}` |
| PATCH | `/admin/api/workspaces/<id>` | `{name?, description?, tags?}` | `200` (shows up in the next refresh). Admin-set description/tags are marked `description_by` / `tags_by` = `admin` |
| POST | `/admin/api/workspaces/<id>/profile/approve` | `{rev}`: the `rev` of the proposal the owner looked at | `200` the workspace card. The pending description/tags become live (marked `workspace`), the version is raised and refresh-hints go out. `404` when nothing is pending, `409 conflict` ("This change was replaced, review again.") when `rev` no longer matches |
| POST | `/admin/api/workspaces/<id>/profile/reject` | `{rev}` | `204`. The pending change is dropped, old values stay. `404` / `409` as for approve |
| POST | `/admin/api/workspaces/<id>/token` | – | `200 {token, prompt}`. Also drops a pending profile change |
| DELETE | `/admin/api/workspaces/<id>` | – | `204` |
| GET / PUT | `/admin/api/rules` | PUT: `{rules: [{from, to, text, files, delegate, start}]}` (full list) | `{rules: […]}` |
| GET | `/admin/api/messages?workspace=&type=` | – | list of message + `{acked}`, decrypted with the master key |
| GET | `/admin/api/allows` | – | list of `{from, to, kind, key, mode, created_at}` (read from `allow` messages) |
| GET | `/admin/api/shared` | – | `{version, skills, mcp, credentials (names only), assign}` |
| PUT | `/admin/api/shared/skills/<name>` | `.tar.gz` of the skill folder | `200 {name, version}` |
| PUT | `/admin/api/shared/mcp/<name>` | `{config}` | `200` |
| PUT | `/admin/api/shared/credentials/<NAME>` | `{value}` | `200` |
| DELETE | `/admin/api/shared/{skills\|mcp\|credentials}/<name>` | – | `204` |
| PUT | `/admin/api/shared/assign/<ws>` | `{skills: [], mcp: [], credentials: []}` | `200` |
| GET / PUT / DELETE | `/admin/api/voice` | PUT: `{deepgram_key}` (sets or replaces the one relay-wide Deepgram key) | `{deepgram: {set: bool, last4: string \| null}}`; DELETE `204`. The key is never returned in full, never sent to phones or workspaces, and is not part of `/admin/api/shared`; it does not raise `version` |
| GET | `/admin/api/webhooks` | – | list of all webhooks with workspace |
| DELETE | `/admin/api/webhooks/<id>` | – | `204` |
| GET / POST | `/admin/api/phones` | POST: `{name, workspaces: [ws…]}` | list / `201 {phone_id, link, qr_svg}` |
| PATCH | `/admin/api/phones/<id>` | `{workspaces: [ws…]}` | `200`. Workspaces added or removed get a refresh-hint |
| DELETE | `/admin/api/phones/<id>` | – | `204` (same effect as sign-out). Its workspaces get a refresh-hint |

Every change under `/admin/api/shared/`, to a workspace's name/description/tags, or to the rules raises `version` by 1 and sends a `refresh-hint` to each affected workspace.
So do pairing a phone (`POST /v1/phone/pair`), signing it out, and editing or deleting it: its workspaces refresh their `phones` list.
