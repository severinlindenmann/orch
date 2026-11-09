# Common rules for publish and relay APIs

- **Times:** RFC 3339, UTC, seconds, ends with `Z`: `2026-11-04T11:00:00Z`. Same in tickets and messages.
- **IDs:** prefix + lowercase letters/digits: `ws_` (10), `ph_` (10), `wh_` (10), `m_` (16), `b_` (16), `t_` (6–16), file and app ids `f_` (16), artifact ids `a_` (12 hex, relay-api.md Phone app v3). Phone `client_id`s are UUIDs. Tokens: see crypto.md.
- **Errors:** always `{"error": "<code>", "message": "<plain words>"}` with the HTTP status. Deploy failures add `"output": "<test or health output>"`.
  Codes: `unauthorized` 401, `forbidden` / `not_allowed` 403, `not_found` 404, `conflict` / `already_answered` 409, `gone` 410, `too_large` 413, `rate_limited` 429, `tts_cap_reached` 402, `transcription_failed` / `tts_failed` 502, `transcription_off` / `tts_off` 503, `invalid` 422 (schema), `test_failed` / `health_failed` 422.
- **Lists:** newest first, `?limit=` (default 50, max 100) and `?after=<cursor>`. Response `{"items": [...], "next": "<cursor>" | null}`. The cursor is opaque.
- **Unknown fields** in requests and messages are allowed and kept. Clients ignore unknown fields in responses.
- **Nullable:** a field that has no value is `null`, never left out, in responses.

## Cross-cutting invariants (all contracts, also the workspace CLI)

**Threat-model boundary (owner decision R1: Level 1, no OS sandbox).** An agent runs as the same OS user and can always read
or write anything that user can. **Goal:** no agent can act as the person *through orch's own interfaces*: flags,
environment, workspace files, the local page, the relay client. **Non-goal:** an agent that patches the orch install, edits
orch-home files directly, or traces processes; such findings go to "Level 2 later" (human-proof.md), not into these contracts.

- **H1. A human-only action needs proof from the human channel, never caller-asserted flags or environment.** How: human-proof.md
  (a short-lived HMAC proof minted by the local page server, bound to action, target and expiry, passed on stdin). Every
  contract with a human-only op names it and links there.
- **P1. Default = hide or deny.** Allowlists are minimal and enumerated; unknown or missing values fall into the hidden or
  denied branch (unknown source → name hidden, unknown block → "can't show this here", unknown event kind → skipped, no
  allow entry → action not allowed, no proof → refused, no value hider → nothing recorded).
