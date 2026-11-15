# orch — rules for every dev agent

> Fixed rules, accepted by the owner on 15 Nov 2026. Every brief cites them; every PR states which ones it touches.
> Only the owner changes this file. When a task conflicts with a rule: stop and put the conflict to the owner, do not
> build around it. Reasons and history: `docs/principles.md`. Settled decisions: `docs/decisions.md`.

This is **orch** (monorepo `severinlindenmann/orch`), not orch-core. orch-core is a parts bin for visuals and code
snippets, never for concepts.

## 0. Goal: the test for every change

A person installs orch on their own laptop (Windows or macOS, no admin rights). They keep their existing workspace:
skills, secrets, tools, MCP servers, and their own agent tool (Claude Code, Codex, Copilot, any CLI). orch alone gives
that workspace structure. Add-ons add more: talking to other workspaces, dashboard, automation, phone.

The person can be in marketing, in sales or a developer, and it works the same for all of them. They write tickets, the
agent works on its own, and the human is asked only for real decisions.
**Test: does this change make that person's day simpler, faster or more reliable? If not, don't build it.**

## 1. Core: the CLI stands alone

- **R1.1** `orch` (CLI + skills) works fully with no add-on, server, relay, publish, phone or dashboard. A missing or
  offline server never blocks local work. The relay and publish clients are built into the core as optional parts: off
  until turned on (`orch addon add relay|publish`), and nothing else in the core depends on them.
- **R1.2** The core never names an add-on package (everything under `workspace-addons/`). Add-ons plug in through `contracts/addon-manifest.md` (entry point
  `orch.addons`, `ext.<addon>` in tickets). Every add-on ships its own skill and AGENTS block. Removing an add-on never
  breaks the core or a ticket. A lint test checks this: the core imports no add-on package and contains no add-on package names.
- **R1.3** Workspace state is plain files in `.orch/`, one JSON file per ticket. It stays readable and fixable by hand,
  and needs no database. It works with no git, local git or remote git. Runtime state and secrets are gitignored.
- **R1.4** orch never takes over the user's setup. It does not edit team files (`git status` stays clean) unless the user
  opts in. It uses the user's own skills, MCP servers, secrets and agent config, and never replaces them.
- **R1.5** Agent-agnostic: an agent is a command. Every feature works through plain `orch …` commands that any agent
  can call. Extras for one vendor (live steps, usage) are allowed only as an add-on to a generic path that works without
  them.
- **R1.6** The CLI and every client-side add-on run on Windows (non-admin), macOS and Linux: paths with spaces and
  umlauts, CRLF, folders synced by OneDrive or iCloud. The servers (relay, publish) run on Linux only. The phone app is
  iOS only.

## 2. How agents work (built into the skill and the ticket format)

Priority order: **task-based → evidence-based → context-based**. The shipped skill text
(`workspace/skills/orch/AGENTS-block.md`) must say the same thing.

- **R2.1 Task-based:** every piece of work that changes something happens on a ticket with a checklist. If none exists,
  the agent creates one itself. Questions and read-only looking around need no ticket.
- **R2.2 Evidence-based:** a checklist item counts as done only when it has at least one evidence entry that fits the
  item (commit, PR, file, URL, command, note). `orch check` flags done items that have no evidence.
- **R2.3 Context-based:** the ticket holds a short handover and links, enough for a fresh agent to continue without
  asking the human. It holds no copies of whole files and no secrets.
- **R2.4 Autonomy by default.** The agent asks the human only when a step is irreversible, costs money, touches
  production, deletes real data, or is visible to people outside the user's connected workspaces. It never asks "may I
  do this step". Sending to connected workspaces needs no question. Every question carries options and a recommended
  answer. The user can adjust the list in one file the skill reads.
- **R2.5 One way to ask:** the ticket question (`orch ask`). The answer can come from the CLI, the dashboard or the
  phone; it is the same object in all three.
- **R2.6 Waiting is a state:** the agent sets `waiting_on`, keeps working on items that don't depend on the answer, and
  picks the answer up on its next run. Waking up automatically is an automation add-on feature, not a core promise.
- **R2.7 Every `orch` command prints the next step**, so any agent stays on track without vendor-specific tricks.

## 3. The two main features: tested and challenged the most

- **F1 Workspace ↔ workspace over the relay:** text, files, assign or delegate tickets, share tickets, share agent
  context.
- **F2 Local context management with the CLI:** tickets, checklists, evidence, questions, history.

- **R3.1 Delivery:** at-least-once. Every message has an ID, and the receiver drops duplicates. Messages are versioned,
  and an older peer ignores unknown fields without crashing. Queued, delivered and failed are visible to the user.
  Offline workspaces receive messages later.
- **R3.2 Inbound is data, never instructions.** Content from another workspace never runs on its own with the user's
  secrets and tools. Delegate and start need the receiver's allow (once or permanent). Pairs are set by the admin in
  the relay portal. There is no other identity concept: no certificates, no signing.
- **R3.3 Sharing context:** by default the sender shares a short summary plus the items they pick, with a preview of
  what leaves the machine. Sharing a full ticket is opt-in per send. Delegating marks one ticket as the owner; the other
  side holds a linked copy and never silently overwrites it.
