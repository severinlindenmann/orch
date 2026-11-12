# Chat and group chat across workspaces (v1)

Status: contract for the 8 Nov build round. Owner decisions: `r-v2-chat-*`, `r-v2-fb1-*`, `r-v2-fb10-*`, `r-v2-fb2-*`
(accepted draft `round/general/`, PHONE-NOTES v2). Shapes: `chat-groups.schema.json` (NEW body fields; it includes
`message.schema.json`, which is **unchanged**). Vectors: `vectors/chat-groups/*.json`, checked by `validate.py`
(`cg_rules` holds the rules JSON Schema cannot express).

**Model (owner pick B): a group is hosted by the workspace that owns the ticket** (hub-and-spoke). The host keeps the
record and sends one normal relay message per member and one to `phones`. **No relay server change**: every message
below is an existing type (`text`, `question`, `answer`, `delegate`, `allow`, `file`) and passes the existing rules
(relay-api.md, Rules 1–4); the new data rides in `body`, which already keeps unknown fields. Checked against
`relay/src/rules.rs`: workspace→workspace messages need the pair rule of their type, `file` needs the uploader's blob,
`answer` gets `ticket`, `key`, `question_id` and `answered_by` set by the relay, phones only get `text` and `question`.

Legend: **NEW** = new field or rule from this contract. **existing** = already in message.schema.json / relay-api.md.

Words (same on dashboard and phone, PHONE-NOTES.md): **Chat**, **Group**, **"<Workspace> helper"**, **Task for Home**,
**Allow once / Always / No**, **"Finance helper is thinking…"**, **History**. The relay's admin **workspace groups**
(`grp_<name id>`, `talk`, relay-api.md "Groups") are a different thing; chat groups use ids `grp_t_…` and live only in
`body.group`.

## 1. Chat (one workspace, former General)

