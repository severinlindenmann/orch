# orch – Prototype Plan (owner, 4 Nov 2026)

orch starts again as five small projects. The prototype keeps orch core's look and feel, reuses code only where it fits, and ships only the features listed here.

## Brief (owner's words)
we need to roll out orch completly new. it is to big overhead and to much features at once and does not work anymore as a prototyp. we want to start with a fresh beginning. we want to keep the feel and look (branding, styling) from orch core and maybe we can reuse part of codes but otherwise with a fresh slate. the goal is a few new projects (if old ones exist with same name rename the repos). run subagents for each of them, use codex for visuell part, opus for the plan, and challenge it also each time. what comes out is a visuell draft + a tech stack for each + a really simple stichwortliste what will be implemented to reach a viable prototyp; everything the owner lists is a needed feature. one repo, a subfolder each (workspace, workspace-addons, publish, network); each with its own CI/CD so a change only tests that part.

## Principles
- Fresh start. Keep branding/styling; reuse code only where it fits.
- No signing, no fixed requirements or planning gates. A ticket starts, changes a lot, continues.
- Few features per project. Only what's listed.
- Everything installs as a skill: .agents/skills/ + AGENTS.md entry.
- Any agent tool: Claude Code, Codex, Copilot, Claude Cowork.

## Repository
orch/
  workspace/          orch-workspace         Python, uv
  workspace-addons/   dashboard, scheduler   Python, uv; dashboard UI from orch core
  publish/            orch-publish           Rust
  network/            orch-network           Rust
  mobile/             orch-mobile            Swift
  .github/workflows/  one path-filtered workflow per folder
Old repo with the same name is renamed first.

Each workspace installs the skills of the services it uses. Phone and other workspaces reach it only through orch-network.

## orch-workspace (Python/uv; skills + CLI files only; Windows, macOS, Linux incl. customer Windows)
1. Evidence-based concept
2. Ticketing CLI
3. Checklists, connected to evidence
4. Ticket history and context
5. Ticket format in JSON, flexible/dynamic: extra fields for add-ons, other params/tools; generic links to any tool
6. Questions and answers
Not included: signed tickets, fixed requirements, planning gates.
Ticket JSON sketch: id, title, status, checklist[{id,text,done,evidence[{type,url}]}], links[{type,url}], questions[{id,text,options,recommended,answer}], history[{at,by,text}], wake_at, waiting_on, ext{scheduler{cron}}.
- links open (any type). ext: each add-on owns its key.
- .agents/skills/ is the one real skills folder; .claude/skills -> symlink (mac/linux) / junction (Windows, no admin).

## orch-workspace-addon (Python/uv; each add-on installs a skill + AGENTS.md entry)
1. Dashboard: really light, display-only, reads the ticket files; user works in any other agent tool; optional read-only status snapshot published via orch-publish.
2. Scheduler: agents schedule one-time or recurring tasks; a task reruns an agent session (Claude Code, Codex, other CLI); one-time = ticket wake_at; recurring = ticket type recurring with cron; also checks the orch-network inbox and starts an agent when a task arrives (an already-working agent runs that shell command itself).

## orch-publish (Rust, VPS, HTTPS public domain e.g. publish.severin.io)
1. Public links: apps /a/<app>, files /f/<file>; temporary (default 7 d, max 90 d) or permanent
2. One admin owner, /admin
3. Onboarding prompt: admin sets workspace name + permissions (perm files, apps, temp files, public/private only) -> unique workspace ID + long token + prompt "Integrate the following skill with token XYZ" pointing to publish.severin.io/onboarding.sh; script adds skill(s) to .agents/skills/, AGENTS.md entry, token in gitignored file
4. Encrypted files: VPS can't read; workspace holds key; key in URL fragment; browser decrypts
5. Apps not encrypted; own sandbox; fixed stacks from orch core publish templates: static (HTML/MD), Python (stdlib/FastAPI), Node; store none/JSON/MD/SQLite; app.toml (stack, start, health path, test cmd); host gives PORT, BASE_PATH, DATA_DIR. Token-protected by default (?token=) or public
6. API only with workspace ID + token
7. Admin portal only via localhost (NetBird); sees files (unreadable) and apps, restart/stop
8. Workspaces manage own items via API: list, restart, stop, delete
Max file size 1 GB (env configurable).

## orch-network (Rust, VPS, HTTPS e.g. network.severin.io; messages and files encrypted)
1. Workspaces talk to each other; admin adds a workspace in portal -> prompt installs skill with token
2. Rules between workspaces: which pair, what: share text, share files, delegate a task, start a task. Delegate/start need an extra one-time allow on the receiver with its own token; allow once or permanent (weekly report)
3. Inbox: skill/AGENTS.md says read at session start and when returning to a ticket. Unique message IDs, stored locally, never processed twice. Offline workspaces get messages later
4. Webhooks: one-time or permanent with token (network.severin.io/webhook/<id>?token=); ping-pong wait or GitHub etc.; workspace listens through orch-network
5. Shared skills, MCP servers, credentials: admin configures + assigns per workspace; inbox read installs new/updated ones; `orch network refresh`
6. Admin can read: master key reads agent communication
7. Admin portal only via localhost (NetBird); only workspace API public HTTPS

## orch-mobile (Swift iOS; reuse orch core mobile UI; only with orch-network)
1. Voice input
2. Receive questions and answer them, push notifications
3. Send to a workspace's inbox
4. Onboarding link from orch-network portal; owner sets which workspaces the phone may reach

## Security and tokens
- Tokens: gitignored file; onboarding adds .gitignore entry
- Admin portals: localhost only (NetBird)
- Public HTTPS: only workspace APIs, public links, webhooks
- Published files: encrypted, key in fragment
- Network messages: encrypted; admin master key can read
- Inbox content: untrusted; agent acts with own local permissions; irreversible actions ask the user
- Duplicates/loops: unique message IDs stored locally
- Shared credentials: per workspace

## Decisions
- No time per history entry
- App stacks: static, Python (FastAPI), Node; stores none/JSON/MD/SQLite
- Temp file lifetime default 7 d, max 90 d
- publish in Rust
- One repo, path-filtered CI/CD per folder
- Max file size 1 GB, env configurable
- Repo name: orch
- orch-mobile in the same repo, mobile/
