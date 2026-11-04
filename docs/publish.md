# orch-publish

## What it does
Public links on `publish.severin.io`: files at `/f/<id>` (end-to-end encrypted, the browser decrypts) and small apps at
`/a/<name>` (private with a token by default, or public). Temporary (default 7 days, max 90) or permanent.
One admin manages workspaces in a localhost-only portal.

## Tech stack
Rust: `axum`, `tokio`, `rusqlite` (bundled), `serde`/`serde_json`, `toml`, `sha2`, `rand`, `base64`, `tar` + `flate2`,
`tower-http`, `tracing`. Portal and file page: plain HTML/CSS/JS embedded with `include_str!` (orch style tokens), WebCrypto.
Apps: systemd `orch-app@<name>.service` units (from orch core). Caddy in front.

## Folder layout
```
publish/
  Cargo.toml  src/{main.rs, api.rs, admin.rs, files.rs, apps.rs, sweep.rs, db.rs}
  web/{portal.html, file.html, file.js, private.html, style.css}
  onboarding/{onboarding.sh, onboarding.ps1}   (the orch-publish skill lives in workspace/skills/)
  templates/{static, python, node}   (from orch core publish templates)
  deploy/{Caddyfile, orch-publish.service, orch-app@.service, install.sh}
  tests/
```

## Endpoints
`contracts/publish-api.md`. Blob format: `contracts/crypto.md`. App manifest: `contracts/app.toml.md`.

## Data storage
- SQLite `/var/lib/orch-publish/publish.db`: workspaces (name, description, tags, token hash, rights), files (id, workspace, size, expiry), apps.
- Blobs: `/var/lib/orch-publish/files/<id>` (ciphertext only).
- Apps: `/srv/orch-publish/apps/<name>/` (code), `/var/lib/orch-publish/apps/<name>/data` (DATA_DIR).
- Sweep every hour: deletes expired files and stops + removes expired apps. Env: `PUBLISH_MAX_FILE_MB` (100), `PUBLISH_DEFAULT_DAYS` (7), `PUBLISH_MAX_DAYS` (90).

## Tests
- T0: `cargo test --test files -- upload` (one test file per area: files, apps, admin, auth).
- In-process tests with a temp dir and a fake app runner (no systemd). The JS decrypt is tested with `node --test web/file.test.js`
  against `contracts/vectors/publish-blob-v1.json`. Real systemd only in e2e on the VPS.
- CI: `publish/**`, `contracts/**`; `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test`, `node --test`.

## Deploy
`publish-deploy.yml` on push to `main`: build for linux x86_64, copy binary + web + scripts to the VPS over SSH,
`systemctl restart orch-publish`, check `/health`. First install: `deploy/install.sh` (user, folders, admin token, Caddy route).

## Not included
Several admins, custom domains per app, app logs view, file previews, own databases beyond SQLite, Docker.

## Workspace profile

A workspace proposes its own description and tags with `PATCH /v1/me` (see contracts/publish-api.md); the owner approves or rejects the change in the admin portal (overview banner, "Needs your review" badge, a card with current vs proposed text), and the old values stay in effect until then. Approve/reject are bound to the exact proposal (`rev`); a new access key drops a pending change. Same text rules as the relay. The admin "connect your agent" text ends with a line asking the agent to do this.