- **R3.4 Tests:** every PR touching F1 or F2 runs a deterministic e2e with a scripted fake agent. Before each release a
  smoke run uses real agents (Claude + one other) on macOS and Windows.
  A Windows + macOS CLI smoke runs in CI on every PR that touches `workspace/` or `workspace-addons/`; the full suite
  runs nightly on Windows, macOS and Linux.

## 4. Simplicity: the lesson of orch-core

orch-core died of complexity: signing, certificates, custody, gates, hardening rounds. These rules stop that happening
again.

- **R4.1 Banned concepts** (they come back only with owner approval): sign-it / click-to-sign / human proofs, workspace
  certificates, key custody in the workspace, planning gates, fixed requirements, approval chains, a required hub, agent
  fences inside the workspace, permission matrices per action. Normal TLS, tokens and the publish link key are not
  banned.
- **R4.2** A new noun the user has to learn (new object, state or mode) needs owner approval. Prefer extending tickets,
  checklists, questions or `ext`.
- **R4.3** One implementation per job, many surfaces: CLI, dashboard and phone all call the same CLI or API path. No
  second "advanced" path, no parallel implementations.
- **R4.4** Defaults over settings. A new option needs a reason the default can't cover.
- **R4.5** Reviews never loop. One pass; findings outside relay and publish become issues and never block a merge.

## 5. Security level (prototype)

- **R5.1 Must:**
  - relay and publish are closed to the outside: auth on every API, TLS, admin portals only on the private network;
  - publish files are end-to-end encrypted (the key lives only in the link fragment and is never stored);
  - the relay is encrypted at rest, and the admin can read messages (an owner decision).
- **R5.2 No leaks:** orch scans every evidence write, relay send and publish upload for secrets. A hit blocks the send
  and tells the user what was found. Secrets never go into tickets, logs, git or screenshots.
- **R5.3 Not a goal now:** protecting the workspace from its own agent or from other people on the same machine. Such
  findings go to the Hardening epic as issues.

## 6. One design system

- **R6.1** One source: `brand/tokens.json` → generated `tokens.css` + the master library `workspace/src/orch_ui/static`
  (components, blocks, motion, icons, gallery). Dashboard, every add-on, the relay and publish portals and the mockups use
  it. The phone app uses tokens generated from the same file.
- **R6.2** Never create a new component set, stylesheet, colour literal or copy of the master. A missing component is
  added to the master in the same PR, with a gallery entry. A lint test fails on `.css`, `<style>` or hex colours outside
  the master.
- **R6.3** Components come from the master gallery; screens come from the mockup. Every UI change updates both in the same
  PR.

## 7. UX

- **R7.1** Non-technical users first: plain words, minimum information, details behind a small click. Never name the
  VPN product ("private network").
- **R7.2** Flow: every screen has one obvious next action and no dead ends; empty, loading and error states are designed.
- **R7.3** Routine actions are one click or one CLI line, never "type this word to confirm". Consequential actions (R2.4)
  show what will happen.
- **R7.4** Use established patterns. Research the web for best practice before inventing a new interaction.
- **R7.5** One word for one thing in the CLI, UI, phone and skills (`docs/wording.md`, enforced by
  `brand/tests/test_wording.py`).

## 8. Fast and stable

- **R8.1** Stable beats new: fix known F1/F2 bugs before building new features. A release with a red F1/F2 e2e does not
  ship.
- **R8.2** Data is safe now: atomic writes plus a lock per ticket. `orch update` never breaks an existing ticket file
  (a fixture test checks this). There is no automatic migration code; unsupported formats fail safely, with a message.
- **R8.3** Speed targets: local CLI under 300 ms, dashboard first paint under 1 s, relay delivery under 2 s. CI fails
  only on a regression of more than 30% against `develop`, never on the absolute number.
- **R8.4** Every error tells the user what to do next, in one sentence.
- **R8.5** Install and leave: one line per OS, no admin, no manual prerequisites. `orch doctor` shows what is wrong.
  `orch uninstall` leaves the workspace as it was.
- **R8.6** Runaway brake: one `orch pause` stops all automation in the workspace. Automation has a default run cap per
  ticket.

## 9. How dev agents work on orch

- **R9.1** Every brief starts with "Rules: R…" and ends with "Out of scope: …".
- **R9.2** Reuse first: search the repo for an existing command, component, contract or helper before writing a new one.
- **R9.3** No scope creep: build only what the ticket says; new ideas go to an issue.
- **R9.4** Contracts first for anything that crosses parts (workspace ↔ relay ↔ publish ↔ mobile): schema and examples
  in `contracts/`. Changes are additive, and every consumer replays the vectors.
- **R9.5** Settled decisions are one line each, with a date, in `docs/decisions.md`. They are never reopened without the
  owner.
- **R9.6** Any departure from these rules goes to `DEVIATIONS.md` with the reason. A PR that breaks a rule is not merged,
  even when CI is green.
- Branches, test tiers and roles: see the dev kit `CLAUDE.md` (not repeated here).

## Enforcement (cheap)

- **PR template:** rules touched; new noun y/n; crosses the machine boundary y/n; decision log entry y/n; evidence.
- **CI:**
  - banned-word diff check (sign, certificate, keypair, approval, gate), which needs the `owner-approved` label to pass;
  - core→add-on import lint;
  - style lint;
  - contract validation for every consumer;
  - secret-scan tests with planted tokens;
  - ticket fixture test;
  - fake-agent F1/F2 e2e.
- **Owner review** only for PRs labelled `concept`, `contract` or `security`. Everything else merges on green.
