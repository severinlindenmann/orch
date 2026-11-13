# 12 Nov phone UX, batch 4
- Info: one "Shared" list; filters (Photos, Files, Links, Previews) only when they have content and only when there are two or more, zero counts hidden, "Progress · 3 of 4 done" row; no "N tasks · N references"; phone-local workspace name.
- Result viewer: subtitle "PDF · 3 pages · 12:38" (time as the app prints it), version behind "Details", no status chip; PDF edge to edge on dark with page shadows and page count; share icon next to close; action bar on the composer band.
- Location: centred spinner with "Finding your location…"; on denial "Location is off for orch" + Open Settings + Try again.
- Voice: real length counting down while playing; same filled play button for sent and received; failed audio shows a retry button; received audio has an adjustable VoiceOver scrubber; speed button kept.
- Add sheet: "Add to chat" (sentence case), close button only (no grabber), Camera hidden when there is none.
- Review fixes: info and viewer changes now live in round3b.js / visual-challenge.js (the screens that actually render); dead edits in app.js / flows.js removed. Share shown for links and web pages too. Jump flags (No camera, Location off) are no longer saved and reset on navigation.
- Mockup jumps: Voice › "Audio not available" (shows "Audio not available" with a retry button), Media › "No camera", Media › "Location off".

- Workspace badges show the picked icon and colour (Pilatus wallet/amber, Home house/teal) in the chats list, workspace screen and Conversation info; Rigi has no pick: letter + Automatic colour. Styles and the override live in `look.css` / `look.js`.

# Info tabs (TestFlight 10 + 14, 7 Nov)
- Conversation info: the four tabs sit in one row with one-line labels (Photos, Files, References, Artifacts); the count is a small badge, shown only when there is something. With large text the row scrolls sideways instead of wrapping.
- Removed the "Voice & reply language" row from Conversation info: Settings > Voice keeps Swiss German, and replies follow the language the person spoke.

# Round 5
- Grouped workspace topics by Working / Waiting / Review / Backlog with Done collapsed; renamed Links to References with URL, ticket, artifact and plain file-path rows. Added static `statuses-references.html` review screens.
- Workspace screen shows Done only once (owner 2A): the "Done (n)" toggle with the finished chats directly under it, no second "Done" header (and none for Stopped / Didn't work; the row chip says which).
- Words (owner 6A): groups and chips read Needs you / Working / Ready for review / Not started / Done (n), in that order; starting chip "Getting started…". "Waiting on you", "Waiting for your answer", "Check this", "Backlog" and "Review" are gone from the phone.
- Wording (owner 5A/10A): "Needs you" replaces "Waiting on you" / "Waiting for your answer" (filter chip, status chip, question label); chat list count reads "1 needs you" / "2 need you".
- Removed all bottom-tab rendering, styles, badges and reserved space; Chats is the only root.
- Added a matching 44 pt Settings gear at top-left; Settings pushes and Back returns to Chats.
- Removed asleep banners; headers and workspace rows share five-minute online and dated last-seen presence.
- Kept composer notes; relay receipt shows one check while asleep and two after computer delivery.
- Rebuilt Conversation info with 16 pt insets, centered profile, separate Summary/language groups and spaced media control.
- Applied shared grouped spacing and fixed page targeting during consecutive navigation pushes.
- Verified all 39 review entries at 393/375 px in Default/L/XL (234 checks): no overflow, blank screens or runtime errors; focused interactions passed.
- Round 5b: replaced Chats row presence text with a 10 pt avatar dot and 2 pt row-colour ring, shared with the workspace picker; compact rows checked at 393/375 px.

# Archive (lane AR, 7 Nov)
- New `archive.html`: swipe left on a chat = [Delete][Archive] with Undo toast, plain Delete confirmation (phone copy only), Archived list (move back by swipe, button or menu), Settings > Chats auto-archive 3/7/14/30 days. Phone-local, no contract change.
- New `mobile-mode.html`: the Mobile mode banner in its three states (on, can't reach, muted).

## Owner TestFlight round 1
- Kept Settings > Preferences > Voice wired to the existing Voice screen.
- Conversation info now has single-line Photos, Files, Links and Artifacts tabs with small count badges and horizontal scrolling at larger text sizes. Removed its Voice & reply language row.
- The + sheet contains only Camera, Photos, File and Location in one compact row. Location preview now has a secondary Open in Maps button above Share current location; chat location cards retain Open in Maps.
- Extended the header surface through the status bar / Dynamic Island area and added top breathing room. The composer floats with an 8 px inset and 26 px corners at the bottom of the chat, above the native keyboard when opened on a phone.
- Standardized app CSS radii: small 8, medium 14, large 22, extra-large 26, pill 999 px, and avatars at 30%. Cards/inputs use medium, bubbles large, sheets extra-large top corners; inset segmented controls subtract their padding from the outer radius. Device-frame and illustration geometry is unchanged.
- Validation: opened index.html directly with a headless browser; Voice navigation, Default/L/XL tabs at 375/393 px, share/location actions and header/composer geometry passed with no JavaScript errors. Native keyboard appearance still requires an on-device check.

## 11 Nov visual challenge

Added Chats Groups, open / sent / read-only group rooms and Done groups. Redrew PIL-12 info to the shipped layout, with collapsible agent / job Results, one dated label per card, fitted previews, counted text tabs and right-aligned numeric cells. Replaced the publishing question demo with a Result artifact and Accept / Ask for changes bar; finished work without a question keeps Ready for review and no bar. Standardized tasks and References. All new states have right-panel jumps and connected in-phone navigation; existing question kinds remain available.

11 Nov: helper wording

12 Nov phone UX, batch 2: one onboarding screen (Scan QR code, Paste link, Get an invitation steps, Try a demo); Add workspace sheet says Join this workspace? with Connection details, one Add button, Use a different link / Use a new invitation; Settings shows the real connection state and a short version line; workspace Notifications row (On / Muted until …) with 1 hour, Until tomorrow, Until I turn it on; Voice caption as section footer and budget labelled USD; scanner explains denied camera.

12 Nov phone UX, batch 2 review fixes: Add this workspace? (one verb, Add); expired invitation says create a new one in orch on your computer; Use a different link returns to the start screen during onboarding; Try a demo marked debug only; check-connection toast says Connected; Connection row sits under Your workspaces with no Details sheet; Voice is one block (Voice replies menu row, I speak Swiss German, footer) plus one Voice budget block (Monthly limit (USD)); mute ends read 8:00 / tomorrow 8:00 / weekday / date; archive footer "Finished chats move to Archived after a while. A new message brings them back."
12 Nov phone UX, batch 1: chats list. Removed the summary strip and its NEW pill; a busy workspace row says "Working…". Pinned Needs your OK shows at most 3 (each with its workspace avatar and name), then "See all (n)" opens the filter. Titles are one line (two at XL text). Unread / Needs your OK filters also apply to groups. "Earlier" link is now a "Finished groups" row with a count. Avatars no longer use the status colours (amber, teal, green). Workspace screen: Chat card in the same margins with one status line; "Done" is a plain disclosure row with a count.

12 Nov phone UX, batch 1 review: an unread reply now shows instead of "Working…" on a workspace row and on the Chat card; the Chat card shows the last message or "X is working…" like the app. "Working…" counts only started topics with status Working. Groups follow the Unread / Needs your OK filters. "Finished groups" shows only when there are finished groups (helper-chat days stay under each chat's "Earlier").
