# orch mobile v3 messenger: research (6 Nov 2026)

Source note: web facts carry URLs. Items marked (known) are established messenger conventions from general knowledge, not freshly sourced. Items marked (verify) must be checked on device before we commit.

## 1. Messenger UX must-haves on iPhone

**Chat list (known)**
- Pinned chats at top (WhatsApp 3, Telegram 5+, iMessage 9); unread badge (count, muted = grey), bold last-message preview, timestamp (time today, weekday this week, date later).
- Swipe: leading = pin / mark unread; trailing = mute / archive / delete (iMessage + WhatsApp + Telegram all use leading/trailing split). Full-swipe performs the first action.
- Search: pull-down search field at top; scopes (chats, messages, files). Archive: hidden row at top that appears on pull (Telegram) or "Archived" row (WhatsApp).
- Long-press chat row = context menu with preview (iMessage style).
- Filters row (All / Unread / Groups). WhatsApp and Telegram folders: good fit for orch ("Workspaces", "Tickets", "Needs me").
- Presence in list: typing indicator replaces preview ("typing…", for agent: "working…").

**Chat room (known)**
- Bubbles: own right/accent, other left/neutral; tail only on last bubble of a group; consecutive messages within ~1 min grouped with tight 2pt spacing vs 8-12pt between groups. Sender name only in groups (workspace agent vs sub-agent).
- Day separators ("Today", "Yesterday", date) as centered pills, sticky while scrolling (Telegram).
- Ticks: clock = pending, one tick = sent to relay, two ticks = delivered to the workspace, two blue/accent = read/handled by agent. Signal: same plus "sending…" circle. Keep to 4 states.
- Reply/quote: swipe right on bubble (iMessage + WhatsApp + Telegram), quote strip above the composer with X; tap quote jumps to original with highlight flash.
- Reactions: long-press shows emoji bar (6 + "+"), reaction chips under bubble. For orch: reactions double as lightweight agent feedback (thumbs up = approve? decision needed).
- Long-press menu: Reply, Copy, Forward, Pin, Select, Delete, Info. iOS 26 renders as glass popover with blurred background.
- Jump-to-bottom: floating circular glass button with unread count when scrolled up; "N new messages" divider at first unread on entry.
- Typing indicator: three animated dots in a bubble (iMessage) or text in header (WhatsApp/Telegram).
- Scroll anchoring: inverted list so newest sits at bottom, keyboard open keeps last message visible.

**Composer (known)**
- "+" opens attach sheet: Camera, Photos, Files, Location, Contact (iMessage uses an app drawer; WhatsApp a grid sheet; Telegram a half-sheet with recents grid, best for speed). Add orch-specific: Ticket, Workspace file.
- Mic button replaces send when the field is empty. Hold-to-record: slide left to cancel, slide up to lock (hands-free), lock shows pause/stop/send. Haptic on start, lock, cancel. Release sends.
- Draft persistence: per chat, shown in list as red "Draft:" prefix (WhatsApp/Telegram). Survives app kill.
- Multi-line growth up to ~6 lines then scrolls; send button animates in.

**Media, links, docs (known)**
- Chat info screen has tabs: Media (grid, filter photos/videos), Links, Docs; Telegram adds Voice and GIFs; WhatsApp "Media, links and docs". Month section headers, tap opens full-screen viewer with swipe between items, share/save/forward.
- Link previews: card with title, domain, thumbnail, fetched on sender side (privacy: Signal fetches on sender; WhatsApp also sender-side). For orch: agent generates previews, phone never hits arbitrary URLs.
- File/PDF bubbles: icon + filename + size + page count, tap = Quick Look, long-press share. Show download progress ring for large files.
- Location bubble: static map snapshot (MKMapSnapshotter) with pin, address line, tap opens Apple Maps. Live location: bubble with timer ring, "Stop sharing" button, durations 15 min / 1 h / 8 h.
- Share sheet in: Share extension so a photo/PDF/URL from any app lands in a chosen workspace chat. Share out: standard UIActivity sheet from long-press menu and media viewer.

**What each does best (known)**
- WhatsApp: voice notes, fast playback, transcripts, simple tick semantics, calm chat list.
- Telegram: speed, attach sheet with recents, folders, scheduled/silent send, saved messages, media tabs, drafts sync.
- Signal: clear delivery/read states, privacy defaults, minimal UI, disappearing messages, strong a11y.
- iMessage: native feel, Liquid Glass, tapback reactions, inline replies, text effects, haptics, lock-screen replies.

