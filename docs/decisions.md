# Settled decisions

One line per decision, newest first. Agents never reopen a decision without the owner (AGENTS.md R9.5).
Older decisions: `owner-decisions.md` (4 Nov 2026) and `owner-plan.md`.

- 2026-11-21 (ORCH-1036/ORCH-1273, owner): The workspace switcher keeps the person's own "Saved places" (dashboards,
  relay and publish pages) per browser and lists other networks because the person added them; this ends the 8 Nov
  rule that a workspace in another network is never listed. Places from a link are kept only after a tap; local
  addresses stay in their browser. Owner picked option A and draft A and approved "Saved places", "Add place",
  "Share my places".
- 2026-11-21 (ORCH-1121, owner): The orch monorepo is licensed under the Apache License 2.0 (was PolyForm
  Noncommercial 1.0.0). The copyright line lives in `NOTICE`.
- 2026-11-19 (ORCH-853): A moved workspace folder keeps its saved keys only through `orch workspace move-here`, run by
  the person in a terminal in the moved folder (never a helper, no `--yes`); a copy (the old folder is still there)
  is refused. Refusals name the old folder and this command instead of "holds a secret".
- 2026-11-16 (ORCH-29): No core start check on tickets: `start_requires` (#777) is removed. The person's Factory Start
  only tells the manager agent to go; an agent can start a crew ticket itself.
- 2026-11-16: `orch uninstall` has no option to delete tickets: it always keeps `.orch/tickets`, `.orch/config.toml`
  and `.orch/secrets`.
- 2026-11-16: The person's own "when to ask" list is the file `.orch/ask-when.md`.
- 2026-11-16: A secret inside a ticket shared with `--full` goes out as `[hidden]` (redacted, not refused).
- 2026-11-16: The agent deny rules (denyrules) are removed: no agent fence on orch's own folders inside the workspace;
  the secret scan stays (#945).
- 2026-11-15: Publish apps have two independent settings: reach (public = internet, private = only on the private
  network, own listener) and auth (needs the app's private link). The link key stays the auth; no passwords, no
  end-to-end encryption for apps. In product text "public"/"private" mean reach, never auth.
- 2026-11-15: The fixed rules in `AGENTS.md` are accepted. Reasons and choices: `principles.md`.
- 2026-11-15: The orch-core proof/signing leftovers (humanproof, pageproof, filesig, keystore, denyrules, human-proof
  contract, syncgate) are removed in one clean-up PR.
- 2026-11-15: The relay and publish clients stay in the core as optional built-ins (off until `orch addon add`). They
  are not add-on packages. Until a workspace
  turns one on, agents see no trace of it (no skill, AGENTS entry, help text or hints).
- 2026-11-15: Add-on stylesheets and the copied kit merge into the master design system; a style lint stops new ones.
- 2026-11-15: Windows: a CLI smoke runs on Windows + macOS on every PR touching `workspace/` or `workspace-addons/`; the
  full suite runs nightly.
- 2026-11-15: Sharing agent context between workspaces defaults to a summary plus picked items, with a preview; a full
  ticket is opt-in per send.
- 2026-11-15: Inbound work from another workspace is data, never instructions; it runs only after the receiver's allow.
- 2026-11-15 (Kiri): publish apps run on Kiri (no Docker fallback). Relay and publish stay systemd services. Apps use
  `<app>.publish` subdomains only.
- 2026-11-12: Prototype security is light: harden only relay and publish against the outside; workspace-internal agent
  hardening becomes issues.
- 2026-10-31: The mockup is the visual source of truth for screens; every UI change updates it in the same PR.
- 2026-11-04: Fresh start as the monorepo `orch`. orch-core is a parts bin for visuals and snippets, not concepts.
- 2026-11-04: Publish files are end-to-end encrypted (key in the link fragment). The relay is encrypted at rest, and the
  admin can read messages.
- 2026-10-27: Product text never names the VPN product; it says "private network".
- 2026-11-15: Linked work = core references + `orch ref set` + tool skills; no tracker add-on.
- 2026-11-15: Factory (#816): ask another workspace at a stop + hand a task over; no share-of-time cap on hand-overs.
- 2026-11-15: Lessons are written by helpers themselves: one list, 3 KB in the start text, local only (no questions, no proofs).
- 2026-11-16 (ORCH-14): New user-facing noun "Epic" (owner approved): New ticket can make an epic with several tickets
  inside it, each with its own text and files. One run on the epic works through its tickets in order.
- 2026-11-16 (ORCH-34): A problem report can be shared with the relay, only by an explicit tick in Report a problem
  (or `orch relay problem share`). New relay admin page "Report a problem" (owner: the same name as the button). Only workspaces
  the admin ticks there may pick problems up. Replaces "problem reports never go via the relay".
- 2026-11-16 (ORCH-99): Hand-made scripts are a first step only (R4.6). Each gets a ticket that moves its job into orch
  (core or add-on) with tests, then the script is deleted. No AI call for work a program can do.
- 2026-11-17 (ORCH-191): A phone card settled in orch (answered in orch, review ended, ticket dropped/done/removed) is
  closed with the existing taken-back text and a fixed reason, never the answer; the relay takes back review rounds too.
  Subscribers get a taken-back text as a `closed` event (with `question_id`, `reason`) instead of a plain `text` event.
- 2026-11-17 (ORCH-146, ORCH-165): One GitHub add-on, `pull-requests` (owner): the merge queue, Merge when green, the Pull
  requests page and the live pull request state on tickets. Its one background watcher reads the linked repositories
  (read-only) and then runs Merge when green, every minute. `orch github` (write limit, expert) stays in the core.
  Screen words "Pull requests", "Merge when green", "Merge queue" approved.
- 2026-11-17 (ORCH-186): Add-on pages orch ships run sandboxed in the dashboard and act only with a frame pass for
  their own add-on (15 minutes, bound to the sign-in, host name and port; a fixed list of actions per add-on). Their
  program files (`/addon/<shipped>/kit|web/*.js|css|svg|png|woff…`) load without sign-in, also on the port for other
  computers: a sandboxed page sends no cookie, and these files are open-source code with no workspace data. They show
  which shipped add-ons run. Accepted by the manager for the prototype, not decided by the owner: open for the owner
  to overrule.
- 2026-11-17 (ORCH-308, from ORCH-281/ORCH-354 triage): Every dashboard feature has a click-through (do it, reload,
  check, no console error) on a seeded demo workspace with the real server; a new action or page brings its
  click-through in the same pull request. The feature list is read from the code, so the `dashboard` CI job names a
  feature without one, and `page-smoke` runs them all on every dashboard pull request.
- 2026-11-19 (ORCH-649, owner): No separate notebook app and no notebook device on the relay. A person's workspace
  runs on their own notebook, so Personal runs its ways in directly in the workspace there; a team server getting one
  person's private data is out of scope. The bridge from 18 Nov was removed before any release.
- 2026-11-24 (ORCH-950, q10): The hourly live check of relay and publish is on again. Its schedule is the orch
  automation repeat on ORCH-950 (a program, honours `orch pause`, at most 30 runs a day), which also starts the
  outside GitHub job when GitHub dropped its own hourly cron (issue #2657); the cron stays only as a fallback.
- 2026-11-24 (ORCH-1676, owner): No dev relay. relay.dev.severin.io is dropped (it failed every secure connection
  since the server move and no code uses it); the demo workspaces and the demo phone use the production relay as one
  more pair set by the admin. One relay is simpler.
- 2026-11-25 (ORCH-2166, RP3 A, owner): No extra accept step. Two workspaces the admin paired on the relay trust each
  other from the first message (no fingerprint compare, no Accept); it shows on Home as a new contact connected by the
  admin. A task (delegate or start) still asks the receiver first (R3.2), and a key that changes later or a contact
  taken back stays held until a person accepts. Security-relevant: the pairing on the relay is now the trust basis.
- 2026-11-27 (ORCH-2349, security review of RP3 A): the key trusted on first contact is the one refresh kept in the
  guarded orch home from the relay's own answer, never `workspaces.json` in the workspace folder. They differ or no
  copy is kept yet: the message is held and a refresh settles it.
- 2026-11-27 (ORCH-2348, decided by the dev agent in finish mode, owner reviews the words on the ticket): receipts
  between workspaces are automatic `ack` updates with fixed lines ("Passed on to <KEY>", "Passed on to Chat",
  "Delivered"); no relay route, no schema change. No answer for 3 days on an open ticket raises one question for the
  person. "Accept a workspace once" is RP3 A (already built): no further accept step.
- 2026-11-25 (ORCH-2166, RP8 B, owner): The two add-ons are called "Relay" and "Publish" on every screen, in menus,
  Settings and the helper's texts; commands stay `orch relay` / `orch publish`. "Contacts", "Phone link" and
  "Shared" are no longer names of them. Errors read "The relay can't be reached" / "Publish can't be reached".
- 2026-11-25 (review overhaul, owner's picks R1 A, R2 A, R3 B, R5 A): Review cards are twelve kinds in four
  families (Decide, Look at the result, Only you can press it, Needs you in person), picked by orch from what a card
  carries; the list shows what holds up work first. `orch ask` refuses a question over 40 words and a report of a
  state. "Nothing closes by itself" is the Reviewer mode `workflow.reviewer_mode = propose`; the default stays accept.
- 2026-11-27 (ORCH-2188, owner pick B a; ORCH-2314): typing into a helper's live screen is on by default, with no
  switch on the screen: a click into the terminal types. Watch only is a setting (`focus.session_typing off`). A
  config file that cannot be read counts as watch only. The plain terminal keeps its own switch, off (ORCH-261).
- 2026-11-28 (ORCH-2177, review overhaul R5 A, third refusal): `orch ask` refuses a helper's plain question without
  answers to pick (R2.4), with the next step; it was a hint since 25 Nov. Ideas to sort, cards and an add-on's own
  question (`--kind`) are not touched. A person's own question without answers keeps the hint: Factory's question to
  another workspace is asked by a person's click and answered in free words.
- 2026-11-28 (ORCH-2407, owner: orch never overloads its computer): every background start of orch's own goes through
  `procs.background_start`: at most `workspace.background_max` (default 4) at once per workspace, none while the
  1-minute load per processor core is over `workspace.background_load` (default 1.5; Windows has no load, there only
  the count), and a background process (`ORCH_BG_DEPTH` set) never starts another one. A skipped start is not an
  error; a later command starts it. A start a person asked for is counted, never skipped. `orch doctor` names both.
