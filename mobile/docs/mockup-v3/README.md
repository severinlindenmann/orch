# orch iPhone app v3 — mockup (visual source of truth)

Clickable HTML mockup of the whole phone app v3 ("messenger"): workspaces with a General conversation and topic
sub-chats, voice in/out (German, English, Swiss German), artifacts with in-app preview and comment pins, questions,
delivery receipts, media, location, offline outbox, pairing / add workspace, settings.
Owner-reviewed in 5 rounds on 6 Nov 2026 (Codex + Opus challenges between rounds).

Open: `python3 -m http.server 8000 --bind 127.0.0.1 --directory mobile/docs/mockup-v3` → http://127.0.0.1:8000/
(the right panel jumps to every screen; `?phone=1` shows only the app). Works offline, no build.

- `archive.html` — archive, delete and auto-archive of chats (swipe, Undo, Archived list, Settings > Chats; phone-local).
- `draft-1114.html` — phone points 14 Nov (A, B, D, E built; C in progress): swipe to hide Needs your OK, centred group logo, one Mute all, hands-busy New topic.
- `mobile-mode.html` — the Mobile mode banner on the chat list: on, computer not reachable, phone muted.
- `notes.html` — what the backend needs (contracts: `contracts/relay-api.md` "Phone API v3").
- `FEATURES.md` — inventory of the app before v3 (every feature must stay).
- `RESEARCH.md` — messenger UX + speech research behind the design.
- `CHANGES.md` — what each review round changed.
- `audio/` — real Deepgram Aura-2 samples (German, English).

Rule (orch-mockup): every UI change to the phone app updates this mockup in the same PR, and the app never ships a screen
or state the mockup lacks.

What is simulated here: recording, transcription, replies, camera, uploads, sync, push, pairing. Audio playback is real.

11 Nov visual challenge — use the matching entries in the right-panel **11 Nov · Visual challenge** jump list:

- **Chats · Groups** — chats with stacked group badges, report preview, key tag and the 44 pt Done groups row; also present in Workspaces.
- **Group · open** — Pay car tax 2027, member runs, task card, thinking, recipients and group composer; also tap the group in Chats.
- **Group · after send** — the open group with an owner message and delivery ticks; also type and send in the group composer.
- **Group · done** — Pay car tax 2026 with system pills and Read only footer; also tap a row in Done groups.
- **Done groups** — muted group rows without unread badges; also tap Done groups in Chats.
- **Ticket info · collapsed** — PIL-12 app-layout header, description, Results and counted tabs; tap a result to expand.
- **Ticket info · expanded** — agent result with summary, totals and fitted chart; tap the chart to preview it.
- **Ticket info · job result** — expanded job result with right-aligned numbers and 3 of 40 rows; switch Photos / Files / References / Artifacts below.
- **Ticket · ready for review** — Result with a fish-page artifact preview and Accept / Ask for changes bar; also replaces Questions → Accept / Ask for changes.
- **Ticket · no review question** — finished work stays Ready for review with 3 of 3 tasks done and no review bar.

Ticket info is also reachable through PIL-12 → Info or the existing Artifacts · Files · References entry. Back returns to the originating screen. New fixtures are local simulations; jump-list entries reset them for repeatable review.

11 Nov: helper wording
