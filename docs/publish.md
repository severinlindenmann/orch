# Publish: share a file or a small app

Publish is a small server (yours). It is optional and works on its own, without the relay. A file is encrypted on your computer
before it leaves. The key is part of the link (after the `#`), so the server never has it. Share the whole link; keep it private.

## Connect a workspace

Your admin clicks **Add workspace** on the publish page and gets a short text for your agent. It runs:

```sh
$ orch addon add publish --yes
$ orch publish connect <publish address> --workspace <workspace id> --token <token>  # skip
```

## Share

```sh
$ orch publish whoami  # server
$ orch publish file report.csv --days 7  # server
$ orch publish list  # server
```

The link lasts 7 days unless you say `--days N` (up to 90) or `--permanent`. Put the link on the ticket so people find it:
`orch ref add <id> "<link>" --title "<what it is>"`. A folder with an `index.html` opens as a website.

## Keep a link, change what is behind it

```sh
$ orch publish file report.csv --days 7 --note "Draft, numbers for March"  # server
$ orch publish list  # server
$ orch publish view --json  # server
```

- **Extend:** `orch publish extend <file id> --days 30` keeps the file longer under the same link. It is never shorter than now,
  and a permanent file stays permanent.
- **Replace:** `orch publish file report.csv --replace <file id>` puts new content under the same link and the same end date.
- **Note:** `--note "..."` (up to 280 characters) is shown to the person who opens the link.
- **Shared tab:** `orch publish view --json` is what the dashboard shows under Shared: your files and apps, no keys.

Redeploying an app (`orch publish app <folder>`) keeps its address and private view link; the old version keeps running if the
new one fails its test.

**Apps run sandboxed.** Every page an app serves is sandboxed by the server (`Content-Security-Policy: sandbox ...`), so
that one app can never read another app's pages. Scripts, forms, popups and downloads work. But the page has no origin of its
own: `localStorage`, `sessionStorage`, IndexedDB and cookies throw or stay empty. Keep state on the app's backend and
identify people by a link token or a typed name. `fetch()` to the app's own paths works: the server answers the cross-origin
check for public apps, and for private apps only under their own private address. A private app is served under a secret
`/a/<name>/~<key>/` address (the server redirects there after the view link or cookie check). That private link, and the address
it opens, is the key to the app, as before; both change when the link is reset. The server keeps its key for these addresses in `app-cap.key` in the data folder; it must stay private to the publish user. Use relative links (`style.css`, `data.json`),
not root-absolute ones (`/a/<name>/style.css`), or they get no access. An app cannot switch the sandbox off.

---

# Reference

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

## Private-network listener (app reach)
An app with `reach = "private"` in `app.toml` is served only on a third listener, on the private network. Two settings, both
or neither (one alone stops the server at start with a one-sentence message):
- `ORCH_PUBLISH_PRIVATE_LISTEN`: address to bind, e.g. `<private-network IP>:80`.
- `ORCH_PUBLISH_PRIVATE_URL`: the address people use, e.g. `http://publish-vps.office.internal` (the auth cookie gets
  `Secure` only when this URL is `https`).

Without them the server refuses `reach = "private"` (`422 invalid`). The listener serves only `/a/<name>/...` of private-reach
apps, `/_/` page assets and `/health`; everything else, and public-reach apps, answer `404`. On the public address a
private-reach app answers exactly like an app that does not exist. Sleeping apps wake on either listener.

The listen address must be an IP address and port on the private network (100.64.0.0/10, 10/8, 172.16/12, 192.168/16,
fd00::/8, or loopback for local runs); `0.0.0.0`, `::` and public IPs stop the server at start, and so does a
`ORCH_PUBLISH_PRIVATE_URL` equal to the public URL. The listener answers `404` unless the request's `Host` is the host (and port,
default from the URL scheme) of `ORCH_PUBLISH_PRIVATE_URL` (DNS rebinding guard; `/health` is exempt). If the listener cannot
bind, the server logs one error and keeps serving the public and admin listeners; private-reach apps stay hidden.
An app that moves between reaches on redeploy gets a new private link. Open apps (`auth = false`) on the private network are also served under a secret `/a/<name>/~<key>/` address, so that a page from elsewhere cannot read them cross-origin; their pages must use relative links.

