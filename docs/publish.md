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
  web/{portal.html, file.html, file.js, frame.html, frame.js, private.html, style.css, favicon.svg, apple-touch-icon.png}
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
- Previews in a real browser (local, not in CI): `node e2e/walkthrough/publish-previews.mjs [out dir]` builds and starts
  the server on 127.0.0.1, shares one file of each kind (html, folder, png, pdf, md, py, csv, docx), checks the
  preview and the sandbox, and saves a screenshot of each.
- In-process tests with a temp dir and a fake app runner (no systemd). The JS decrypt is tested with `node --test web/file.test.js`
  against `contracts/vectors/publish-blob-v1.json`. Real systemd only in e2e on the VPS.
- CI: `publish/**`, `contracts/**`; `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test`, `node --test`.

## Deploy
`publish-deploy.yml` on push to `main`: build for linux x86_64, copy binary + web + scripts to the VPS over SSH,
`systemctl restart orch-publish`, check `/health`. First install: `deploy/install.sh` (user, folders, admin token, Caddy route).

## Not included
Several admins, custom domains per app, app logs view, own databases beyond SQLite, Docker.

## Workspace profile

A workspace proposes its own description and tags with `PATCH /v1/me` (see contracts/publish-api.md); the owner approves it or keeps the current text (Approve / Keep current) in the admin portal (overview banner, "Waiting for your approval" badge, a card with current vs proposed text), and the old values stay in effect until then. Approve / Keep current are bound to the exact proposal (`rev`); a new access key drops a pending change. Same text rules as the relay. The admin "connect your agent" text ends with a line asking the agent to do this.

## Keeping, replacing and noting a file

- `orch publish extend f_… --days N` keeps a file longer (`PATCH /v1/files/<id>`); the link stays the same and an expired file is never revived.
- `orch publish file <path> --replace f_…` swaps the content behind the same link (`PUT /v1/files/<id>`). It reuses the key saved in `.orch/secrets/files/keys.json`, so it only works on the computer that shared the file; the expiry stays.
- `orch publish file <path> --note "…"` adds a one-line note (up to 280 characters) to the **encrypted** header (`crypto.md`, vector `good_with_note`). The server never sees it; the browser shows it as text.
- `orch publish list` follows the server's paging, so it shows every file, not only the first 100.
- `orch publish view --json` is the read-only "Shared" tab of the dashboard: files and apps with name and expiry, links **without** a key, and a hint to use the CLI for copy, extend and delete.

## Previews