**Apple HIG / iOS 26**
- Tab bar floats on a Liquid Glass background, items should never be hidden or disabled when unavailable; controls acting on the current view belong in a toolbar. Nav bars and toolbars float above content with glass. Tab bar can minimize on scroll (`tabBarMinimizeBehavior`), and `tabViewBottomAccessory` hosts a persistent view above the bar (candidate for the voice mini player). Sources: https://developer.apple.com/design/human-interface-guidelines/tab-bars.md , https://developer.apple.com/videos/play/wwdc2025/284 , https://developer.apple.com/videos/play/wwdc2025/323
- Glass belongs on the navigation/control layer; content stays opaque. Do not paint custom opaque backgrounds behind nav/tab bars (blocks glass). Third-party summaries, check HIG Materials page before final (verify).
- Haptics: use `sensoryFeedback` / UIFeedbackGenerator for send, record start/lock/cancel, reaction pick, pin (known).
- Dynamic Type: bubbles must reflow up to accessibility sizes; never fixed heights; timestamps and ticks scale or stack (known).
- Reduce Motion: replace springs/flying bubbles with cross-fade; Reduce Transparency: glass falls back to solid; Increase Contrast and VoiceOver actions on bubbles (reply, react, play) (known).
- Messages-in-iOS-26 features were not covered by the search; (verify) before copying.

## 2. Voice messages UX
- Bubble (known): play/pause circle, waveform (~40-60 bars, played portion filled, scrubbable by drag), duration, speed pill; blue/accent mic dot until listened (WhatsApp turns the mic blue after the recipient listens; Telegram shows a blue dot beside duration until played). Own voice notes: mic turns accent when the agent "listened" (processed).
- Playback speed: WhatsApp Fast Playback = 1x / 1.5x / 2x, pitch preserved, no slow option, tap the avatar/speed chip to cycle. Source: https://www.pocket-lint.com/apps/news/whatsapp/157188-what-is-whatsapp-fast-playback-and-how-to-speed-up-voice-messages , https://www.androidcentral.com/latest-whatsapp-beta-brings-playback-speed-control-voice-notes . Implementation: `AVAudioPlayer.enableRate` / `AVPlayer.defaultRate` with `audioTimePitchAlgorithm = .timeDomain`.
- Auto-play next: consecutive unheard voice notes play in sequence with a soft tick between (WhatsApp, Telegram). Stops at a played one.
- Transcript under voice note: WhatsApp transcripts are free, on-device, opt-in in Settings > Chats > Voice message transcripts, per-language; long-press > Transcribe. iOS languages include German (incl. English, French, Italian, etc.). Source: https://wabetainfo.com/whatsapp-is-rolling-out-new-languages-for-voice-transcriptions/ , https://www.thestar.com.my/tech/tech-news/2024/11/22/whatsapp-rolling-out-transcription-for-voice-messages-in-multiple-languages
- Telegram: voice-to-text button on each voice/video note; Premium unlimited, free users limited (about 2 per week). Source: https://www.engadget.com/telegram-now-offers-all-users-limited-transcriptions-of-voice-messages-185114448.html , https://androidcentral.com/apps-software/telegram-similar-channels-reposting-stories-and-more-features
- For orch we do the opposite: transcript is the default and the primary text (agents read text), collapsed behind a chevron "Aa" under the waveform; tap expands. Show transcript status: "Transcribing…" shimmer, then text, then edit-needed hint if confidence low.
- Raise-to-listen (known): proximity sensor, `UIDevice.proximityState` + route to earpiece; raise while a voice note is shown to play it; raise on a not-yet-recorded composer starts recording (WhatsApp, Telegram).
- Mini player (known): when leaving the chat while audio plays, a bar with play/pause, speed chip, close, title; Telegram pins it under the nav bar. In iOS 26 use `tabViewBottomAccessory` or a glass capsule above the tab bar. Needs background audio session + Now Playing info / remote commands.
- Listened state: tracked per message, synced to the workspace so desktop and phone agree.