Host setup on the VPS (Linux only):
1. Check port 80 is free on the private IP: `ss -ltnp 'sport = :80'`.
2. Bind the private-network IP on port 80. Port 80 is below 1024, so give the service the right to bind it, with a systemd
   drop-in `/etc/systemd/system/orch-publish.service.d/private-listen.conf`:
   ```
   [Service]
   Environment=ORCH_PUBLISH_PRIVATE_LISTEN=<private-network IP>:80
   Environment=ORCH_PUBLISH_PRIVATE_URL=http://publish-vps.office.internal
   AmbientCapabilities=CAP_NET_BIND_SERVICE
   ```
   then `systemctl daemon-reload && systemctl restart orch-publish`. In the plain sandbox mode (`ORCH_PUBLISH_SANDBOX`
   unset) app processes inherit `CAP_NET_BIND_SERVICE`; container mode and `systemd` mode do not.
3. Firewall: a host may already allow port 80 from anywhere, so deny it on the public side first, and allow it in on the
   private-network interface:
   `sudo ufw insert 1 deny in on <public interface> to any port 80 proto tcp` (adjust if the host serves something
   public on 80), then `sudo ufw allow in on <private-network interface> to any port 80 proto tcp`.
   If the host has no general deny-from-app-subnet rule, also keep app containers out:
   `sudo ufw insert 1 deny in from <app subnets> to any port 80 proto tcp`.
   Check the order with `sudo ufw status numbered`. Do not add a public proxy route for the listener.

## Sandbox (`ORCH_PUBLISH_SANDBOX`)
- unset: plain child process (development and tests). `systemd`: one transient unit per app (static, python, node).
- `container`: one container per app on the Kiri engine, driven with the `docker` CLI against
  `ORCH_PUBLISH_ENGINE_SOCKET` (default `/run/kiri/docker.sock`; CLI path `ORCH_PUBLISH_DOCKER`, default `docker`).
  Per app: its own network (`orch-net-…`, one /28 from 10.213.0.0/16, never removed), port published on 127.0.0.1 only, 128 MB, 0.5 CPU, 64 processes, read-only root,
  `/tmp` tmpfs, no capabilities, `no-new-privileges`, uid 61000 with the server's group (data and code folders are group-writable, mode 2770), code at `/app` (read-only), data at `/data`.
  Images `python:3.12-slim` / `node:22-slim`; build steps (venv + pip, `npm ci --omit=dev`) and test steps run in the
  same image (512 MB). Stack `docker` (needs `ORCH_PUBLISH_SANDBOX=container` AND `ORCH_PUBLISH_DOCKER_APPS=1`, off by default because image builds run in a privileged builder; otherwise "This server doesn't run apps with their own Dockerfile."): the bundle has
  a `Dockerfile`; the host builds `orch-app-<instance>-<name>:<version>-<random>`, runs it, and removes the old image after the switch.
  The Dockerfile may not use `--mount`, `--network`, `--security`, `--device` or parser directives; a built image with `dev.kiri.*` / `orch.*` labels or a `VOLUME` is refused. One image build runs at a time.
  Containers carry the labels `orch.publish.app` and `orch.publish.instance` (a hash of the data folder, so a second server on the same engine never touches them). At server start, before the listeners bind, leftover step containers and containers of unknown apps of this instance are removed.
  Real-engine test: `ORCH_PUBLISH_TEST_ENGINE=1 cargo test --test container -- --ignored`.
  Scale to zero: `ORCH_PUBLISH_IDLE_SECS` (default 900 in container mode, 0 = never; other modes never sleep) stops a python/node/docker
  app that got no request for that long (the sweeper looks every `ORCH_PUBLISH_SLEEP_SWEEP_SECS`, default 30). The next request starts it
  again (one start per app, other requests wait for it; health is polled every 25 ms) and is answered when the app is healthy; if it cannot
  start, the visitor gets a 503 page and the log tail goes to the server log. Measured on the edge machine (Kiri 0.2.0): cold start of a
  small python app to first 200 = 150-230 ms; an idle app uses about 15 MB. A sleeping app keeps `status: running` and shows `awake: false`
  (the admin portal says "Sleeping"). Requests still open (SSE, long polls) keep an app awake. After a server restart, apps are not started:
  they wake on their first request. Apps must keep state in `DATA_DIR`; timers and background work stop while the app sleeps.
  After a wake the first requests arrive together: use a normal listen backlog (Python's `http.server` default of 5 is small; the templates' `ThreadingHTTPServer` is fine, or set `request_queue_size`). Requests are proxied as plain HTTP: WebSocket upgrades are not forwarded, so they do not work through `/a/<name>/` and do not keep an app awake (SSE and long polls do). At most 4 apps start at the same time. A failed wake is not retried for 30 s (visitors get the 503 page at once); a restart clears that.