After the browser decrypts a file, `/f/<id>` shows it by type (by file name ending, not by the type the sender
wrote in the header). The document is the focus: one slim header line (logo, file name, "size · until Thu 19 Nov" as a
date in the viewer's own time zone, Download, Copy link, full screen), the sender's optional note on one small line
(from the encrypted header, shown as text, click to read all of a long one; no sender or workspace name), the viewer
filling the rest of the window height (full screen with the button or the F key, Esc leaves), and a tiny footer
("Only people with this link can open the file." plus pages, pixels or lines). Publish's own blue accent, dark, system
font. The expiry comes from the `X-Orch-Expires-At` header of `/f/<id>/blob`. No inline styles or scripts (CSP).

| Files | Preview |
|---|---|
| png, jpg, jpeg, gif, webp, avif, bmp, ico | image (`<img>`, blob URL), size in pixels, full screen |
| svg | image, only as `<img>` (scripts in the SVG never run) |
| pdf | the browser's own PDF viewer in a frame (blob URL), page count, full screen |
| mp4, webm, mov, m4v / mp3, m4a, wav, ogg, oga, flac, aac, opus | native video / audio player, length |
| md, markdown | rendered (headings, lists, task lists, quotes, code, tables, links); raw HTML is shown as text; only http(s) and mailto links; https images are shown (no referrer), other images become their alt text |
| txt, log, py, js, ts, tsx, jsx, json (pretty-printed), yaml, toml, sh, swift, rs, go, sql, css, xml, ini, .env files, Dockerfile, Makefile, c, java, kt, rb, php, lua, … | monospace with line numbers and light highlighting (own ~40-line highlighter, no library); first 1 MB |
| csv, tsv | table, first 500 rows, column count |
| html, htm | rendered in a sandboxed frame ("Runs in a safe frame"), full screen |
| folder (`orch publish file <folder>` with at least one .html page) | the same frame, opening `index.html` or else the first page by name; with several pages a page switcher; paths resolve like on a web server rooted at the folder (subfolders, `../`, css `url()`, img/script src, `fetch()`, links between pages); CDN scripts, Google Fonts and https APIs work; "Website · N files"; Download gives a .zip |
| everything else (Word, Excel, PowerPoint, zip and other archives, programs) | card with the file name, kind and size, "No preview … yet", Download file |

Folder format: `contracts/crypto.md` "Folder bundle" (vector `contracts/vectors/publish-bundle-v1.json`). The CLI
leaves out dot files and folders (`.env`, `.git`), `node_modules`, `__pycache__`, symlinks and secret-looking files
(`*.pem`, `*.key`, `*.p8`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`, `credentials*.json`, `secrets.*`, ...), refuses
names the viewer can't read (`\`, over 255 characters, not valid text), and prints the shared and left-out file names.

How HTML stays safe (for security review):
- The file page itself keeps a strict CSP: `script-src 'self'` (no inline, no eval), `img-src 'self' data: blob: https:` (https for images in markdown),
  `media-src blob:`, `frame-src 'self' blob:`, `object-src 'none'`, `base-uri 'none'`, `form-action 'none'`,
  `frame-ancestors 'none'`. All markdown, code and table output is built from escaped text; no file byte becomes markup.
- HTML runs only in `<iframe sandbox="allow-scripts" src="/_/frame.html">`: no `allow-same-origin` (opaque origin:
  it cannot read the file page, its `#k=` key, cookies, storage or other files), no top navigation, no popups, no forms.
  The key is never sent to the frame; the frame gets only the decrypted files by `postMessage` after it says ready,
  and it accepts one message, only from its parent.
- `/_/frame.html` has its own CSP: `default-src 'none'; script-src 'self' 'unsafe-inline' 'unsafe-eval' blob: https:;
  style-src 'unsafe-inline' blob: https:; img-src blob: data: https:; font-src blob: data: https:; media-src blob: data:;
  connect-src blob: data: https:; form-action 'none'; base-uri 'self'; frame-ancestors 'self'; sandbox allow-scripts`
  (the `sandbox` directive keeps the opaque origin even if some page frames or opens it without the attribute). Inline scripts and eval are allowed there
  because shared pages need them; https: lets pages that load a CDN script, style or font work (the page can then
  reach the internet, like any web page the user opens, but it holds nothing but its own content).
- Inside the frame, `frame.js` writes the page with `document.write` and serves the folder's files: relative `src`,
  `href`, CSS `url()` and `@import` become blob: URLs, and `fetch()` / `XMLHttpRequest` of a relative path answer
  from the folder. Not supported: ES module imports between files (`import "./x.js"`), service workers.
- The PDF frame is not sandboxed (Chrome's viewer refuses sandboxed frames). It is shown only when the bytes start
  with `%PDF-` (else the download card), and its blob is always typed `application/pdf` by the page, never by the
  sender, so it cannot become an HTML document. Same for images and media.

## Icons

Every orch web page has a favicon from one family (`brand/favicon-<surface>.svg` and a 180 px
`brand/apple-touch-icon-<surface>.png`): the orch orbit on a dark tile, tinted per surface so tabs are easy to tell
apart: workspace dashboard green `#2fc6a3`, publish blue `#60a5fa`, relay violet `#a78bfa`. Publish serves its copy at
`/_/favicon.svg` and `/_/apple-touch-icon.png` (public and admin), and the publish logo and admin accents use the blue.
Make the PNGs with `node e2e/walkthrough/favicon-png.mjs brand/favicon-<surface>.svg brand/apple-touch-icon-<surface>.png`.