## 3. Offline-first patterns
- Outbox (known): message written to local DB with `pending` status immediately, bubble appears with clock icon; tapping failed bubble shows Retry / Delete. Order by local creation time, replace local id with server id on ack.
- Banner wording: Telegram header states "Waiting for network…", "Connecting…", "Updating…". WhatsApp title bar shows "Connecting…" and a banner "Computer not connected" / "Phone not connected" for linked devices (known). Proposed orch wording: "Waiting for network", "Connecting…", and workspace-specific "Workspace offline, message will be delivered when it is back" (the computer being off is the common case, distinct from phone being offline).
- Optimistic UI (known): append locally, animate, reconcile on ack; never block the composer.
- Sync on reconnect: fetch since last cursor, merge, keep scroll position, show "N new messages" divider; dedupe by client-generated UUID (idempotency key).
- Media upload (known): circular progress ring with X to cancel on the bubble; thumbnail shown instantly from local file; background `URLSession` (background config) so uploads continue after app suspend; resumable/chunked uploads (tus-like or per-chunk offsets) so a dropped connection resumes; compress images before send with HD toggle; voice notes upload as soon as recording stops.
- Queue limits: persist outbox across app kill; exponential backoff; surface failure after N tries instead of silent drop.

## 4. Animation patterns
- Send (known): bubble flies from composer to its slot with spring (response ~0.35, damping ~0.8), composer text clears, list inserts with bottom anchor; tail appears after settle. iMessage adds a subtle scale pop.
- Keyboard-synced scrolling: interactive dismiss (`scrollDismissesKeyboard(.interactively)`), composer rides the keyboard; use `safeAreaInset(edge: .bottom)` for the composer so the list inset follows the keyboard automatically in SwiftUI. Telegram's smoothness comes from per-frame keyboard tracking.
- Record button morph: mic to send arrow cross-morph, hold expands to a pulsing red circle, slide-left reveals "Slide to cancel" with the trash icon lid opening (Telegram/WhatsApp), lock chevron rises above.
- Reaction pop: emoji scales 0.3 to 1.2 to 1.0 with spring, brief particle burst optional; bar items magnify on hover/drag.
- Typing dots: staggered sine opacity/offset, 3 dots, 1.2 s loop.
- SwiftUI notes (known, verify on iOS 26): `ScrollView` + `LazyVStack` with `.defaultScrollAnchor(.bottom)` and `ScrollViewReader`/`scrollPosition(id:)` for jump-to-bottom; `matchedGeometryEffect` or `navigationTransition(.zoom)` for media viewer; `PhaseAnimator`/`keyframeAnimator` for reaction pop; `sensoryFeedback(.impact, trigger:)`; `glassEffect()` and `GlassEffectContainer` for floating controls; `withAnimation(.spring(duration:bounce:))`; respect `accessibilityReduceMotion`. A UIKit `UICollectionView` (inverted) can be needed for very long histories; SwiftUI List inserts at top still jump (known pitfall).

