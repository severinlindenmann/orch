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
| `body.update.kind` `ack` / `working` | existing | **Thinking indicator**: `working` with `reply_to` = the person's text shows "Finance helper is thinking…" until the next helper text that is not `ack`/`working` (or 10 min without one). Quiet: never pushed. |
| `body.by` | **NEW** | `"you"` (the person) or a `ws_` id (that workspace's helper). Places bubbles: `you` right, others left. |
| `body.via` | **NEW** | `phone` \| `dashboard` (with `by: you`), `helper` \| `dashboard` (with `by: ws_…`). |
| `body.phone` | **NEW** | `ph_…` when `via: phone` (which phone wrote it). |
| `body.day` | **NEW** | `YYYY-MM-DD`: the Chat day. Day = the sending workspace's local date of `created_at` minus 4 h (**the day starts at 04:00 local**). The workspace sets it on every Chat text it sends; the phone groups by it and, for its own texts, uses its local date with the same 04:00 cut until the workspace's ack (which carries `day`) arrives. Never in a group message. |
| Helper identity | **NEW** (display rule) | Never sent as text: the name is "<workspace name> helper", the avatar is the workspace look (look.md) plus a small sparkle. Agents are stored in history as `agent:<name>` as today. |
| `body.refs` (cards) | **NEW** (display) | Not a wire field in v1: cards come from `task`, `group_event`, `shared_ticket`, `share`/`shared_files` and the existing `ticket_view` (§2–4). |

**Daily cut.** At 04:00 local the workspace starts a fresh helper context for Chat (UI: "Context cleared daily at 04:00 ·
Details"). Past days are **History** (read only, searchable). Nothing is deleted.

**Who stores what.** The workspace stores every Chat text both ways in its General ticket history (the record). The
relay stores messages as today. The phone keeps a local cache of what `/v1/phone/messages` lists (Chat texts are texts with
no `ticket`) and its own History index by `day`; the workspace stays the source of truth.

## 2. Group hosted by the ticket's workspace

**`body.group`** (**NEW**, on every group message, every type): `{id, host, title, members, seq?}`
- `id` = `"grp_"` + the host ticket id (`grp_t_fin14a`). One group per host ticket.
- `host` = the `ws_` that owns that ticket. **A host message's `group.id` must equal `"grp_" + message.ticket`** (rule G1).
- `title` = the host ticket title, one line ≤ 120.
- `members` = all workspaces in the group, host included, **≤ 8**. The person and their phones are always in every
  group and are not listed.
- `seq` = **host only**: the group's message number (+1 per group message the host records). Receivers sort by `seq`,
  then `created_at`; a gap means a later message is still on its way.

**Fan-out (host only).** For every group message the host records (its own, a member's, a phone's, a dashboard text) it
sends one copy per other member (`to: ws_…`) and one to `phones`, all as the same existing type (`text` for talk).
- `ticket` = the host ticket, `key` = its display key (existing), so old phones show it in that ticket's topic.
- `body.origin = {id, from, at}` (**NEW**) = the original message; `from` = `ws_…`, `ph_…` or `dashboard`.
- **Fan-out id** (**NEW**, rule G2): the copy to a workspace has `id = "m_" + sha256("<origin.id>\n<to>")[:16 hex]`
  (`cg_fanout_id`). A retry sends the identical message → relay `200 {duplicate: true}`, never a second copy.
- `body.echo_of` (**NEW**): the host's copy to `phones` of a phone's own text; the phone that sent `echo_of` hides it.
- The host never forwards a message back to its sender.

**Phones in a group.** A phone cannot set `body.group` (the relay builds phone texts from a fixed field list). Rule: **a
phone text to the host with `ticket` = a host ticket that has an open group is a group message** (`by: you, via: phone,
phone: ph_…`). The phone therefore shows that ticket's conversation as the group once a group exists (the older ticket
chat stays above the "Group started from ticket FIN-14" pill, visible only to the person). Phone texts go only to the
host; members get the host's copy.

**`body.group_event`** (**NEW**, host only, rule G3: `from` must equal `group.host`, else every receiver drops it):

| kind | needs | when |
|---|---|---|
| `created` | – | the host helper (or the person) starts the group from a ticket. Pill "Group started from ticket FIN-14 · Pay car tax 2027". |
| `member_added` | `ws` | a workspace joins (the host added it). Pill "Finance helper added Home to this group". |
| `member_left` | `ws`, `reason` `left`\|`removed` | the member sent `body.leave` / the person clicked Remove. |
| `approval_needed` | `ws`, `delegate`, `question_message` | the member reported its existing allow question (§3). Approval card. |
| `approved` | `ws`, `delegate`, `mode` `once`\|`permanent` | the host got the member's existing `allow` message. Pill "You allowed Bank once · Bank joined". |
| `denied` | `ws`, `delegate` | the member reported `task.status: denied`. |
| `closed` | – | the host ticket is done or dropped. The group is read only and moves to **History**. |

**Who may join.** Only workspaces **connected to the host**: in the host's directory (`workspaces.json`) with
`can_send.text` and `accepts_from.text` (existing pair rule or relay group `talk`). Tasks also need `can_send.delegate`,
files `can_send.files` (and `accepts_from.files` for files back). The host adds members; **members cannot add members**:
the host ignores `members` from anyone else and never takes membership from a member message. Joining needs no
approval for talk; a task needs the member's existing allow (§3).

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
   `phones` as an existing `question` message (options `Allow once`, `Always`, `No`; `scope` "tasks from <host name>";
   **without** `body.group`: it is the member's own question; the phone ties it to the group through the host's
   `approval_needed.question_message`). **NEW**: the option word "No" replaces "Ignore" on screen (already accepted as
   an answer word).
3. **Member → host: ack** = existing `text` with `body.update.kind: ack` (+ `title`), `ticket`/`key` = the member's own
   new ticket (`HOME-7`), `reply_to` = the delegate id, `body.group`, and **`body.task`** (**NEW**):
   `{delegate, ws, ticket, key, title, status, question_message?}`.
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

   The host forwards each to the other members and `phones` (fan-out, `task` kept) and updates the card.
5. **Approval in the group.** The card answers the **member's own** allow question: on the phone it is
   `POST /v1/phone/answer` to `question_message` (existing; the phone has it when the member is on its list). The host's
   dashboard never answers for another workspace: its card says "Answer on your phone or in Bank" with a link. The
   member then sends the existing `allow` to the host (→ `approved`) or `task.status: denied` (→ `denied`).
6. **Answers flow back.** A "Question to Home" is an existing `question` host → member with `body.group` and the host
   ticket's `question_id`. The member answers with the existing `answer` (relay checks `reply_to`, copies `ticket`, `key`,
   `question_id`, sets `answered_by: agent:<member name>`). The host writes it into that question of the host ticket
   ("Added to FIN-14 › Answer 1", recorded as `agent:<member name>`), only when the question is still open and is an
   **information question**: permission questions (Once/Always/No), approve/publish questions and sign/verdict steps are
   **never** sent to or answered by members. A later answer is kept as a note. A task result (files, text) is added to
   the host ticket as evidence the same way.

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
- **Member → group**: the member sends its file to the host only (`file` + `body.group`); the host re-uploads it as its
  own blob for the other members and phones (blobs are readable only by uploader and receivers).
