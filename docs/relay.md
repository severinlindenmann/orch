# orch-relay

## What it does
Workspaces and phones send each other messages on `relay.severin.io`, under pair rules set by the admin.
Delegate/start need an allow on the receiving side. Webhooks become inbox messages.
The admin hands out shared skills, MCP servers and credentials per workspace, and can read all messages.
Each workspace has a description and tags; refresh gives every workspace a directory (`workspaces.json`) of who it can work with.

## Tech stack
Rust: `axum`, `tokio`, `rusqlite` (bundled), `serde`/`serde_json`, `aes-gcm` (at rest), `sha2`, `rand`, `base64`,
`tar` + `flate2`, `a2` (APNs push), `qrcode` (phone link), `tower-http`, `tracing`. Portal: plain HTML/CSS/JS embedded. Caddy in front.

## Folder layout
```
relay/
  Cargo.toml  src/{main.rs, api.rs, phone.rs, admin.rs, rules.rs, store.rs, crypto.rs, webhooks.rs, shared.rs, push.rs}
  web/{portal.html, style.css}
  onboarding/{onboarding.sh, onboarding.ps1}   (the orch-relay skill lives in workspace/skills/;
  its SKILL.md says: read inbox at session start; before handing work over, read workspaces.json next to it)
  deploy/{Caddyfile, orch-relay.service, install.sh}
  tests/
```

## Endpoints
`contracts/relay-api.md`. Messages: `contracts/message.schema.json`. Keys: `contracts/crypto.md`.

## Voice transcription
The admin stores one Deepgram API key (portal: Shared config > Voice; `PUT /admin/api/voice`). It is sealed with the master key and never returned in full
(only "set" and the last 4 characters) or sent to phones and workspaces. `POST /v1/phone/transcribe` (phone token) and `POST /v1/transcribe` (workspace token)
take audio bytes (m4a, wav, webm; 10 MB / 2 min), call Deepgram (`nova-3`, smart format, language detected unless `?language=`) and return `{text, language, duration}`.
No key = `503 transcription_off`. 30 calls a minute per phone or workspace (in memory). The Deepgram call sits behind the `Transcriber` trait; tests use a fake.

## How a message flows
Sender `POST /v1/messages` → relay checks the schema and the pair rule → stores (body encrypted with the master key)
→ receiver gets it on the next `GET /v1/inbox` and acks → receiver stores the id as seen. Offline = it waits on the relay.
Questions to `phones` also trigger an APNs push.

## Data storage
- SQLite `/var/lib/orch-relay/relay.db`: workspaces (name, description, tags, last_seen), phones, rules, messages (envelope plain, body encrypted), acks,
  webhooks, shared items (encrypted), assignments, `version`, settings (the Deepgram key, encrypted).
- Blobs: `/var/lib/orch-relay/blobs/<id>` (encrypted). Messages and blobs are kept 90 days.
- Secrets: `/etc/orch-relay/master.key`, `/etc/orch-relay/admin-token`, APNs key `/etc/orch-relay/apns.p8` (only on the VPS).

## Tests
- T0: `cargo test --test messages -- rule` (one test file per area: messages, inbox, allow, webhooks, shared, phone, admin).
- In-process server + temp dir; APNs behind a trait with a fake. Every `contracts/examples/message/*` is accepted/refused as expected.
- CI: `relay/**`, `contracts/**`; `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test`.

## Deploy
`relay-deploy.yml` on push to `main`: build, copy over SSH, `systemctl restart orch-relay`, check `/health`.
First install: `deploy/install.sh` (user, folders, master key, admin token, Caddy route). Same VPS as publish.

## Not included
End-to-end encryption between workspaces, key rotation, groups/teams, several admins, message edit/delete by users,
read receipts, a web client for messages.

## Workspace profile and the portal (UX round 1)

- A workspace can change its own description and tags with `PATCH /v1/me` (see contracts/relay-api.md); the admin "add workspace" prompt ends with a line asking the agent to run `orch relay profile --description "..." --tags a,b`.
- The admin list shows `last_seen`; the portal says "Online" (called in the last 2 minutes) or "Last seen 5 min ago".
- Dark only. Unknown public paths and `/` show a branded "This page isn't available" page.
