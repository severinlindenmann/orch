# orch

Agent workspaces with tickets that change while you work, proof for every finished step, and two small servers to share
work: **publish** (encrypted file links and small apps) and **relay** (workspaces and your phone talking to each other).

Works with any agent tool: Claude Code, Codex, Copilot, Claude Cowork. Everything installs as a skill in `.agents/skills/`.

## Install

macOS / Linux:

    curl -fsSL https://raw.githubusercontent.com/severinlindenmann/orch/main/install.sh | sh

Windows (PowerShell):

    irm https://raw.githubusercontent.com/severinlindenmann/orch/main/install.ps1 | iex

Then in a project folder: `orch init`. Add-ons: `orch addon add dashboard`, `orch addon add scheduler`.

## Folders

| Folder | What | Stack |
|---|---|---|
| `contracts/` | shared formats: ticket, message, workspace list, APIs, crypto | JSON Schema + docs |
| `workspace/` | the `orch` CLI and its skills | Python, uv |
| `workspace-addons/` | dashboard (display only), scheduler | Python, uv |
| `publish/` | publish.severin.io: encrypted files, small apps | Rust |
| `relay/` | relay.severin.io: inbox, rules, webhooks, shared config, phones | Rust |
| `mobile/` | iPhone app | Swift |
| `e2e/` | end-to-end scenarios | |

Each folder has its own CI (`.github/workflows/<folder>.yml`), run only when that folder or `contracts/` changes.
Specs: `docs/`. Prototype status: `docs/CHECKLIST.md` and `DEVIATIONS.md`.

License: PolyForm Noncommercial 1.0.0.
