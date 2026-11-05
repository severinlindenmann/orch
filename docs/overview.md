# orch prototype: overview

## How the parts fit

```
 laptop / customer PC (any agent tool)                    VPS (Caddy + systemd)
 ┌───────────────────────────────┐   HTTPS   ┌────────────────────────────────┐
 │ workspace: orch CLI + skills  │──────────▶│ publish.severin.io  (orch-publish) │ files /f/, apps /a/
 │ .orch/tickets/*.json          │           ├────────────────────────────────┤
 │ add-ons (optional, e.g.       │──────────▶│ relay.severin.io    (orch-relay)   │ messages, webhooks,
 │  dashboard, scheduler)        │           └────────────────────────────────┘ shared skills/creds
 └───────────────────────────────┘
                                                        ▲
                                    iPhone (orch-mobile)┘  only through the relay
```

- **workspace** works alone: tickets, checklists with evidence, questions, history. No server needed.
- **workspace-addons**: optional add-ons, turned on per workspace: dashboard (read-only view, hosts add-on tabs) and scheduler (starts agent runs).
  The core knows no add-on by name; contract in `contracts/addon-manifest.md`. Once on, an add-on feels like part of orch (same CLI rules, design, skills).
- **publish**: shares files (end-to-end encrypted) and small apps under a public link.
- **relay**: workspaces talk to each other and to the phone; webhooks; shared skills, MCP servers, credentials.
- **mobile**: answer questions, get pushes, send text or voice to a workspace inbox.

## Onboarding (same for publish and relay)

1. Install orch once per machine (the repo is public):
   macOS/Linux `curl -fsSL https://raw.githubusercontent.com/severinlindenmann/orch/main/install.sh | sh` · Windows `irm https://raw.githubusercontent.com/severinlindenmann/orch/main/install.ps1 | iex`.
   It installs `uv` if missing, then `uv tool install git+https://github.com/severinlindenmann/orch#subdirectory=workspace`.
2. `orch init` once per project folder (`.orch/`, the `orch` skill, AGENTS.md block, `.claude/skills` link, `.gitignore`).
3. Optional add-ons: `orch addon add dashboard` / `orch addon add scheduler` (or a local folder). Later: `orch update` (orch + all add-ons together).
4. The admin opens the portal (private network) → "Add workspace" → name, description, tags (+ rights for publish).
5. The portal shows a prompt with `orch publish connect …` / `orch relay connect …` (+ the onboarding line for machines without orch). The user pastes it into any agent tool.
6. Phone: relay portal → "Add phone" → pick workspaces → QR / `orch://pair` link → open on the iPhone.

## Domains, ports, access

| What | Public | Local on the VPS |
|---|---|---|
| publish | `https://publish.severin.io` (workspace API, `/f/`, `/a/`, onboarding) | API `<private-network IP>:8102` (the reverse proxy forwards publish.severin.io here), admin `<private-network IP>:8411`, apps `127.0.0.1:9100–9199` |
| relay | `https://relay.severin.io` (workspace + phone API, `/webhook/`, onboarding) | API `<private-network IP>:8103` (the reverse proxy forwards relay.severin.io here), admin `<private-network IP>:8412` |
| dashboard | – | on the laptop, `127.0.0.1:8420` |

- One VPS. Caddy does TLS and proxies the public paths only. `/admin` is never routed by Caddy.
- Admin portals: open `http://<private-network IP>:8411/admin` (publish) or `:8412/admin` (relay) from the owner's devices on the private network.
  Admin token required. Never public; no SSH tunnel.

## Monorepo `orch`

```
contracts/          schemas, examples, vectors, API docs (this folder's contracts/)
install.sh install.ps1   one-line installers (raw.githubusercontent.com)
workspace/          Python/uv: orch CLI (tickets, addon, update, publish/relay clients) + skills orch, orch-publish, orch-relay
workspace-addons/   dashboard/, scheduler/  (Python/uv; each has orch-addon.toml)
publish/            Rust: server, portal, file page, onboarding scripts, deploy/
relay/              Rust: server, portal, onboarding scripts, deploy/
mobile/             Swift: OrchMobile.xcodeproj
e2e/                scenarios (e2e-scenarios.md), Playwright, scripts
.github/workflows/
```

## CI

- `ci.yml` runs on every PR. Job `changes` (paths filter) decides which folders changed.
  It calls one reusable workflow per folder: `workspace.yml`, `addons.yml`, `publish.yml`, `relay.yml`, `mobile.yml`.
- A change in `contracts/**` runs `contracts.yml` (validate examples) **and** every consumer: workspace, addons, publish, relay, mobile.
  A change in `workspace/**` also runs `addons.yml` (add-ons call the CLI).
- Job `gate` always runs and is the only required check: green when every called job passed or was skipped.
- Deploy: `publish-deploy.yml` / `relay-deploy.yml` on push to `main` with changes in that folder: build, copy binary over SSH, restart, check `/health`.
- e2e (`e2e.yml`) runs by hand or nightly, not on every PR.