## Container mode: host setup

Run these on the server that runs orch-publish. Apps get the internet; they cannot reach the server itself, the
private network (VPN), the local network or the cloud metadata address.

1. Install Kiri: download the `kiri` .deb and its `SHA256SUMS` from the Kiri release page, check
   `sha256sum -c SHA256SUMS --ignore-missing`, then `sudo apt install ./kiri_*.deb`.
2. Give the publish user access to the engine: `sudo kiri host-access <publish user>`. Caution: this is
   root-equivalent for that user (whoever controls the engine socket controls the machine). Only the publish user
   gets it; see the security note of the deploy.
3. Find the public network interface: `ip route show default` (the name after `dev`, used as `<public interface>`).
4. If the host uses ufw, add these rules in this order (apps live in 10.213.0.0/16, one /28 per app; change the pool
   with `ORCH_PUBLISH_APP_SUBNETS`). `<kiri0 gateway>` is the address of `kiri0` (`ip -4 addr show kiri0`). Kiri's
   image mirror port changes between runs, so the rule allows that one address, not a port:

```
sudo ufw allow in on kiri0 to <kiri0 gateway> proto tcp   # Kiri's builder reaches Kiri's image mirror only
sudo ufw route deny in on kiri0 to 169.254.0.0/16
sudo ufw route deny in on kiri0 to 10.0.0.0/8
sudo ufw route deny in on kiri0 to 172.16.0.0/12
sudo ufw route deny in on kiri0 to 192.168.0.0/16
sudo ufw route deny in on kiri0 to 100.64.0.0/10           # the private network (VPN)
sudo ufw route allow in on kiri0 out on <public interface>
sudo ufw route deny from 10.213.0.0/16 to 169.254.0.0/16
sudo ufw route deny from 10.213.0.0/16 to 10.0.0.0/8
sudo ufw route deny from 10.213.0.0/16 to 172.16.0.0/12
sudo ufw route deny from 10.213.0.0/16 to 192.168.0.0/16
sudo ufw route deny from 10.213.0.0/16 to 100.64.0.0/10   # the private network (VPN)
sudo ufw route allow from 10.213.0.0/16 out on <public interface>
sudo ufw allow from 10.213.0.0/16 to 10.213.0.0/16 port 53 proto udp   # app DNS on its gateway only
sudo ufw allow from 10.213.0.0/16 to 10.213.0.0/16 port 53 proto tcp
```

The deny rules come first so the final allow only opens the public internet. The `kiri0` denies matter for image
builds (the builder is not in the app range). Per-app networks are never removed (Kiri 0.2.0 keeps a DNS listener
on the old gateway after `docker network rm`); a redeploy reuses them. Kiri 0.2.0 also ignores
`enable_icc=false`, so apps on different networks are separated by the network and the firewall, not by that flag.
Kiri may add its own forward rules ahead of ufw's, which is why the check below is part of the setup.

### Check once after setup

Deploy a python app, then run each of these inside its container (`docker exec <container> python -c ...`, or
`docker run --rm --network <app network> python:3.12-slim ...`). Every one of them must FAIL (time out or be refused):

1. Connect to another app's container IP and port.
2. Connect to another app's published port through the app network's gateway address.
3. Connect to a private-network (VPN) address, any 100.x.y.z host that is up.
4. Connect to `169.254.169.254` (cloud metadata).
5. Connect to a port on the host that is not open to the world (for example the admin port).

Then run `ip -6 addr` (and `ip -6 route`) in the container: there must be no global or ULA IPv6 address.
Do this on the edge machine before turning container mode on for the shared server.

## Not included
Several admins, custom domains per app, app logs view, own databases beyond SQLite.

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
