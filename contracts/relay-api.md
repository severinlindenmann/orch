# orch-relay API (v1)

Base: `https://relay.severin.io` (reverse proxy → `<private-network IP>:8103`). JSON in, JSON out.
Messages follow `message.schema.json` (`orch.msg/1`). Times, IDs, errors and lists follow `common.md`.

**Workspace auth:** `X-Orch-Workspace: ws_…` + `Authorization: Bearer orn_<43 chars>`.
**Phone auth:** `X-Orch-Phone: ph_…` + `Authorization: Bearer orn_<43 chars>`.
Workspace tokens work only on `/v1/` workspace routes, phone tokens only on `/v1/phone/`.
**Subscriber auth:** the `sub_…` token in the path or as `Authorization: Bearer` (see Subscribers); it works only on `/v1/sub/`.

## Rules the relay checks on every message

1. **Sender = caller.** `from` must equal the authenticated workspace, else `403`. Phones never post raw messages; the relay builds them.
2. **Pair rule** (one-way: Pilatus → Reports does not imply Reports → Pilatus). Members of one group with `talk` on also
   count as having `text` and `files` both ways (see "Groups" under the Admin API). Phones need no pair rule: pairing a phone with
   workspaces (admin "Add phone", or editing its list) is the rule both ways. The phone may send to those workspaces, and they may
   send it text and questions:

