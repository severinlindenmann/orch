# orch-publish API (v1)

Base: `https://publish.severin.io` (reverse proxy → `<private-network IP>:8102`). JSON in, JSON out.
Times, IDs, errors and lists follow `common.md`.

**Workspace auth** (all `/v1/` routes): two headers.

```
X-Orch-Workspace: ws_pilatus001
Authorization: Bearer orp_<43 chars>
```

Wrong or missing → `401`. Right token but no right for this action → `403`. A workspace only sees and changes its own files and apps (others → `404`).
Rights per workspace (set by the admin): `files` (temporary files), `apps` (temporary apps), `permanent` (may make files and apps permanent), `public` (may make public apps; without it apps are private only).

## Workspace API

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/v1/whoami` | – | `{id, name, description, tags, rights, max_file_mb, default_days, max_days}` |
| POST | `/v1/files?days=7` or `?permanent=1` | body = encrypted blob (`application/octet-stream`, crypto.md) | `201 {id, url, size, expires_at\|null}`. `url` has no key; the CLI adds `#k=<key>`. `days` 1–90, default 7 |
| GET | `/v1/files` | – | list of `{id, size, created_at, expires_at}` |
| DELETE | `/v1/files/<id>` | – | `204` |
| PUT | `/v1/apps/<name>?days=7` or `?permanent=1` | body = `.tar.gz` of the app folder (has `app.toml`), max 100 MB | `200 {name, url, status, expires_at\|null, view_token\|null}`. Runs `test`, starts, checks `health`. On failure the old version keeps running: `422 test_failed\|health_failed` with `output`. A redeploy keeps the existing `view_token` unless `?new_token=1` |
| GET | `/v1/apps` | – | list of `{name, stack, store, public, status: running\|stopped\|failed, url, expires_at, updated_at}` |
| POST | `/v1/apps/<name>/restart` | – | `200 {name, status}` |
| POST | `/v1/apps/<name>/stop` | – | `200 {name, status}` |
| DELETE | `/v1/apps/<name>` | – | `204` (code and data are removed) |

`<name>`: `^[a-z0-9-]{2,40}$`, unique on the server (first workspace wins). `view_token` is set when `public = false`.
Expired apps are stopped and removed by the hourly sweep, like files.

## Public routes (no workspace auth)

| Method | Path | What |
|---|---|---|
| GET | `/f/<id>` | Small HTML page. Its JS reads `#k=` from the URL, fetches the blob, decrypts in the browser, offers the download. States: decrypting, ready, expired (`410`), missing key, wrong key. Headers: `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'` |
| GET | `/f/<id>/blob` | The encrypted blob (`application/octet-stream`). `404` / `410` when gone |
| ANY | `/a/<name>/...` | The app. Private apps need `?token=<view_token>` once; the server sets a cookie (HttpOnly, SameSite=Lax, path `/a/<name>/`) and redirects without the token. No token → small "This app is private" page (`401`) |
| GET | `/onboarding.sh`, `/onboarding.ps1` | Small scripts: install orch if missing, then `orch publish connect` (below) |
| GET | `/health` | `200 ok` |

Known prototype risk: apps run on the same origin as `/f/` pages and each other. A hostile app could read another app's pages in the browser. Only the owner's workspaces deploy apps.

## Onboarding

The admin creates a workspace. The portal shows the prompt once:

```
Connect this workspace to orch-publish. Run in the project folder:
  orch publish connect https://publish.severin.io --workspace ws_pilatus001 --token orp_...
If orch is not installed yet:
  macOS/Linux: curl -fsSL https://publish.severin.io/onboarding.sh | sh -s -- --workspace ws_pilatus001 --token orp_...
  Windows:     & ([scriptblock]::Create((irm https://publish.severin.io/onboarding.ps1))) -Workspace ws_pilatus001 -Token orp_...
```

`onboarding.sh/.ps1` only install orch if missing (they run the GitHub `install.sh/.ps1`) and then run `orch publish connect`.
`connect` (in the CLI): runs `orch init` if needed, checks the token with `/v1/whoami`, writes `.orch/secrets/publish.json`,
copies the `orch-publish` skill (shipped inside the CLI) to `.agents/skills/`, adds the AGENTS.md block. Layout: local-files.md.

## Admin API (only on `<private-network IP>:8411`, reached directly from the owner's devices on the private network; never public)

Auth: header `X-Orch-Admin: <admin token>` (file `/etc/orch-publish/admin-token`). The portal at `/admin` asks for it once and keeps it in a cookie.

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/admin` | – | Portal HTML |
| GET | `/admin/api/workspaces` | – | list of `{id, name, description, tags, rights, files, apps}` |
| POST | `/admin/api/workspaces` | `{name, description, tags: [], rights: {files, apps, permanent, public}}` | `201 {id, token, prompt}` (token shown only here) |
| PATCH | `/admin/api/workspaces/<id>` | `{name?, description?, tags?, rights?}` | `200 {id, name, description, tags, rights}` |
| POST | `/admin/api/workspaces/<id>/token` | – | `200 {token, prompt}` (new token, old one stops) |
| DELETE | `/admin/api/workspaces/<id>` | – | `204` (its files and apps are removed) |
| GET | `/admin/api/files` | – | list of `{id, workspace, size, expires_at}` (content is unreadable) |
| DELETE | `/admin/api/files/<id>` | – | `204` |
| GET | `/admin/api/apps` | – | same as `/v1/apps` plus `workspace` |
| POST | `/admin/api/apps/<name>/restart` \| `/stop` | – | `200 {name, status}` |
| DELETE | `/admin/api/apps/<name>` | – | `204` |