## 5. Speech-to-text for German, English and Swiss German
- **Standard approach**: transcribe Swiss German speech into Standard German text (Swiss German has no standard orthography, so dialect-text output makes WER meaningless and agents cannot parse it). Sources: https://preview.aclanthology.org/setup/2024.vardial-1.3 (Whisper viable for Swiss German "so long as the Standard German output is desired"), https://arxiv.org/pdf/2207.00412 (FHNW evaluation of commercial systems).
- **Apple Speech / SpeechAnalyzer (iOS 26)**: `SpeechTranscriber` on-device, locales vary by device; sources disagree on count (~10 to ~40). No source confirms de-CH. Check at runtime with `SpeechTranscriber.supportedLocales`, `installedLocales`, `supportedLocale(equivalentTo:)`; fall back to de-DE or `DictationTranscriber`. Expect Standard German with Swiss accent handled OK, true dialect poor (verify on device with Swiss audio). Sources: https://developer.apple.com/documentation/speech/speechtranscriber.md , https://antongubarenko.substack.com/p/ios-26-speechanalyzer-guide
- **Deepgram**: Nova-3 lists "German (Switzerland) de-CH" as a monolingual model, added Dec 2025, with an improved de-CH model in the changelog. Nova-3 multilingual and Flux multilingual (en, es, fr, de, hi, ru, pt, ja, it, nl) do NOT include de-CH. So for Swiss use `model=nova-3&language=de-CH`; Flux does not cover it. Whether it outputs Standard German from dialect is not stated, test with real audio. Sources: https://developers.deepgram.com/docs/models , https://deepgram.com/blog/deepgram-expands-nova-3-with-10-new-languages-and-multilingual-keyterm-prompting.md
- **OpenAI Whisper / gpt-4o-transcribe**: No gpt-4o-transcribe Swiss German benchmark found (unverified). Whisper large (older) gives Standard German output; paper reports 13.88% WER on one Swiss German test set for a vanilla-ish setup but with Standard German approximations, English interpolations and hallucinations on dialect input. Sources: https://arxiv.org/pdf/2412.15726v2 , https://preview.aclanthology.org/setup/2024.vardial-1.3
- **Azure Speech**: de-CH speech-to-text locale released Oct 2021, recognizes Swiss dialects and standard German, output is Standard German text. No `gsw` locale seen. TTS voices de-CH-LeniNeural, de-CH-JanNeural. Sources: https://azure.microsoft.com/en-gb/updates/release-of-swiss-german-dialect-speech-to-text/ , https://learn.microsoft.com/en-my/AZURE/ai-services/speech-service/language-support
- **Google**: Cloud STT has de-CH (Standard German with Swiss variant); no dedicated dialect model found in this pass (unverified, not searched in depth).
- **Hugging Face Swiss German Whisper fine-tunes** (output Standard German): Flix-AI/flix-swissgerman-full (whisper-large-v3 full fine-tune, 1,367 h; processes segments independently) https://huggingface.co/Flix-AI/flix-swissgerman-full ; Flurin17/whisper-large-v3-turbo-swiss-german (retrained 20 Mar 2026, best for clean conversational speech) https://huggingface.co/Flurin17/whisper-large-v3-turbo-swiss-german . Could be self-hosted on the workspace computer or a GPU box. Metrics not comparable across cards (normalization, 25.6% WER vs 13.8% cWER on one card).
- **Swiss providers** (recapp, SwissText, others): search returned nothing concrete; the FHNW/Swiss Parliament line of work shows in-house dialect models beat commercial ones (BLEU 0.607 vs 0.509). Follow up separately if we want a Swiss vendor (open item).
- **Recommendation**: primary Deepgram nova-3 (language by detection, below) with de-CH for Swiss; A/B against a Swiss Whisper fine-tune on 20 real Swiss voice notes from the owner; Apple on-device as offline fallback for dictation preview.

## 6. Text-to-speech for agent voice memos
- Deepgram Aura-2: German added Jan 2026 (voice count disagrees across sources, 7 vs more), English already. Pay-as-you-go about $0.030 per 1k characters, Growth $0.027. Confirm German uses the same rate. Sources: https://www.together.ai/models/aura-2 , https://www.costbench.com/software/ai-transcription-apis/deepgram/ , https://deepgram.com/text-to-speech-api-li
- Azure Neural TTS de-CH-LeniNeural (female), de-CH-JanNeural (male): Standard German with Swiss accent, standard neural tier. Price roughly $15 per 1M characters (known, verify). https://json2video.com/ai-voices/azure/voices/de-ch-lenineural/
- ElevenLabs: library has a Swiss-accent German voice (e.g. "Heidi", third-party listing). Pricing sources inconsistent: roughly $0.05 to $0.30 per 1k characters depending on plan/model; check https://elevenlabs.io/pricing/api . Highest quality, highest price.
- Play.ht lists Swiss German TTS: https://play.ht/text-to-speech/swiss-german (unverified quality).
- Note: true dialect TTS (Berndeutsch, Zueritüütsch) is not mainstream; Swiss-accented Standard German is what exists. Reply voice memo should be short (agent summary), generated on demand not for every message, cached by text hash.

## 7. Language detection to choose reply language
- Deepgram: `detect_language=true` (prerecorded) picks ONE dominant language for the file; `language=multi` enables code-switching on Nova-3 (with `endpointing=100`). Sources: https://developers.deepgram.com/docs/language-detection.md , https://developers.deepgram.com/docs/multilingual-code-switching.md . Caveat: do not rely on multi for de-CH, since it is not in the multi list.
- Whisper: detects from the first 30 s; short clips (<4 s) are unreliable, mixed-language audio confuses it. https://www.mintlify.com/openai/whisper/guides/language-detection
- Proposed logic: (1) user setting per chat "reply language: auto / de / en"; (2) auto = language of the last voice note via detection (de vs en; Swiss counts as de), falling back to the language of the last typed text, then the device locale; (3) store detected language on the message and send it to the agent as metadata; (4) reply voice memo uses a matching TTS voice (de-CH accent only if user chose "Swiss"); (5) text replies mirror user's language; (6) user can override with a one-tap language chip on the reply.
- Use a cheap text language ID (NLLanguageRecognizer on-device) on the transcript as the second signal; transcription language and text language agreeing = high confidence.