| Type | Allowed when |
|---|---|
| text with `body.ticket_view` | as text (a `ticket_view.light: true` update is a quiet status update of a ticket the phone already lists: only title, status, started, running, summary, agent, updated_at; the phone overlays them on its last full snapshot; the relay treats it like any other), and: `body.update` is set (schema), `body.ticket_view` is at most 16384 bytes as compact UTF-8 JSON (else `422 invalid`), and every attachment `blob_id` was uploaded by the sender with that `size` (another sender's or a missing blob → `404`, a wrong size → `422`). The relay never reads the snapshot otherwise |
| text (phone fields) | `body.client_id`, `attachments`, `voice`, `location` and `feedback` are set only by the relay on the texts it builds for `POST /v1/phone/send`; a workspace text with any of them → `422 invalid` |
| text, question | to a workspace: pair rule `text` from → to. `to: "ph_…"`: that phone is paired (signed in) and the sender is on its list, else `403 not_allowed` ("That phone is not paired with <name>. In the relay admin, open Phones and tick <name> …"). `to: "phones"` = every paired phone with the sender on its list (none = stored, reaches nobody). Only text and questions go to phones |
| answer | `reply_to` is a `question` that `to` sent to `from` (questions to `phones` / `ph_…` are answered by phones only, `POST /v1/phone/answer`). `ticket` and `question_id` are copied from that question, not trusted from the sender |
| file | pair rule `files`, and the blob was uploaded by the sender; `size` and `sha256` must match the stored blob |
| delegate / start | pair rule `delegate` / `start`. The relay does **not** check the allow; the receiver does (local-files.md) |
| allow | `reply_to` is a delegate/start that `to` sent to `from` |
| refresh-hint, webhook | only made by the relay itself |
| control | only made by the relay, from `POST /v1/phone/control` (a workspace posting one → `403`) |

3. **Same id twice:** identical message → `200 {id, duplicate: true}`, nothing new is stored. Same id, different content (or another sender) → `409 conflict`.
4. **Only the receiver** can fetch and ack its inbox messages.

## Workspace API

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/v1/whoami` | – | `{id, name, description, tags, icon, color, look_by, phones: n, pending}` (`icon`/`color`/`look_by`: look.md): the approved values, plus `pending` = `{description: string\|null, tags: [..]\|null, at}` (only the proposed fields are set; `rev` identifies this exact proposal) or `null` |
| PATCH | `/v1/me` | `{description?: string ≤ 280, tags?: [string ≤ 24, ≤ 8 items]}` (at least one) | `202 {…whoami, status: "pending"}`. The change is only a proposal: the owner must approve it in the admin panel, and until then the old values stay in effect everywhere (directory, refresh snapshot, phones). One pending change per workspace; a new one replaces it. `description` is one line of plain text, characters from Unicode categories L, M, N, P, S and Zs only (no control, newline, bidi or zero-width characters), NFC-normalised, no Default_Ignorable_Code_Point characters (variation selectors, U+034F, U+3164, ...) or U+2800, at most 2 combining marks in a row; tags are lowercase `[a-z0-9-]`, 1–24 characters. Admin-set values follow the same rules. Writes only the pending fields, only while the calling token is still current (else `401`). Bad input → `422 invalid` |
| PATCH | `/v1/me` (look) | `{icon?: <id>\|null, color?: <token>\|null}` (at least one; look.schema.json `me_look_patch`) | `200 {…whoami}`. Applied at once, not pending; sets `look_by = workspace`. Left out = unchanged, `null` = default. One bad value → `422 invalid`, nothing stored. Look fields mixed with `description`/`tags` or any other field → `422` (send them on their own). Not part of `workspaces.json`: no version bump, no refresh-hint (look.md, vectors/look-v1.json `me_patch`) |
| POST | `/v1/heartbeat` | `{mobile_mode: {on, since, ends_at, machine, ended?}}` | `200 {mobile_mode}` (the stored value, as phones see it). See **Mobile mode** below |
| POST | `/v1/messages` | one message | `201 {id}` (see rules above) |
| GET | `/v1/inbox?wait=0..30` | – | `{items: [message…], next: null}` not yet acked, oldest first, max 100. `wait` = long-poll seconds |
| POST | `/v1/inbox/ack` | `{ids: [m_…]}` | `204`. Acked messages are no longer delivered (the admin can still read them). The relay keeps the ack time; for a phone's text it is that text's `delivered_at` (Phone API) |
| POST | `/v1/blobs` | raw bytes, max 100 MB | `201 {blob_id, size, sha256}` |
| GET | `/v1/blobs/<blob_id>` | – | raw bytes; only for the uploader, receivers of a `file` message with this blob, and the workspace a stored phone text names it in (`body.attachments[].blob_id`, `body.voice.blob_id`, `body.feedback.pins[].voice_blob_id` of a phone text whose `to` is exactly the calling workspace; never via `to: phones`), else `404`. That access lasts as long as the phone text is stored: removing the workspace from the phone or signing the phone out does not take it back. Always served as `application/octet-stream` |
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
| GET | `/v1/phone/workspaces` | – | list of `{id, name, description, tags, icon, color, online, last_seen, open_questions, muted_until}` (only workspaces this phone may reach; `icon`/`color` = the workspace look or `null`, look.md: unknown values and missing fields fall back to letter + Automatic colour). `online` = called the relay in the last 2 minutes (unchanged); the phone itself shows a workspace as online while `last_seen` is at most 5 minutes old. `muted_until`: `null`, a time, or `"forever"`; plus `mobile_mode` = `{on, since, ends_at, machine}` (always present; `on: false` and the other three `null` when off; see **Mobile mode**) |
| PATCH | `/v1/phone/workspaces/<ws>` | `{muted_until: <time> \| null \| "forever"}` | `200` the workspace item as listed. While muted (`"forever"`, or a time in the future) the relay sends this phone no push for anything from that workspace (texts and questions); messages are still stored and listed. `null` or a past time = not muted. A workspace not on the phone's list → `404` |
| PATCH | `/v1/phone/groups/<host ws>/<grp id>` | `{muted_until: <time> \| null \| "forever"}` | `200 {host, id, muted_until}`. Mutes ONE group chat (key = host + id) for this phone: no push for a message whose `body.group` or `body.group_ref` names that group (the host's other messages are unaffected). `null` or a past time = not muted. A host not on the phone's list → `404`. At most 100 group mutes per phone (`422 invalid` beyond). See **Muted** |
| DELETE | `/v1/phone/workspaces/<ws>` | – | `204`. Drops the workspace from this phone's list (same as the admin unticking it: the workspace gets a refresh-hint and can no longer reach the phone). Only an invitation adds it again. Not on the list → `404` |
| GET | `/v1/phone/questions` | – | list of `{message, workspace_name}`, open questions only (sent to `phones` or to this phone by a workspace on its list) |
| GET | `/v1/phone/messages?after=&limit=` | – | list of `{message, workspace_name, delivered_at, client_id}`, newest first: `text` messages that workspaces on its list sent to this phone or to `phones`, and the texts this phone sent to them (`workspace_name` = the other side). General texts (no `ticket`) are listed like all others. `delivered_at` = when the receiving workspace acked the phone's own text (`POST /v1/inbox/ack`), else `null`; `client_id` = the text's `body.client_id`. Both are `null` on workspace texts. See Phone app v3 |
| GET | `/v1/phone/updates?workspace=&ticket=&after=&limit=` | – | A read view over the same stored `text` messages as `/v1/phone/messages` (no second store, nothing is written): only texts with `body.update` that a workspace sent to this phone or to `phones`, filtered by the phone's workspace list **as it is at read time** (a workspace removed from the list disappears at once). **Grouped** (no `ticket`): one item per (workspace, ticket) with its newest update, newest first, at most `limit` (1–100, default 50) items; no paging, `next` is always `null`; `workspace` optionally narrows it. **One ticket** (`ticket` + `workspace`): that ticket's updates, newest first, `limit` per page; `after` = the `id` of an item of this same filtered view (the last item of the previous page), `next` = the last item's `id` when more exist, else `null`. `ticket` without `workspace` → `422 invalid`; an `after` that is not in this phone's filtered view of that ticket → `422 invalid`; a `workspace` that is not on the phone's list answers exactly like an unknown one: `200 {items: [], next: null}` (never `403`, so nothing tells them apart). Items: `{id, workspace, workspace_name, ticket, key, kind, title, text, reply_to, at, ticket_view}` (`key` = the ticket's display key from the message, e.g. `DM1-12`, or `null`); `title`/`text` are plain text from the message, never HTML `ticket_view` = the message's `body.ticket_view` (message.schema.json), else `null`; in the **grouped** view it is the newest `ticket_view` of that ticket (looked for in the same bounded rows as the title), so a newer update without one keeps the last snapshot. The relay passes it through as stored |
| POST | `/v1/phone/blobs` | Body = the raw bytes, any `Content-Type` (image/jpeg, image/png, image/heic, application/pdf, audio/m4a, text/plain, application/octet-stream, …), max 25 MB | `201 {blob_id, size, sha256}`. `413 too_large` over 25 MB, `422 invalid` when empty. Stored like workspace blobs (encrypted at rest), kept **90 days** after the upload, then deleted (`404`). Readable only by this phone (`GET /v1/phone/blobs/<id>`) and by the workspace a text of this phone names it in (`GET /v1/blobs/<id>`). A retried upload makes a new blob; an unused one simply expires. The `Content-Type` is not stored or checked: every blob is served as `application/octet-stream`. No upload rate limit or storage cap in v3 besides the 25 MB per blob |
| GET | `/v1/phone/blobs/<blob_id>` | – | raw bytes (`application/octet-stream`) of a proof file a workspace on the phone's list named in a `body.ticket_view` attachment of a text it sent to this phone or to `phones` (the same filter as `/v1/phone/messages`), or of a blob this phone uploaded; anything else, an unknown id included, answers `404` |
| POST | `/v1/phone/answer` | `{question_message_id, answer, client_id}` | `201 {id, client_id}`. The relay builds the `answer` message (`from: ph_…`, `answered_by: human:<phone name>`, `body.client_id`, routed as above). Same `client_id` from this phone again → `200 {id, client_id, duplicate: true}` with the first answer's id (checked before the 409, so a retry of the winning answer is not a conflict). First answer wins; later answers from any phone → `409 already_answered` |
| POST | `/v1/phone/send` | `{to: ws_…, client_id, text?, ticket?, general?, reply_to?, attachments?, voice?, location?, feedback?}` (phone-api.schema.json `send_request`) | `201 {id, client_id}`. A `text` message from the phone, built by the relay (see Phone app v3). `to` must be on the phone's list (`403 not_allowed`). Same `client_id` from this phone again → `200 {id, client_id, duplicate: true}`, no second message (the relay does not compare the content) |
| POST | `/v1/phone/control` | `{to: ws_…, control: "mobile_mode_off", client_id?}` (phone-api.schema.json `control_request`) | `201 {id, client_id}`. The relay stores a `control` message `from: ph_…`, `to` the workspace, `body: {control, client_id?}`. `to` must be on the phone's list (`403 not_allowed`), an unknown `control` value → `422 invalid`. Same `client_id` again → `200 {id, client_id, duplicate: true}`. Not listed in any phone view (`/v1/phone/messages` shows `text` only). See **Mobile mode** |
| POST | `/v1/phone/transcribe` | Body = the audio bytes, `Content-Type: audio/m4a` (also `audio/wav`, `audio/webm`), max 10 MB / 2 min, optional `?language=de` (`de`, `en`, `de-CH`, …; else the language is detected, or `de-CH` when the phone's `swiss_german` setting is on: Deepgram nova-3 with `language=de-CH`) | `200 {text, language, duration}` (`duration` in seconds). `503 transcription_off` when the admin set no Deepgram key (the app then uses on-device speech), `502 transcription_failed` when Deepgram fails or is unreachable, `429 rate_limited` after 30 calls a minute per phone, `413 too_large`, `422 invalid` (type, empty, language) |
| POST | `/v1/phone/signout` | – | `204`. Deletes the token and the push registration; the old token gets `401` from now on |
| GET | `/v1/phone/speech/<message_id>` | optional `?lang=de\|en` | `200` `audio/mpeg`: the text read aloud (see Speech). `404` unless the message is a text to this phone or to `phones` from a workspace on its list (the `/v1/phone/messages` filter) **and** (it has `body.speak` and the phone's `speak` setting is not `never`, or the setting is `always`). Empty spoken text → `404`. `?lang` other than `de`/`en` → `422 invalid`. `402 tts_cap_reached`, `503 tts_off`, `502 tts_failed` |
| GET | `/v1/phone/settings` | – | `{speak, swiss_german, tts_cap_usd, tts_used_usd_month, mute_all_until, group_mutes}` (`mute_all_until`: `null`, a time or `"forever"`; `group_mutes`: the ACTIVE group mutes `[{host, id, muted_until}]`; both absent from an older relay = off/none). Defaults: `auto`, `false`, `10`. `tts_used_usd_month` = read-aloud cost of this phone in the current calendar month (UTC) |
| PATCH | `/v1/phone/settings` | `{speak?: auto\|always\|never, swiss_german?: bool, tts_cap_usd?: 0..100, mute_all_until?: <time> \| null \| "forever"}` (at least one) | `200` the settings as for GET. A bad value → `422 invalid`; unknown fields are ignored (common.md) |
| POST | `/v1/phone/invitations/redeem` | `{code}` (phone auth) | `200 {workspaces: [{id, name}]}` = the invitation's workspaces, now all on this phone's list (ones already there stay). The code comes from the same `orch://pair?relay=…&code=pc_…` link or QR as pairing and works once: unknown → `404 not_found`, used or expired → `410 gone`. The phone entry the admin made with that invitation is removed (it was never paired); the added workspaces get a refresh-hint. At most 10 calls a minute per phone, else `429 rate_limited` |

## Mobile mode

Shapes: `phone-api.schema.json` (`heartbeat_request`, `mobile_mode`, `control_request`), `message.schema.json` (`control`). Test vector:
`vectors/mobile-mode-v1.json`. Mobile mode = the person left the desk: the workspace keeps its computer awake and sends every question to the
phone. The relay only stores the flag, shows it to phones, pushes three kinds of news and carries one phone request back.

**Heartbeat (`POST /v1/heartbeat`, workspace auth).** The workspace sends `{mobile_mode: {on, since, ends_at, machine, ended?}}`
at least every 60 s while Mobile mode is on, and once when it changes (also when it turns off). `on` is required (bool). While `on` is
true: `since` and `ends_at` are UTC times (`ends_at` = when the lease runs out), `machine` is a display name of the computer, one line of
plain text, 1 to 60 characters, NFC, same character rule as `update.title` / the `PATCH /v1/me` description (letters, marks, numbers, punctuation, symbols, spaces; no control, bidi, zero-width or other format characters; schema `machine_name`; 422 otherwise), `ended` is not allowed. While `on` is false: `since`, `ends_at` and
`machine` must be `null` or left out; `ended` (optional) says why: `off` (someone turned it off), `lease` (the time ran out) or `restart`
(the computer restarted). A bad body → `422 invalid`. The relay keeps one value per workspace (the last one) and replaces it as a
whole. A workspace that never sent a heartbeat is `{on: false}`. Any authenticated call of the workspace counts as "heard from it"
(`last_seen`), the heartbeat is the only call that changes the flag.

Expired leases are immediately shown as off; the next sweep clears the stored flag and sends `mobile_mode_ended` with `ended: lease`, instead of an unreachable push.
Heartbeats per workspace per rolling minute: at most 6 that repeat the current on/off state, at most 20 that change it, and at most 30 in all (counted right after auth, before the body is read); beyond that `429 rate_limited`; `mobile_mode_ended` pushes have a ten-minute per-workspace cooldown (off transitions are still stored).

**Phones see it:** `GET /v1/phone/workspaces` items carry `mobile_mode: {on, since, ends_at, machine}` (all `null` but `on: false` when off).
The phone's own mute still wins: a muted phone gets no push below and shows "muted, but <machine> is in Mobile mode".

**Pushes** (APNs, to every paired phone that has the workspace on its list and has **not** muted it; a muted phone gets none, a phone
that is not paired with the workspace never gets one). Payload: `{"aps": {"alert": {"title": "<workspace name>", "body": "<text>"}, "sound": "default"},
"workspace": "ws_…", "type": "mobile_mode", "kind": "<kind>"}` with no `message_id` / `text_id`; tapping opens the workspace.

| `kind` | When | Body text |
|---|---|---|
| `mobile_mode_unreachable` | Mobile mode is on and the relay has not heard from the workspace for 5 minutes. Once per outage | "Can't reach <machine>. Your answers wait until it is back." |
| `mobile_mode_back` | the workspace is heard from again (a heartbeat with `on: true`) after `mobile_mode_unreachable` | "<machine> is back." |
| `mobile_mode_ended` | a heartbeat with `on: false` after one with `on: true` (also right after `mobile_mode_unreachable`) | `ended: lease` "Mobile mode ended: the time ran out.", `restart` "Mobile mode ended: the computer restarted.", otherwise "Mobile mode was turned off." |

`<machine>` = the last `machine`, else the workspace name. The relay checks for silent workspaces every 60 s. A heartbeat with
`on: false` for a workspace that was already off pushes nothing. Turning on pushes nothing (the person just did it).

**Turn off from the phone (`POST /v1/phone/control`).** `control: "mobile_mode_off"` is the only value. The relay builds the message
(`type: "control"`, `from` = the authenticated phone, `to` = the workspace) only for a workspace on that phone's list; the workspace
cannot post this type and the phone cannot set `from`. It reaches the workspace through its normal inbox. **The workspace must act on it
only when** `from` is a phone id in the `phones` list of its last `GET /v1/refresh` (the phone is still paired), **and** `created_at` is at
most 10 minutes old (an old request is acked and ignored, so a stale "off" cannot end a later Mobile mode). It then turns Mobile mode off, acks the
message, and sends a heartbeat with `on: false, ended: "off"`. The relay does not know whether the workspace obeyed.

## Phone app v3 (messenger)

Shapes: `phone-api.schema.json` (requests and responses), `message.schema.json` (the stored text). Test vector:
`vectors/phone-v3-v1.json`. Every phone write from app v3 carries a `client_id` (a UUID the phone keeps for that message on every
retry). It is optional so the app before v3 keeps working: a write without `client_id` is stored as before, never
deduplicated, and its response has `client_id: null`. One namespace per phone across `send` and `answer`: a `client_id` this phone already used on either route answers
`200 {id, client_id, duplicate: true}` with the stored message's id, whatever the new body says (nothing is compared or
stored), for as long as the relay keeps that message. Rate limits in v3: only redeem (10 a minute per phone) and transcribe
(30 a minute); there is no send rate limit. Uploads: max 25 MB per blob, at most 1 GB per phone in 24 h (else
`429 rate_limited`) and at most 4 uploads in progress at once per relay (others wait); a blob the phone uploaded but
never named in a sent text is deleted after 24 h. Blob downloads carry `X-Content-Type-Options: nosniff` and
`Content-Disposition: attachment`.

