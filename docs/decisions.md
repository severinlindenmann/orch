# Settled decisions

One line per decision, newest first. Agents never reopen a decision without the owner (AGENTS.md R9.5).
Older decisions: `owner-decisions.md` (4 Nov 2026) and `owner-plan.md`.

- 2026-11-15: The fixed rules in `AGENTS.md` are accepted. Reasons and choices: `principles.md`.
- 2026-11-15: The orch-core proof/signing leftovers (humanproof, pageproof, filesig, keystore, denyrules, human-proof
  contract, syncgate) are removed in one clean-up PR.
- 2026-11-15: The relay and publish clients stay in the core as optional built-ins (off until `orch addon add`). They
  are not add-on packages.
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
