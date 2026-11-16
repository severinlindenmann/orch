# Settled decisions

One line per decision, newest first. Agents never reopen a decision without the owner (AGENTS.md R9.5).
Older decisions: `owner-decisions.md` (4 Nov 2026) and `owner-plan.md`.

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