**Send → stored text.** The relay builds a `text` message `from: ph_…`, `to` from the request, `ticket` and `reply_to` when
set (not null), and `body` = `{client_id, general: true (only when sent true), text, attachments, voice, location, feedback}`
(only the fields sent). Checks: at least one of `text`, `attachments`, `voice`, `location`, `feedback`; `general: true` and a
`ticket` together → `422`; `feedback` needs `ticket`; `reply_to` must be a text in this phone's `/v1/phone/messages` view
with that workspace, else `422`; every `blob_id` (attachments, `voice.blob_id`, a pin's `voice_blob_id`) must be a phone
upload of this phone (else `404 not_found`), and an attachment's `size` must equal the stored size (else `422`).

| Request | Means |
|---|---|
| `general: true` | The workspace's **General** conversation: no ticket. |
| no `ticket`, no `general` | **New topic**: the workspace starts a ticket for it and acks it (below). |
| `ticket` | A message in that topic. |
| `attachments` | `[{blob_id, kind: image\|file\|voice, name, size, mime, duration?}]`, 1–10 phone uploads. Photos are JPEG, at most 2048 px, without location data (the phone does this). `kind`, `name` and `mime` are what the phone says, not checked by the relay: the workspace must not trust them (look at the bytes) and must clean `name` before using it as a file name (no `/` or `\`, no leading dots, no control characters). |
| `voice` | A voice memo: `{blob_id, transcript, lang, lang_source: detected\|setting\|corrected}`. The agent works from `transcript` (empty when nothing could be transcribed). |
| `location` | `{lat, lon, label?, accuracy_m?}`, sent once. |
| `feedback` | On one artifact revision of the ticket: `{artifact_id, artifact_rev, verdict: approve\|changes, pins: [{n, anchor, text?, voice_blob_id?, transcript?}]}`. `approve` = "Looks good" (pins may be empty), `changes` = at least one pin; a pin has `text` and/or `voice_blob_id`. Anchors: `html` {selector and/or quote, offset (scroll px), viewport_w}, `pdf` {page, x, y}, `image` {x, y}; x/y are fractions 0..1 from the top-left. Feedback is never an approval to publish (that is always a question answer). |

**General vs topics (one rule).** `/v1/phone/messages` lists every text both ways; the relay never rewrites a stored text.
- **Workspace texts:** `ticket` set = that topic; otherwise (`general: true`, or no `ticket` and no `general`) = General.
  Workspaces should set `general: true` on General texts; an update in General must (schema).
- **The phone's own texts:** `general: true` = General; `ticket` = that topic; neither = a **pending new topic** until a
  workspace ack with `reply_to` = its id names the ticket (then the phone shows it in that topic).
- **Topic started from General:** a workspace text without `ticket` whose `reply_to` is a phone text that started a topic
  (`orch relay topic --from`, or a new-topic text) belongs to that topic (the workspace sets `ticket` itself), and the phone
  shows that originating General text first in the topic (it also stays in General, with the "started" chip).

**Receipts.** ✓ = the relay stored it (`201`/`200`). ✓✓ = `delivered_at` is set (the workspace acked it from its inbox).
**Started** = a workspace text with `body.update.kind` `ack` or `working` and `reply_to` = the phone text's id. The
workspace **must** set `reply_to` on the ack (and on `working`) for a phone text; for topic updates the relay does not
check it (older acks without `reply_to` stay valid), in General the schema does; the ack of a new topic carries the new
`ticket` and its `key`, which moves the phone's text into that topic. Started ends (back to ✓✓) when a later text on that
ticket is a `result`, `failure`, `stopped` or `question` update, a question, or carries a `ticket_view` with `running: false`
or `status: "waiting"`; a later `ack`/`working`
for the same text starts it again. **In General** the same receipts work without a
ticket: a workspace text with `body.general: true`, no `ticket`, `reply_to` = the phone's General text and `body.update.kind`
`ack` or `working` (only those two; no `title` needed, no `ticket_view`). These are stored and listed in
`/v1/phone/messages`, never pushed, and not part of `/v1/phone/updates` (that view is per ticket).

**Speech** (`GET /v1/phone/speech/<message_id>`). A workspace marks a text worth hearing with
`body.speak = {lang: de|en, summary?: ≤ 600}`. Spoken text = `summary` if set, else `text`; URLs become "link", `*`, `` ` `` and
`#` are dropped, whitespace runs become one space; over 900 characters (≈ 60 s) it is cut after the last `.`, `!` or `?`
followed by a space within the first 900, else at the last space, else at 900 (`speech_text` in the vector). Language =
`?lang` if given (`de` or `en`, else `422 invalid`), else `speak.lang`, else `en`; voice `de` → `aura-2-julius-de`, `en` → `aura-2-thalia-en` (Deepgram Aura-2,
the relay's one Deepgram key, `/admin/api/voice`). The relay makes the audio on the first request and caches it per
(message, language); cached audio is served free and always, even over the cap. Another language for the same message is
a new, paid generation and counts against the cap. An empty spoken text (nothing left after cleaning) → `404`. Cost = USD 0.030 per 1,000 characters
spoken, counted per phone and calendar month (UTC) when audio is made. If `tts_used_usd_month` + this cost would pass the
phone's `tts_cap_usd` → `402 tts_cap_reached` (cap 0 = never make new audio). No Deepgram key → `503 tts_off`; Deepgram
failing → `502 tts_failed`. The phone then uses its own voice.

**Settings** live on the relay per phone (`GET`/`PATCH /v1/phone/settings`): `speak` (`auto` = a play button on texts
marked `speak`, `always` = on every workspace text, `never` = none), `swiss_german` (transcription in `de-CH`),
`tts_cap_usd` (0–100, default 10).

**Artifacts** (`body.ticket_view.attachments`, message.schema.json): kinds `image`, `file` (blobs) and `link`, `html`
(a published page or app), `pr`, `commit` (url kinds; a PR's state in `status`). `id` = `a_` + the first 12 hex
characters of sha256(`"<evidence type>\n<ref>"` (UTF-8), where `<evidence type>` is the ticket evidence `type`:
`pr`, `commit`, `file`, `url`, `command` or `note` (ticket.schema.json), and `<ref>` its `ref`; or `"link\n<url>"` for
ticket references) stays the same across revisions (section `artifact_ids` of `vectors/phone-v3-v1.json`);
`rev` names the revision (blob sha256, commit sha, publish id or deploy rev). Feedback points at (`id`, `rev`).
ticket.schema.json is unchanged: the phone attachments are made from evidence and references at send time, `id` is derived
from (type, ref) and `rev` from the content (blob sha256, commit sha, publish id), so nothing new needs storing.

**Questions** (`body` of a `question`): optional `previews: {"<option>": "<attachment id>"}` (A/B choices, approve with a
preview) and, for permission questions (options `Once` / `Always` / `No`), optional `scope` (shown as "Always allow
<scope>").

Push for a new question (APNs): `{"aps": {"alert": {"title": "<workspace name>", "body": "<question text, max 120 chars>"}, "sound": "default"}, "message_id": "m_…", "workspace": "ws_…"}`. Tapping opens that question.
Push for a new text to a phone (`ph_…` or `phones`): same `aps`, plus `"type": "text", "text_id": "m_…", "workspace": "ws_…"` (no `message_id`); tapping opens the messages with that workspace.
Work updates (`body.update` on a text, message.schema.json): the relay pushes a text with `update.kind` = `result`, `question`,
`failure` or `stopped` as above (push body = `update.title` + ": " + the first line of the text, max 120 chars); `ack`, `working`
and `note` are stored and listed (`/v1/phone/messages`, `/v1/phone/updates`) but **never pushed**. A text without `update` is
pushed as before. The filter runs in the relay, not in the sender.
**Text push budget** (per sending workspace and phone, kept in the relay's memory): at most 1 text push per 10 s and 30 per hour
window (the window starts with the first push after the last one ended) for each (workspace, phone) pair; a text over the budget is still stored and listed, only its push is skipped.
Questions are not limited by it. The budget applies after the update-kind filter (quiet kinds never use it up).
**Ticket key**: a message may carry `key` (the display key of its `ticket`, e.g. `DM1-12`, message.schema.json). A `key` that does not match `^[A-Z0-9]{2,4}-[1-9][0-9]{0,8}$` is dropped
on intake (the message is kept, without a key). The relay keeps a valid key
like any top-level field (so `/v1/phone/questions` and `/v1/phone/messages` show it in `message.key`), copies the question's
`key` onto every answer together with `ticket` (an answerer's own `key` is dropped), lists it in `/v1/phone/updates` items, and
puts it first in the push body: `"DM1-12 · <body as above>"` (still max 120 chars). Pushes with a ticket also carry `"ticket"`
and `"key"`. The phone only displays the key; `ticket` stays the reference.
Pushes go to the phones the message is for: `phones` = every paired phone with the sender on its list, `ph_…` = that phone.
**Muted:** no push to a phone while ANY of these is active (`"forever"` or a time in the future; a past time is off): its **mute all** (`mute_all_until`, every push of any kind, Mobile-mode pushes included), its mute of the **sending workspace** (`muted_until`), or its mute of the **group** named in the message's `body.group` or `body.group_ref` (`PATCH /v1/phone/groups/…`, matched on host AND id). The message is stored and listed as usual; only the push is skipped. The phone computes durations in local time and sends UTC ("1 hour", "Until tomorrow 8:00", "Until I turn it back on" = `"forever"`). vectors/mute-v1.json.

Admin prompt for a workspace (shown once): `orch addon add relay --yes` then `orch relay connect https://relay.severin.io --workspace ws_… --token orn_…`
(+ the `onboarding.sh/.ps1` line for machines without orch). `connect` runs `orch init` if needed, checks `/v1/whoami`,
writes `.orch/secrets/relay.json`, copies the `orch-relay` skill (shipped inside the CLI), adds the AGENTS.md block, then runs `orch relay refresh`.

Phone onboarding link (from the admin portal, also as QR code, valid 24 h, one use):
`orch://pair?relay=https%3A%2F%2Frelay.severin.io&code=pc_<22 chars>`

## Subscribers (other systems that listen)

A **subscriber** is another system or agent (a team chat bot, a script, a monitoring tool, another AI agent) that the admin
adds in the portal. It sees what a paired phone with the same workspace list would see from workspaces to people, nothing
else: never workspace-to-workspace traffic, shared tools, secrets, webhook payloads, or texts a workspace sent to one
phone (`to: ph_…`). Workspaces change nothing: agents keep sending to `phones`. Event shape: `subscriber-event.schema.json`;
test vectors (events and signatures): `vectors/subscriber-v1.json`.

**Scope (checked on every call).** The workspaces a subscriber sees = its `workspaces` plus the **current** members of its
`groups`, worked out at read time: a workspace that leaves a group or is removed from the list disappears at once,
including from catch-up and from an open stream. Only events stored at or after the subscriber's creation are shown.

**Auth.** The link `https://relay.severin.io/v1/sub/<token>` carries the token: `sub_` + 43 characters (32 random bytes,
base64url), shown once, stored only as its SHA-256 hash. Every route also accepts the token as `Authorization: Bearer sub_…`
with the literal `-` in its place (`/v1/sub/-/events`), so it need not sit in URL logs. Unknown, rotated or removed token →
`401 unauthorized`. At most **60 calls a minute** per subscriber (every route, opening a stream included) → `429 rate_limited`.

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/v1/sub/<token>/events?after=&limit=` | – | `{items: [event…], next}`: events in the subscriber's view **oldest first**, after the event `after` (an event `id`; left out = from the start), at most `limit` (1–100, default 100). `next` = the id to pass as `after` for the next page when the page is full or the relay stopped looking (it looks at a bounded number of stored messages per call, so `next` can come with fewer than `limit` items); `null` = the end was reached. An `after` that is no stored message → `422 invalid` |
| GET | `/v1/sub/<token>/stream` | `Last-Event-ID` header (or `?after=`) | `200 text/event-stream` (Server-Sent Events). Each event: `id: <event id>`, `event: <type>`, `data: <event JSON on one line>`. A comment line `: ping` every 25 s. With `Last-Event-ID` the stream first replays everything after that id (the same view as `/events`), then stays live; without it, only new events. The relay closes the stream when the token is rotated or the subscriber removed. At most **2 open streams** per subscriber; a third → `429 too_many_streams` |
| GET | `/v1/sub/<token>/files/<blob_id>` | – | Raw bytes (`application/octet-stream`) of a proof file named in an event the subscriber can see (`ticket_view.files`), only when **Files** is on and the admin allowed downloads (`can_download`); anything else → `404` |
| POST | `/v1/sub/<token>/answer` | `{question_id: "m_…", answer: "1–2000 chars"}` (`question_id` = the question event's `id`) | `201 {id}`. Only when the admin allowed answering (`can_answer`) and the subscriber receives **Questions**, else `403 not_allowed` ("This subscriber may only read. In the relay admin, open Subscribers and turn on Can answer questions."). A question not in its view → `404`. First answer wins, from a phone or a subscriber: a later one → `409 already_answered`. The relay builds the `answer` message `from: sub_…` (the subscriber id) to the asking workspace, `answered_by: "agent:<name> (system)"`, `ticket`, `key` and `question_id` copied from the question. The workspace records it like a phone answer, as from that system, never as a person |

**Event (v1)**, `subscriber-event.schema.json`. `v` is the format version: fields may be added, never renamed. `id` = the
stored message id (the cursor). Text is plain text, never HTML.

| `type` | From | Shown when the subscriber receives |
|---|---|---|
| `update` | a text with `body.update` a workspace sent to `phones`; `kind` = `started` (the update kind `ack`), `working`, `note` | **Updates** |
| `update` | the same, `kind` = `result`, `failure`, `stopped` | **Results** |
| `update` | the same, `kind` = `question` | **Questions** |
| `question` | a `question` a workspace sent to `phones` | **Questions** |
| `answered` | the `answer` to such a question (from a phone or a subscriber) | **Questions** |
| `text` | a text without `body.update` a workspace sent to `phones` | always |

Fields: `{v, id, type, workspace: {id, name}, ticket, key, at}` on every event (`ticket`/`key` may be `null`), plus:
`update` → `kind, title, text, ticket_view`; `text` → `text`; `question` → `question_id` (= `id`), `text`, `title`,
`options`, `answerable` (this subscriber may answer and no one has yet), `answered` (`null`, or `{answer, answered_by}`
at read time); `answered` → `question_id` (the question's id), `answer`, `answered_by` (a display name: the phone's name,
or `<name> (system)`). `ticket_view` = a smaller copy of the message's `body.ticket_view`, else `null`: `{title, status,
agent, summary, done, total, refs: [{kind, title, url}], files}`, no checklist and no history; `files` (`[{name, size,
blob_id}]`, the image and file attachments) only when **Files** is on, else `[]`.

**Push (optional).** With a `push_url` the relay also POSTs every event, oldest first, one at a time, as the JSON body with
`Content-Type: application/json` and:
- `X-Orch-Event-Id: <event id>`, `X-Orch-Timestamp: <unix seconds>`,
- `X-Orch-Signature: v1=<lowercase hex HMAC-SHA256(push secret, timestamp + "." + body)>` (the push secret is
  `whsec_` + 43 characters, shown once when push is turned on; the receiver should refuse a timestamp older than 5 minutes).

A `2xx` within 10 s counts as delivered. Anything else (other status, timeout, refused address) is retried after 1 min,
5 min, 30 min, 2 h and 6 h, in order (later events wait). After the last retry fails the push state becomes `failing` and the
relay stops trying until the admin presses **Try again now** (`POST …/push/retry`). Pull keeps working all the time.
**Address checks, on every request:** the URL must be `https://` with a host name or a public IP; the host is looked up and
every address must be public (no loopback, private, shared/carrier-grade `100.64.0.0/10`, link-local, multicast, reserved,
documentation or unspecified ranges, IPv4 and IPv6 incl. mapped/6to4/Teredo/NAT64 forms); the request goes to exactly the
checked address; redirects are never followed; connect timeout 5 s, total 10 s; the response body is not read.

**Activity log.** The relay logs every pull call, stream, file, answer, push attempt and admin change per subscriber
(`GET /admin/api/subscribers/<id>/log`): the newest 200 entries, kept 30 days.

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
| GET / POST | `/admin/api/workspaces` | POST: `{name, description, tags: [], icon?, color?, group?: "grp_…", new_group?: "<name>"}` (at most one of `group` / `new_group`; `icon`/`color` given → `look_by = admin`) | list of `{id, name, description, tags, description_by, tags_by, icon, color, look_by, online, last_seen, unread, pending, group}` (`last_seen` null until the workspace first calls; `pending` as in whoami, or `null`; `group` = `grp_…` or `null`) / `201 {id, token, prompt, group, shared?}`. With `group` (an existing group) or `new_group` (creates a group with the defaults of `POST /admin/api/groups`), the workspace joins it and gets the group's tools at once (see Groups); `shared` = `{skills, mcp, credentials}` counts it got. Unknown group or both fields → `422`, a taken `new_group` name → `409`; nothing is created then. Without either, the workspace is in no group and gets no tools (the admin portal always sends one) |
| PATCH | `/admin/api/workspaces/<id>` | `{name?, description?, tags?, icon?, color?, group?: "grp_…"}` | `200` (shows up in the next refresh). Admin-set description/tags are marked `description_by` / `tags_by` = `admin`. `icon`/`color`: only while `look_by` is `null` or `admin` (sets `look_by = admin`); once the workspace sent its own look (`look_by = workspace`) → `409 conflict` ("This workspace chooses its own icon.") and nothing in the body is stored (check and write in one transaction; a new token keeps the look and `look_by`); bad value → `422` (vectors/look-v1.json `admin_patch`). `group` moves it to that group (unknown → `422`): it gets the new group's tools and keeps the ones it has |
| GET / POST | `/admin/api/groups` | POST: `{name, colour?, defaults?: {skills?, mcp?, credentials?}, talk?}` | `{items: [group]}` by name / `201 group`. group = `{id: "grp_…", name, colour, defaults: {skills, mcp, credentials}, talk, members: [ws…], gives: {skills, mcp, credentials}}`. `name`: one line of plain text (description rule), 1–40 characters, unique ignoring case (else `409 conflict`). `colour`: one of `teal, violet, amber, blue, pink`; left out = the one used least. `defaults` (each `true` when left out) = the kinds of shared tools members get; `talk` (default `true`) = members may send each other messages and files. `gives` = how many shared items of each kind a member gets now |
| PATCH | `/admin/api/groups/<id>` | `{name?, colour?, defaults?: {…}, talk?}` | `200 group`. A default kind turned on is given to the current members at once: turning a default on grants all items of that kind, including any the admin took away from a member before; turned off takes nothing away. `404` unknown group |
| DELETE | `/admin/api/groups/<id>` | – | `204`. Members stay, keep their tools and are in no group |
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
| GET / POST | `/admin/api/subscribers` | POST: `{name, workspaces?: [ws…], groups?: [grp…], kinds?: {updates?, questions?, results?, files?}, can_answer?, can_download?, push_url?}` | `{items: [subscriber], next: null}` by name / `201 {subscriber, token, link, push_secret}`. subscriber = `{id: "sub_…", name, workspaces, groups, kinds: {updates, questions, results, files}, can_answer, can_download, push: null \| {url, state: ok\|retrying\|failing, fails, next_try_at, last_ok_at}, created_at, last_seen, streams}` (`streams` = open streams now). `name`: one line of plain text (description rule), 1–40 characters. At least one workspace or group, all existing (else `422`). `kinds` default: questions and results on, updates and files off; `can_answer` and `can_download` default `false` (read-only). `can_answer: true` needs `kinds.questions` on (else `422`, also on PATCH). `link` = `<public origin>/v1/sub/<token>` and `token` are shown once; `push_secret` (`whsec_…`) only when `push_url` is set, else `null`. A `push_url` that is not `https://`, has a user name or password, or names a non-public IP → `422 invalid` (host names are checked on every delivery, see Subscribers) |
| PATCH | `/admin/api/subscribers/<id>` | any of the POST fields; `push_url: null` turns push off | `200 {subscriber, push_secret}`. `push_secret` is new and shown once only when push goes from off to on (it starts with the next new event), else `null`; a changed URL keeps the secret and resets the state to `ok`. Scope changes apply on the next call and to open streams at once. `404` unknown |
| DELETE | `/admin/api/subscribers/<id>` | – | `204`. The token stops at once, open streams close, the log is deleted |
| POST | `/admin/api/subscribers/<id>/token` | – | `200 {token, link}`: a new link; the old one stops at once (open streams close) |
| POST | `/admin/api/subscribers/<id>/push/retry` | – | `200 subscriber`: state `ok`, the next delivery is tried now. `422` when push is off |
| POST | `/admin/api/subscribers/<id>/push/test` | – | `200 {ok, status, ms, detail}`: one signed test event `{v: 1, id: "test_…", type: "test", text, at}` sent now (same headers, address checks and timeouts); `status` = the HTTP status or `null`, `detail` = a plain sentence. Does not change the push state. `422` when push is off |
| GET | `/admin/api/subscribers/<id>/log?failed=` | – | `{items: [{at, what, event, result, ok}], next: null}`, newest first (at most 200). `what`: `created`, `changed`, `rotated`, `events`, `stream`, `file`, `answer`, `push`, `test`, `retry`; `event` = e.g. `DM1-12 result` or `null`; `result` = a short plain line (`200 in 140 ms`, `502 · next try 21:09`, `refused: private address`); `failed=1` = only entries with `ok: false` |

Every change under `/admin/api/shared/`, to a workspace's name/description/tags/group, to a group's `talk` or defaults, or to the rules raises `version` by 1 and sends a `refresh-hint` to each affected workspace.

### Groups

Each workspace is in at most one group (the admin portal makes the owner pick one when adding a workspace). A group only
writes the normal per-workspace assignments (`/admin/api/shared/assign`), so the refresh snapshot and every check stay as
they are:
- **Joining** (create with `group`/`new_group`, or `PATCH … {group}`): the workspace is assigned every shared item of the
  kinds in the group's `defaults`. **Leaving** (moving, group deleted) takes nothing away.
- **A new shared item** (`PUT /admin/api/shared/<kind>/<name>` for a name that did not exist) is assigned to every member
  of each group whose `defaults` include that kind. Replacing an existing item changes no assignment.
- Single items can still be taken away from one workspace with `/admin/api/shared/assign/<ws>`.
- **`talk`**: two members of the same group with `talk` on count as having a pair rule with `text` and `files` both
  ways (added to any pair rule they have; `delegate` and `start` still come only from the rules). They show in each
  other's directory, and messages and files between them pass rule 2 (Pair rule) above. `/admin/api/rules`
  lists only the rules the owner set.
So do pairing a phone (`POST /v1/phone/pair`), signing it out, and editing or deleting it: its workspaces refresh their `phones` list.