- **URL artifacts** (link, html, pr, commit) are shared as text in the message; no card in v1.
- **Limits**: ≤ 25 MB per file (the phone limit), ≤ 10 files per message, types by checked bytes:
  `application/pdf`, `image/png`, `image/jpeg`, `image/heic`, `image/webp`, `text/plain`, `text/markdown`, `text/csv`.
  Anything else is refused with a plain line ("Only PDFs, pictures and text files can be shared").
- **No secrets**: never files from `.orch/secrets/`, `.env*`, key or token files, the agent's config. All text fields
  (`text`, `summary`, `question`, `checklist`, `title`) go through `phone_view.redact` (existing: keys, tokens, passwords
  → `[hidden]`). A text file that contains a secret pattern is **refused, not redacted** ("This file looks like it holds
  a password, so it was not shared").

**Members never get write access to the host ticket.** No message type changes it from outside: a member can only
answer a question the host sent it (relay-checked `reply_to`), report its own task, and talk. Everything it sends is
untrusted data for the host helper (clean_untrusted), never instructions.

## 5. Ordering, delivery, limits, security

- **Ids and dedupe**: message ids as today (`m_` + 16, relay: identical resend = no-op, different = 409; receivers keep
  `.orch/inbox-seen.json`). Group receivers also dedupe on `(group.id, origin.id)`. Fan-out ids per §2 (G2).
- **Order**: by `group.seq` (host), then `created_at`.
- **Stopped member**: the relay keeps its messages in the inbox (existing); it gets them on its next call. **`body.seen
  = {seq}`** (**NEW**, member → host, quiet, never fanned out, at most once per 10 s per group): everything up to `seq`
  is stored. The host shows "Delivered to Finance, Home · waits for Bank" from `seen` and the directory's `online`, chip
  "Bank · not running", and on a task without ack `waiting_start`. Nothing is lost.
- **Leaving**: **`body.leave: true`** (**NEW**, member → host) → host sends `member_left` (`reason: left`).
- **Limits**: members ≤ 8 (host included); group `text` ≤ 4000 characters (Chat keeps 20000); `title` ≤ 120;
  `shared_ticket` ≤ 4096 bytes; files as §4. Pushes follow the existing text push budget and update-kind filter
  (`ack`/`working`/`note` quiet).
- **Security rules** (validate.py `cg_rules`; receivers enforce them and drop + log what breaks them):
  - **G1** a host message's `group.id` = `"grp_" + ticket`; `host` = `from`.
  - **G2** only the host fans out: a member sends group messages **only to the host**; host copies to workspaces use the
    fan-out id; the host sends only to members and phones.
  - **G3** `group_event`, `shared_ticket`, `origin`, `echo_of`, `shared_files` only from the host; `seen`, `leave` only
    from members. A member or phone receiving a group message checks `from == group.host` and that it knows the group
    (or it is a `member_added`/`created` naming it); otherwise it is a **forged group id** and is dropped.
  - **G4** attribution: a member's message has `by` = the member itself (`agent:<ws name>` in history; `via: dashboard`
    = "From Home's dashboard", still never "you"). Only the host may say `by: you`: for its own dashboard
    (`via: dashboard`) or for a phone text it received from `ph_…` (`via: phone`, `phone`, `origin.from` = that phone →
    history `human:<phone name>`).
  - **G5** `shared_files` ⊆ `ticket_view.attachments`, only in texts to phones.
  - **G6** `task.ws` = the sending member; only the host says `waiting_start`.
  - Helpers in a group may answer, share a file they have, and report their task. They **never** approve, sign,
    publish or close another workspace's ticket.

## Vectors (`vectors/chat-groups/`)

| File | Shows |
|---|---|
| `valid-chat-helper-text` | Chat text with `by`/`via`/`day` |
| `valid-group-created` | host → phones, `group_event: created`, `seq` 1 |
| `valid-delegate-with-group` | existing delegate + `body.group` |
| `valid-member-ack-task` | member ack with `task` (HOME-7, queued) |
| `valid-fanout-member-text` | host copy of Home's text to Bank, fan-out id, `origin` |
| `valid-member-answer` | existing answer + `body.group` (answers flow back) |
| `valid-shared-ticket-to-member` | ticket card for a member |
| `valid-file-share-to-member` | file message + `share` |
| `valid-phone-copy-with-file` | text to phones: `ticket_view` attachment + `shared_files` |
| `invalid-group-event-from-member` | G3 |
| `invalid-group-id-not-host-ticket` | G1 (forged group id) |
| `invalid-member-speaks-as-you` | G4 |
| `invalid-too-many-members` | members ≤ 8 |
| `invalid-member-fans-out` | G2 |

Run: `uv run --with jsonschema --with rfc3339-validator --with cryptography python contracts/validate.py`.