## Must-include checklist for orch messenger v3

**Chat list**
1. MUST Chat list as primary screen: workspace chats and ticket chats, sorted by last activity.
2. MUST Unread badges and bold preview; muted badges grey.
3. MUST Pin chats (leading swipe) and mute/archive (trailing swipe).
4. MUST Search field with pull-down; scoped to chats and messages.
5. SHOULD Filter chips: All, Unread, Needs me, Workspaces, Tickets.
6. SHOULD Drafts shown as "Draft:" in the list, persisted per chat.
7. SHOULD Archive section reachable by pull-down.
8. MUST Presence line: "working…" / "typing…" for the agent, workspace online/offline dot.
9. LATER Long-press peek preview of a chat.

**Chat room**
10. MUST Bubbles with grouping, tails on last of a group, day separators.
11. MUST Four message states: sending (clock), sent, delivered (workspace received), read/handled (accent).
12. MUST Reply/quote via swipe, with jump-to-original highlight.
13. MUST Long-press menu: Reply, Copy, Forward, Select, Delete, Info; glass popover.
14. SHOULD Reactions via emoji bar and chips; decide semantics for agent feedback.
15. MUST Jump-to-bottom button with unread count; "N new messages" divider.
16. MUST Typing/working indicator in bubble form.
17. SHOULD Pinned message(s) per chat (e.g. ticket brief).
18. SHOULD Forward message to another chat/ticket.
19. LATER Scheduled send and silent send.

**Composer and attachments**
20. MUST Growing text field, send button, mic button when empty.
21. MUST Attach sheet: Camera, Photos, Files, Location, Contact (+ orch: Ticket).
22. MUST Hold-to-record with slide-left cancel, slide-up lock, haptics.
23. MUST Draft persistence across app kill.
24. SHOULD Photo/video HD toggle and compression before upload.
25. SHOULD Share extension to send from other apps into a chosen chat.
26. SHOULD Share out via system share sheet from bubbles and viewer.

**Media and content**
27. MUST Chat info with Media / Links / Docs tabs.
28. MUST File and PDF bubbles (icon, name, size) with Quick Look.
29. MUST Location bubble: static map, tap opens Apple Maps.
30. LATER Live location with 15 min / 1 h / 8 h and stop button.
31. SHOULD Link preview cards generated sender-side or by the agent, never fetched by the phone.
32. SHOULD Full-screen media viewer with swipe, save, share.

**Voice**
33. MUST Waveform voice bubble, scrubbing, duration, listened state (accent mic).
34. MUST Playback speed 1x / 1.5x / 2x, pitch preserved.
35. MUST Transcript under every voice note (collapsed by default, expandable), with transcribing state.
36. SHOULD Auto-play next unheard voice note.
37. SHOULD Mini player when leaving the chat (background audio, Now Playing).
38. LATER Raise-to-listen / raise-to-record.
39. MUST Agent voice-memo replies (TTS) with same bubble, plus text always present.
40. SHOULD Listened state synced between phone and workspace.

**Offline**
41. MUST Local outbox with client UUID; send while offline; retry and delete on failure.
42. MUST Connection banners: "Waiting for network", "Connecting…", "Workspace offline, will deliver when back".
43. MUST Idempotent sync on reconnect using cursor; keep scroll position.
44. SHOULD Background URLSession uploads with progress ring and cancel.
45. LATER Resumable chunked uploads for large files.

**Language and speech**
46. MUST STT in German and English; Swiss German speech transcribed into Standard German text.
47. MUST Reply language setting per chat: auto / German / English; auto from detected voice language.
48. SHOULD Deepgram nova-3 de-CH as Swiss path, validated on real Swiss audio against a Swiss Whisper fine-tune before release.
49. SHOULD On-device Apple SpeechAnalyzer as offline fallback (check de-CH availability at runtime).
50. LATER Swiss-accent TTS option (Azure de-CH or ElevenLabs).

**Platform and polish**
51. MUST iOS 26 Liquid Glass: floating glass nav/tab bars, opaque content layer, no custom opaque bars.
52. MUST Dynamic Type through accessibility sizes, VoiceOver actions on bubbles, Reduce Motion and Reduce Transparency fallbacks.
53. SHOULD Haptics on send, record start/lock/cancel, reaction, pin.
54. SHOULD Spring send animation, keyboard-synced composer, reaction pop, record-button morph.
