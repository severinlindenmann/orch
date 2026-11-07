# orch iPhone app v3 — mockup (visual source of truth)

Clickable HTML mockup of the whole phone app v3 ("messenger"): workspaces with a General conversation and topic
sub-chats, voice in/out (German, English, Swiss German), artifacts with in-app preview and comment pins, questions,
delivery receipts, media, location, offline outbox, pairing / add workspace, settings.
Owner-reviewed in 5 rounds on 6 Nov 2026 (Codex + Opus challenges between rounds).

Open: `python3 -m http.server 8000 --bind 127.0.0.1 --directory mobile/docs/mockup-v3` → http://127.0.0.1:8000/
(the right panel jumps to every screen; `?phone=1` shows only the app). Works offline, no build.

- `archive.html` — archive, delete and auto-archive of chats (swipe, Undo, Archived list, Settings > Chats; phone-local).
- `mobile-mode.html` — the Mobile mode banner on the chat list: on, computer not reachable, phone muted.
- `notes.html` — what the backend needs (contracts: `contracts/relay-api.md` "Phone API v3").
- `FEATURES.md` — inventory of the app before v3 (every feature must stay).
- `RESEARCH.md` — messenger UX + speech research behind the design.
- `CHANGES.md` — what each review round changed.
- `audio/` — real Deepgram Aura-2 samples (German, English).

Rule (orch-mockup): every UI change to the phone app updates this mockup in the same PR, and the app never ships a screen
or state the mockup lacks.

What is simulated here: recording, transcription, replies, camera, uploads, sync, push, pairing. Audio playback is real.