| Field | Status | Meaning |
|---|---|---|
| `body.general: true`, no `ticket` | existing | The workspace's Chat. Stored on the workspace's hidden General ticket (tickets.py `general: true`). |
| `reply_to` | existing | The phone text a helper answers. `ack` / `working` updates in Chat need it (schema). |
| `body.update.kind` `ack` / `working` | existing | **Thinking indicator**: `working` with `reply_to` = the person's text shows "Finance helper is thinking…" until the next helper text that is not `ack`/`working`, or **10 min** without one (same timeout on phone and dashboard, Chat and groups). Quiet: never pushed. |
| `body.by` | **NEW** | `"you"` (the person) or a `ws_` id (that workspace's helper). Places bubbles: `you` right, others left. |
| `body.via` | **NEW** | `phone` \| `dashboard` (with `by: you`), `helper` \| `dashboard` (with `by: ws_…`). |
| `body.phone` | **NEW** | `ph_…` when `via: phone` (which phone wrote it). |
| `body.day` | **NEW** | `YYYY-MM-DD`: the Chat day, by **local wall time**: the workspace's local date of `created_at`, or the date before when the local wall clock shows before 04:00 (so DST days stay right; never "minus 4 h"). The workspace sets it on every Chat text it sends; the phone groups by it and, for its own texts, uses its local date with the same 04:00 cut until the workspace's ack (which carries `day`) arrives. Never in a group message. |
| Helper identity | **NEW** (display rule) | Never sent as text: the name is "<workspace name> helper", the avatar is the workspace look (look.md) plus a small sparkle. Agents are stored in history as `agent:<name>` as today. |
| `body.refs` (cards) | **NEW** (display) | Not a wire field in v1: cards come from `task`, `group_event`, `shared_ticket`, `share`/`shared_files` and the existing `ticket_view` (§2–4). |

**Daily cut.** At 04:00 local the workspace starts a fresh helper context for Chat (UI: "Context cleared daily at 04:00 ·
Details"). Past days are **History** (read only, searchable). Nothing is deleted.

**Who stores what.** The workspace stores every Chat text both ways in its General ticket history (the record). The
relay stores messages as today. The phone keeps a local cache of what `/v1/phone/messages` lists (Chat texts are texts with
no `ticket`) and its own History index by `day`; the workspace stays the source of truth.

## 2. Group hosted by the ticket's workspace

**`body.group`** (**NEW**, on every group message, every type): `{id, host, title, members, seq?}`
- `id` = `"grp_"` + the host ticket id (`grp_t_fin14a`). One group per host ticket. **The group key is `(host, id)`
  everywhere** (storage, dedupe, phone cache), because ticket ids are unique only per workspace. No first-wins id registry: a
  receiver that holds `id` under another host keeps both groups and **never drops a real group** because another host
  used the same id (rule G7). A forged id is caught by G1/G3 (`from == group.host`), not by the id alone.
- `host` = the `ws_` that owns that ticket. **A host message's `group.id` must equal `"grp_" + message.ticket`** (rule G1).
- `title` = the host ticket title, one line 1–120 (the one title length; `shared_ticket.title` is the same). Redacted.
- `members` = `[{ws, name, look?}]` (**NEW** from messenger review: name and look from the host's directory, so a phone
  not paired with Bank can still draw "Bank helper" and its badge), host included, **≤ 8**, each `ws` once. The person
  and their phones are always in every group and are not listed. Members copy the latest list they got from the host;
  the host ignores lists from members. Receivers show the list as "per <host name>".
- `seq` = **host only, group-wide messages only** (copies every member and the phones get): +1 each. **Targeted**
  messages for one member (`delegate`, `question`, `shared_ticket`) carry **no** `seq`. Order = `seq` only;
  unsequenced (targeted) messages are ordered by receive time; `created_at` is display only. A member's view starts at its `member_added.from_seq`; a gap after that
  is shown ("a message is missing") but never waited on.

**Fan-out (host only).** For every group message the host records (its own, a member's, a phone's, a dashboard text) it
sends one copy per other member (`to: ws_…`) and one to `phones`, all as the same existing type (`text` for talk).
- `ticket` = the host ticket, `key` = its display key (existing), so old phones show it in that ticket's topic.
- `body.origin = {id, from, at}` (**NEW**) = the original message; `from` = `ws_…`, `ph_…` or `dashboard`. The host
  sends a `ph_…` in `origin.from` **only for phones paired to THAT workspace** (rule G4). A phone shows a `ph_` it does
  not know (not one of its own account's phones) neutrally as **"Other phone"**, never "You". (A relay-vouched origin,
  so the receiver need not trust the host for this, is a later improvement, not in v1.)
- **Fan-out id** (**NEW**, rule G2): every copy, to a workspace **and to `phones`** (messenger review), has
  `id = "m_" + sha256("<host>\n<origin.id>\n<to>")[:16 hex]` with `to` = `ws_…` or `"phones"` (`cg_fanout_id`). A
  retry sends the identical message → relay `200 {duplicate: true}`, never a second copy. Including `host` keeps another
  workspace from pre-claiming the id from a known `origin.id`. Receivers also dedupe on `(host, group.id, origin.id)` (the group key, rule G7).
- `body.echo_of` (**NEW**): the host's copy to `phones` of a phone's own text. A phone hides it only when `echo_of` is
  one of its own message ids (`body.phone` = this phone); the person's other phones show it as "You".
- **Push set for copies to `phones`** (**NEW**, messenger review): pushed = `question` messages, `group_event`
  `approval_needed` and `closed`, task `done` / `failed`, and texts addressed to the person (`body.to_person: true`).
  Every other copy (helper-to-helper talk, joins, queued/working) carries `body.update.kind: note` (quiet; the relay
  never pushes it). `validate.py` checks this.
- The host never forwards a message back to its sender.
- **`body.own_seq: true`** (**NEW**, optional, host → member only): the sender's own message still takes a group `seq`,
  so the host sends the sending member (only a `ws_` member; never to `phones`, never for its own or a phone's text) a
  **stub**: a `text` to `to = origin.from` with the same `group` (+ `seq`), `origin`, `by`, the text, `update.kind:
  note` (quiet) and `id` = the fan-out id of (host, origin.id, that member). The member steps over that `seq` in its
  order and never shows the stub (it sent the message itself). An older member that does not know the field keeps it as
  an ordinary group text by itself (its own name, quiet) and stays in order. This holds because an older member checks
  incoming group messages only with its built-in rules (`receive_errors`), which ignore unknown body fields and do
  not reject `origin.from` = the receiver. It runs no JSON Schema on incoming messages. In the old
  `chat-groups.schema.json` too, `body` has no `additionalProperties: false`. A receiver that does validate bodies
  against a closed schema would drop the stub, and its view would wait as before: it shows nothing, but it is no
  worse than without the stub. Phones never get it. `own_seq` anywhere else (another `to`, no `seq`, from a member) is
  invalid. Once a member has received one stub from a host, it relies on stubs for that host and never guesses
  (§5, rule "own messages").

**Phones in a group: explicit opt-in** (rule G8). A phone cannot set `body.group` (the relay builds phone texts from a
fixed field list) and cannot send receipts. So: **a phone text is a group message only when it goes to the host with
`ticket` = the host ticket and `reply_to` = a group copy the host sent to `phones`**. The group composer always sets
`reply_to` to the newest group copy and shows **"To: Finance, Home, Bank"** above the text field. Any other phone text on
that ticket (no `reply_to`, or a reply to a non-group text, an older phone, a private reply to the helper) stays a
**host-only note**: recorded on the host ticket, never fanned out. The host copies a group text as `by: you, via: phone,
phone: ph_…`, `origin.from` = that phone. Phone texts go only to the host; members get the host's copy.

**Unknown groups on a phone** (fresh install, missed `created`): the phone accepts a group message from a workspace on
its list when `from == group.host`, creates the group under `(host, id)` (**§2 wins**: a group first seen from its paired host is accepted) and shows it from that message on ("Earlier
messages are in <host name>"). There is no history request in v1.

**`body.group_event`** (**NEW**, host only, rule G3: `from` must equal `group.host`, else every receiver drops it):

| kind | needs | when |
|---|---|---|
| `created` | – | the host helper (or the person) starts the group from a ticket. Pill "Group started from ticket FIN-14 · Pay car tax 2027". |
| `member_added` | `ws`, `name`, `look?`, `from_seq` | a workspace joins (the host added it). `from_seq` = the first group `seq` it gets. Pill "Finance helper added Home to this group". |
| `member_left` | `ws`, `reason` `left`\|`removed` | the member sent `body.leave` / the person clicked Remove. |
| `approval_needed` | `ws`, `delegate`, `question_message` | the member reported its existing allow question (§3). Approval card (rules in §3.5). |
| `approved` | `ws`, `delegate`, `mode` `once`\|`always` (the allow question's words; the `allow` message's own `mode` stays `once`\|`permanent`) | the host got the member's existing `allow` message from that `ws`, with `reply_to` = that delegate. Pill "You allowed Bank once · Bank joined". |
| `denied` | `ws`, `delegate` | the member reported `task.status: denied`. |
| `closed` | – | the host ticket is done or dropped. The group is read only and moves to **History**. |

**Who may join.** Only workspaces **connected to the host**: in the host's directory (`workspaces.json`) with
`can_send.text` and `accepts_from.text` (existing pair rule or relay group `talk`). Tasks also need `can_send.delegate`,
files `can_send.files` (and `accepts_from.files` for files back). The host adds members; **members cannot add members**:
the host ignores `members` from anyone else and never takes membership from a member message. Joining needs no
approval for talk; a task needs the member's existing allow (§3). Everything fanned out keeps `origin.from` and is
untrusted data for every receiver.

**Which types carry `body.group`.** `text`, `question`, `answer`, `delegate`, `file`: yes. `allow`: **no** (the host
matches it by `reply_to` = its delegate). The member's allow question to `phones`: **no** (it is the member's own).

**What each side sees and stores.**
- **Host**: the full group log (all `seq`) on the host ticket (`ext.relay.group`, **NEW** sub-key: `{id, title, members:
  [{ws, joined_at, left_at}], seq}`), plus every message in the ticket history. It is the one record.
- **Member**: group messages **from its join time** only, stored on its own task ticket (or a hidden group record when it
  only answers). It never gets the host's files, history, other questions or refs unless a message carries them (§4).
- **Phones**: every group message (the person is in every group); cache like Chat. Group list row = `group.title`,
  member badges, last line, ticket `key`.
- **Relay**: as today (stores messages, delivers when the receiver calls its inbox).

## 3. Delegation link (Task for Home)

1. **Host → member: existing `delegate`** + `body.group` (+ `by`, `via`). Relay checks pair rule `delegate` (existing).
   An earlier permanent allow travels as `allow_token` (existing).
2. **Member: existing allow check.** With a valid allow it makes the ticket at once. Without one it makes the waiting
   ticket with the `relay:allow` question (existing `_ensure_allow_question`) and **must** also send that question to
   `phones` as an existing `question` message (wire options `once`, `always`, `no`, shown as "Allow once / Always / No" (rule G11); `scope` "tasks from <host name>";
   **without** `body.group`: it is the member's own question; the phone ties it to the group through the host's
   `approval_needed.question_message`) and **carries `body.group_ref: {host, id}`** (**NEW**: the group key it was asked
   for, never `body.group`; the phone shows buttons only when `group_ref` equals the group the card is shown in, missing or
   different means "Answer in <member>"; the question's sender must also be a member of that group, so a host cannot show it in a second group). **NEW** (rule G11): the member marks its question `body.allow_question: true`; the
   wire options are `once` / `always` / `no` and the answer text is one of them; the UI text is "Allow once / Always /
   No". Mapping (one table):

   | phone answer (wire) | `allow` message `mode` | group event |
   |---|---|---|
   | `once` | `once` | `approved`, `mode: once` |
   | `always` | `permanent` | `approved`, `mode: always` |
   | `no` | (no allow) | `task.status: denied` → `denied` |

   Parsing: the wire value is exact lowercase. A receiver also reads old wording, trimmed, whitespace collapsed,
   case-insensitive: "Allow once" → once, "Always" → always, "Ignore" / "No" → no; anything else is not an answer. The
   phone builds buttons **only** for a question with `allow_question: true` and exactly those options (§3.5 requires the
   marker). **Marker present + other words = invalid** (dropped). **Marker absent** (an old member) = the card says
   **"Answer in Bank"**, no buttons. The validator keys
   on `allow_question`, never on `scope`.
3. **Member → host: ack** = existing `text` with `body.update.kind: ack` (+ `title`), `ticket`/`key` = the member's own
   new ticket (`HOME-7`), `reply_to` = the delegate id, `body.group`, and **`body.task`** (**NEW**):
   `{delegate, ws, ticket, key, title, status, question_message?}`.
   **The host accepts `task` only when** `task.delegate` is a delegate the host sent to `from`, `from` is a current
   member, and the status moves **forward** (rule G9): waiting_start → waiting_approval → queued → working →
   done | failed | denied; a status may repeat, never go back, and the last three are final. Anything else is dropped
   and logged.
4. **Status updates** member → host: same text shape, `update.kind` → `task.status`:

| `task.status` | sent by | `update.kind` | card |
|---|---|---|---|
| `waiting_start` | **host only** (no ack yet and the member is not running) | – | "Waiting for Home to start" |
| `waiting_approval` | member, with `question_message` | `ack` | Approval card "Bank: let Finance give tasks?" |
| `queued` | member | `ack` | Queued |
| `working` | member | `working` | Working |
| `done` | member | `result` | Done |
| `failed` | member | `failure` | Failed |
| `denied` | member (the person answered No) | `failure` | pill "You said no to Bank" |

   **Review is not terminal.** When the member's ticket reaches `review` its own person has not accepted the result
   yet: the task stays `working` and the member sends once only the generic text "Ready for review in <member name>"
   (`update.kind: working`; no agent summary, no files). `done` (and the result summary) is sent only after the
   member's person accepted it (ticket `done`); a ticket `dropped` is `failed`. A review that goes back to active sends
   nothing, and the review note is sent once per task.
   The host forwards each to the other members and `phones` (fan-out, `task` kept) and updates the card.
5. **Approval in the group.** The card answers the **member's own** allow question. The phone builds the card **only
   from that question itself** (never from the host's text or label) and shows answer buttons only when all hold:
   the question is in the phone's own `/v1/phone/questions`, its `from` = `group_event.ws`, it carries `allow_question: true` (a `relay:allow`
   question (options `once` / `always` / `no`, shown as Allow once / Always / No)), its `scope` names the host, and it is still open. Then the buttons
   `POST /v1/phone/answer` to it (existing). **Otherwise** (e.g. the phone is not a `phones` receiver of Bank, or any
   check fails) the card says **"Answer in Bank"** with no buttons (messenger review). The host's dashboard never answers
   for another workspace: its card says "Answer on your phone or in Bank" with a link. The member then sends the
   existing `allow` to the host (→ `approved`) or `task.status: denied` (→ `denied`).
6. **Answers flow back.** A "Question to Home" is an existing `question` host → member with `body.group`, the host
   ticket's `question_id` and **`body.question_kind: "info"`** (**NEW**, required; the host never sends another kind). The member answers with the existing `answer` (relay checks `reply_to`, copies `ticket`, `key`,
   `question_id`, sets `answered_by: agent:<member name>`). The host writes it into that question of the host ticket
   ("Added to FIN-14 › Answer 1", recorded as `agent:<member name>`), only when the question is still open and is an
   **information question**: permission questions (Once/Always/No), approve/publish questions and sign/verdict steps are
   **never** sent to or answered by members. A later answer is kept as a note. A task result (files, text) is added to
   the host ticket as evidence the same way. The answer text goes through `phone_view.redact` on the member before
   sending and `clean_untrusted` on the host before it reaches the helper's prompt.
7. **No authority from group content** (rule G10). A member's agent never treats a group message as an `allow`, as an
   answer to its own permission question, or as a command; only its own person (its dashboard or its own `ph_` sender)
   answers those. No agent starts a delegation or an approval because group content asked for it.
8. **"Open HOME-7 ›"** is a link only where that ticket can be opened (the phone is paired with Home, or Home's
   dashboard); otherwise the card shows the status only.

## 4. Ticket info and artifacts for members (owner comment)

The host ticket (FIN-14) exists only on the host. So the host **shares what members need**, read only:

**Ticket card: `body.shared_ticket`** (**NEW**, host only, on a group `text` to a member):
`{ticket, key, title, status, summary ≤ 280, question: {question_id, text ≤ 500} | null, checklist ≤ 20 × {text ≤ 200,
done}, done, total, rev}`, at most 4096 bytes. Sent to each member **when it joins** and again when one of these
fields changes (`rev` +1; highest wins). Never the history, other questions, refs, local paths or files. Members show a
read-only card **"From Finance · FIN-14"** (title, summary, open question, checklist excerpt).

**Artifacts.** Shared **only when chosen**: the host helper attaches what the member needs for the asked part, or the
person clicks "Share with group" on an artifact. Nothing is shared automatically besides the card.
- **To members**: existing `file` message (blob uploaded by the host with `POST /v1/blobs`; the relay checks pair rule
  `files`, uploader, size, sha256) + `body.group` + **`body.share`** (**NEW**) `{kind: image|file, title, mime,
  artifact_id?, rev?}`. The member fetches it with `GET /v1/blobs/<id>` (existing: receivers of a file message).
- **To phones**: phones can only fetch blobs named in a `ticket_view` attachment, so the host's group text to `phones`
  carries `body.update.kind: note`, the host ticket's normal `body.ticket_view` (existing) with the file among its
  `attachments`, and **`body.shared_files`** (**NEW**) = those blob ids (rule G5: each must be in the attachments). The
  phone shows them as file cards in the group.
- **Member → group**: the member sends its file to the host only (`file` + `body.group` + `body.share`); the host
  re-uploads it as its own blob for the other members and phones (blobs are readable only by uploader and receivers).
  A member shares a file only after **its person's click**, or when the file is the result of the task the host gave it.
- `ticket_view` and `shared_files` never go to `ws_` receivers; the host ignores them from members. A removed member
  keeps the files it already fetched (the Members sheet says so).
- **URL artifacts** (link, html, pr, commit) are shared as text in the message; no card in v1.
- **Limits**: ≤ 25 MB per file (the phone limit), ≤ 10 files per message, types by checked bytes:
  `application/pdf`, `image/png`, `image/jpeg`, `image/heic`, `image/webp`, `text/plain`, `text/markdown`, `text/csv`.
  Anything else is refused with a plain line ("Only PDFs, pictures and text files can be shared").
- **These rules apply to every sender, host and members alike.**
- **No secrets**: never files from `.orch/secrets/`, `.env*`, key or token files, the agent's config, checked on the
  real path (symlinks resolved). All text fields (`text`, `answer`, `summary`, `question`, `checklist`, `title`,
  `group.title`, `share.title`, file names) go through `phone_view.redact` (existing: keys, tokens, passwords →
  `[hidden]`). A text file or PDF (its extracted text) that contains a secret pattern is **refused, not redacted**
  ("This file looks like it holds a password, so it was not shared"). Only a real secret match (content, or a key/
  `.env`/token file name) says "password": a file in a hidden or `secrets` folder (in the workspace or anywhere else,
  also through a link) is refused with "Files in hidden or secrets folders are not shared". A locked PDF or a PDF
  stream that can't be read (a text filter other than FlateDecode, or broken) is "We couldn't check this file ..." —
  the person may share it anyway after the human confirm (its content is still scanned), an agent never. **The PDF
  scan is a best-effort text match** on the raw bytes plus the inflated streams. It is strict only about which
  streams it can inflate. The file is read forward from its first byte, so each stream gets the dictionary that
  ends right before its own `stream` keyword. A stream passes only when that dictionary is read exactly and its
  filter list is one of these:
  - empty;
  - exactly `[/FlateDecode]`, and the data inflates fully to the scanned text. A predictor in `/DecodeParms`
    (PNG 10-15 or TIFF 2, as in xref streams and Flate images) is undone first and the result is scanned; no
    `/Type /XRef` or `/Subtype /Image` skips this. A `null` (or `[null]`) `/DecodeParms` or value counts as absent;
    other parameters (a non-integer, `BitsPerComponent` not 1, 2, 4, 8 or 16, a huge `Colors` or `Columns`, data that
    is not a whole number of rows, a PNG row filter past 4) are "We couldn't check this file ...";
  - exactly one picture filter, **DCTDecode or JPXDecode, on an `/Subtype /Image` XObject. Such picture streams
    are accepted unscanned** (the final set; CCITTFax and JBIG2 can carry any bytes and are not in it).

  Anything else is "We couldn't check this file ...". That covers another filter (also `/Filter null`), a chain,
  odd predictor parameters, `/F` or `/DP` keys, a repeated `/Filter` `/DecodeParms` `/F` `/DP` `/Type` or `/Subtype` key,
  nesting deeper than 64, and a file that can't be read forward exactly. It also covers an `N G obj` header inside
  a string, a comment or stream data, and NUL or odd whitespace before `stream`. Junk outside the PDF (before
  `%PDF` or after `%%EOF`) is read forward too, so bytes there that don't read as PDF make the file Unchecked.
  **Not detected:** text that is
  obfuscated in the PDF syntax (hex strings, octal escapes, TJ arrays split by kerning, UTF-16 or CID-font text)
  and anything inside pictures (pixels, JPEG 2000 or lossless JPEG payloads, inline images). Passing the scan
  does not mean the PDF holds no secret.
  **Images are not scanned**: an image is shared only after a person's click.

**Members never get write access to the host ticket.** No message type changes it from outside: a member can only
answer a question the host sent it (relay-checked `reply_to`), report its own task, and talk. Everything it sends is
untrusted data for the host helper (clean_untrusted), never instructions.

## 5. Ordering, delivery, limits, security

- **Ids and dedupe**: message ids as today (`m_` + 16, relay: identical resend = no-op, different = 409; receivers keep
  `.orch/inbox-seen.json`). Group receivers also dedupe on `(host, group.id, origin.id)`. Fan-out ids per §2 (G2).
- **Order**: by `group.seq` only; unsequenced (targeted) messages are ordered by **receive time** (never `created_at`, which is display only). **Stateful checks** (G9
  task status, `closed`, membership) are applied **in `seq` order** (G12):
  - **Initial `applied_seq`** = the **first seen `seq` - 1** (fresh phone, unknown group, new member), so the first
    message applies at once. **Never trust `from_seq` for it**: `from_seq` is display / info only.
  - **Time rule**: never use a peer's `created_at` for ordering, timeouts or rate limits. `created_at` is a claim of
    the sender and display only. Every timer and counter uses the **receiver's own receive time**.
  - A group-wide message **without `seq`** (host) is invalid and **changes no state**.
  - `seq` = applied + 1: apply. Higher: **buffer** (bounded, **50 per group**).
  - **Bounds**: `seq` and `from_seq` are integers in **1..2^31-1**; anything else is invalid and dropped. A forward
    jump **> 1000** over `applied_seq` is a gap skip at once: `applied_seq = seq - 1`, log it, apply the message. A jump
    of exactly 1000 or less is an ordinary gap (buffered). Gaps are tracked as **ranges**, never as one entry per
    missing `seq`.
    - `group.seq` is explicitly **1..2^31-1**; the member → host `body.seen.seq` is **0..2^31-1** (0 = nothing stored yet).
    - "Integer" means a **JSON integer only**: `5.0`, `"5"` and `true` are invalid.
    - After a jump skip, buffered messages **below the new `applied_seq`** become old: shown, no state.
    - **Ports**: compare `seq <= applied_seq` *before* computing `applied_seq + 1`, or use 64-bit integers, so
      `2^31-1 + 1` never overflows. **Seq exhaustion**: at `2^31-1` the host closes the group and opens a new one.
    - Gap ranges are **not modelled by `validate.py`** (it only decides the outcome per message), so range tracking is
      untested here; the jump vectors only prove no per-seq expansion is needed.
  - **Buffer full, or 10 minutes passed since the receiver received the earliest-received message still in the buffer** (receiver clock; the timer is recomputed after a partial flush; quiet groups): **skip the gap**, apply the
    contiguous run, set `applied_seq` to its last `seq`. A `seq` **≤ `applied_seq`** is **old**.
  - **Late texts are shown** (they are real messages) but **change no state** (task status, closed, membership).
  - **Own messages are never waited on** (a member's own text, file, task report or answer takes a `seq`, but the host
    never sends it back): (1) an `own_seq` stub (§2) marks its `seq` as the member's own: the order steps over it,
    nothing is shown. (2) **Last resort, only for a host that has never sent this member a stub** (in any group; kept
    per group and per host), and **only when the 10-minute gap timeout above fires** (never when a message arrives).
    The member keeps the ids of its own group messages the host has not numbered for it yet (at most 20 minutes, at
    most 50). If the missing `seq`s before the oldest buffered one are **no more** than those, and each was sent
    **before** that higher `seq` was received, they are taken as its own (oldest send = lowest `seq`). They are
    remembered as guesses and stepped over without "a message is missing". More missing than that means someone
    else's message is missing, so it is a plain gap skip. A send the host never numbers (a losing answer, a refusal)
    can make the guess wrong. So when a guessed `seq` arrives late from someone else (`origin.from` ≠ the member), it
    is shown as late, and a `closed` or a `member_left` of this member **still applies**. Both are final and come
    from the host; a leave applies only if the member was not added back at a higher `seq`. Tasks, answers and other
    membership news keep no member state beyond the log, so they are shown only. A guessed `seq` that turns out to be
    the member's own changes nothing.
  - **The host MUST persist `seq` monotonically before sending** (write the new value, then send), so a restart never
    reuses or resets numbers. (Chosen over an `(epoch, seq)` pair: one number, no extra field.)
- **Group caps**: a receiver accepts at most **20 open groups per host** and **5 group creations an hour per host, counted by the receiver's receive time** (never `created_at`);
  a creation is **any** first message of a new `(host, id)` (an explicit `created` or a group first seen from its host,
  §2); beyond that it drops and logs, so a paired host cannot create unbounded groups or buffers.
- **Stopped member**: the relay keeps its messages in the inbox (existing); it gets them on its next call. **`body.seen
  = {seq}`** (**NEW**, member → host, quiet, never fanned out, at most once per 10 s per group): the highest group `seq`
  this member has stored, in its own view (from its `from_seq`). The host keeps one value per member. The host shows "Delivered to Finance, Home · waits for Bank" from `seen` and the directory's `online`, chip
  "Bank · not running", and on a task without ack `waiting_start`. Nothing is lost.
- **Leaving**: **`body.leave: true`** (**NEW**, member → host) → host sends `member_left` (`reason: left`).
- **Limits**: members ≤ 8 (host included); group `text` ≤ 4000 characters (Chat keeps 20000); `title` ≤ 120;
  `shared_ticket` ≤ 4096 bytes; files as §4.
- **Per member at the host** (F12): at most 20 messages and 3 files a minute; beyond that the host drops and logs them
  (the member sees "Finance is busy, try again in a minute"). Per group at most 200 MB of shared files and 5000
  messages; after that sharing is refused with a plain line. Messages from non-members, left or removed members, or
  after `closed` are dropped. Pushes follow the existing text push budget and update-kind filter
  (`ack`/`working`/`note` quiet).
- **Security rules** (validate.py `cg_rules`; receivers enforce them and drop + log what breaks them):
  - **G1** a host message's `group.id` = `"grp_" + ticket`; `host` = `from`.
  - **G2** only the host fans out: a member sends group messages **only to the host**; host copies to workspaces use the
    fan-out id; the host sends only to members and phones.
  - **G3** `group_event`, `shared_ticket`, `origin`, `echo_of`, `shared_files` only from the host; `seen`, `leave` only
    from members. A member or phone receiving a group message checks `from == group.host` (**at members and phones, `from ≠ group.host` is always dropped, also for a known group**; and, for a workspace, that the host is
    in its directory / paired). A group first seen from its paired host is **accepted** and created under `(host, id)`
    (§2 wins); a message whose `from` is not `group.host` is a **forged group id** and is dropped.
  - **G4** attribution: a member's message has `by` = the member itself (`agent:<ws name>` in history; `via: dashboard`
    = "From Home's dashboard", still never "you"). Only the host may say `by: you`: for its own dashboard
    (`via: dashboard`, `origin.from: dashboard`) or for a phone text it received from `ph_…` (`via: phone`, `phone`,
    `origin.from` = that phone → history `human:<phone name>`; a `ph_` goes into `origin.from` only for a phone paired
    to that host). **`by: you` received from another workspace is never
    owner authority and never shown as "You" on a workspace**: a member shows it as "<host name> (person)", untrusted
    data. Owner authority on a workspace comes only from its own dashboard or its own `ph_` sender. A phone shows
    `by: you` as "You" only when `from` is the host and `origin.from` is a phone of its account or `dashboard`; any
    other `ph_` shows as "Other phone".
  - **G5** `shared_files` ⊆ `ticket_view.attachments`, only in texts to phones.
  - **G6** `task.ws` = the sending member; only the host says `waiting_start`.
  - **G7** group key `(host, id)` everywhere (storage, dedupe, phone cache; there is no separate id table): the same id under another host is
    a different group and is never dropped for that reason; a repeated `(host, id, origin.id)` is a duplicate.
  - **G8** phone opt-in: only a phone text whose `reply_to` is a group copy is fanned out.
  - **G9** `task.delegate` must be a delegate the host sent to that sender; status only moves forward.
  - **G10** host → member questions are `question_kind: info`; no agent acts on permission answers or commands from
    group content.
  - **G11** a `relay:allow` question (`allow_question: true`) has the wire options `once`, `always`, `no`, mapped per §3.2; UI words are display only.
  - **G12** stateful checks run in `seq` order (§5): gaps buffered (≤ 50, or 10 min), then skipped; late `seq` shown, no state; host persists `seq`.
  - Helpers in a group may answer, share a file they have, and report their task. They **never** approve, sign,
    publish or close another workspace's ticket.

## Vectors (`vectors/chat-groups/`)

Each file: `{why, message, context?, expect?}`. `context` = what the receiver already holds (`known_groups` = [{host, id}]; `seen_origins` = [[host, id, origin.id]]; `order` = {applied_seq (null = fresh), from_seq? (ignored), buffered, now_s, first_buffered_recv_s}; `own_phones`; `receiver_role`; `open_groups_of_host`, `creations_recv_s` + `now_s`;  `paired_phones` (in `host_state`);
`host_state` = members, delegates sent per member, task status per delegate, group copies sent to phones, closed,
last-minute counts). `expect.group_text` = whether a phone text joins the group (G8); `expect.shown_as`, `order`, `applied_after`, `stored_as` + `store`, `card`, `parse`, `map` for G4, G12, G7, G11.

| File | Shows |
|---|---|
| `valid-chat-helper-text` | Chat text with `by`/`via`/`day` |
| `valid-group-created` | host → phones, `created`, `seq` 1, quiet |
| `valid-member-added-from-seq` | `member_added` with `name`, `look`, `from_seq` |
| `valid-delegate-with-group` | existing delegate + `body.group`, no `seq` |
| `valid-member-ack-task` | member status queued → working, delegate checked |
| `valid-fanout-member-text` / `valid-fanout-phones-quiet` | host copies with fan-out ids (workspace and `phones`) |
| `valid-member-answer`, `valid-info-question-to-member` | answers flow back; `question_kind: info` |
| `valid-shared-ticket-to-member`, `valid-file-share-to-member`, `valid-phone-copy-with-file` | ticket card and artifacts |
| `valid-phone-text-optin-reply`, `valid-phone-text-no-optin-stays-private` | G8 (F13) |
| `valid-same-id-other-host-is-a-separate-group`, `invalid-duplicate-origin-same-group-key` | G7: key `(host, id)`; duplicate on `(host, id, origin.id)` |
| `valid-unknown-phone-shown-other-phone`, `valid-own-phone-shown-you`, `invalid-origin-phone-not-paired-to-host` | G4: "You" vs "Other phone"; host-paired `ph_` only |
| `valid-seq-next-in-order-applied`, `valid-seq-gap-buffered`, `valid-seq-buffer-full-skips-gap`, `valid-seq-timeout-skips-gap`, `valid-seq-first-seen-*`, `valid-seq-late-shown-no-state`, `valid-seq-created-at-future-does-not-flush`, `invalid-groupwide-without-seq`, `valid-seq-jump-1000-buffers`, `valid-seq-jump-1001-skips`, `invalid-seq-zero`, `invalid-seq-over-int31`, `valid-seq-equal-applied-is-old` | G12: seq order, bounded buffer, skip, initial applied_seq, late = shown |
| `invalid-nonhost-message-at-member-known-group` | G3 at members and phones |
| `valid-created-under-cap`, `invalid-created-over-group-cap`, `invalid-created-over-rate`, `valid-implicit-group-under-cap`, `invalid-implicit-group-over-cap`, `invalid-implicit-group-over-rate` | group caps |
| `valid-known-group-same-key-appends` | G7 existing group |
| `valid-allow-question-wire-options`, `valid-allow-question-old-wording-answer-in-bank`, `invalid-allow-question-ui-words-on-wire`, `valid-group-approved-always`, `valid-group-approved-once`, `valid-group-denied-from-no`, `invalid-group-approved-mode-permanent` | G11: mapping table |
| `invalid-copy-you-not-from-phone`, `invalid-member-speaks-as-you` | G4 (F2) |
| `invalid-task-foreign-delegate`, `invalid-task-status-goes-back` | G9 (F4) |
| `invalid-group-event-from-member`, `invalid-group-id-not-host-ticket`, `invalid-member-fans-out` | G3, G1, G2 |
| `invalid-question-without-kind` | G10 (F9) |
| `invalid-targeted-with-seq` | seq rules (F10) |
| `valid-own-seq-stub-to-sender`, `invalid-own-seq-to-other-member`, `invalid-member-sends-own-seq` | `own_seq` stub: only host → the origin's own workspace (§2) |
| `invalid-left-member-text`, `invalid-too-many-members` | F12, limits |
| `invalid-phones-copy-loud` | push set |

Run: `uv run --with jsonschema --with rfc3339-validator --with cryptography python contracts/validate.py`.
