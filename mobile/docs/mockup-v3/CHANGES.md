# Workspace look (7 Nov)
- Workspace badges show the picked icon and colour (Pilatus wallet/amber, Home house/teal) in the chats list, workspace screen and Conversation info; Rigi has no pick: letter + Automatic colour. Styles and the override live in `look.css` / `look.js`.

# Info tabs (TestFlight 10 + 14, 7 Nov)
- Conversation info: the four tabs sit in one row with one-line labels (Photos, Files, References, Artifacts); the count is a small badge, shown only when there is something. With large text the row scrolls sideways instead of wrapping.
- Removed the "Voice & reply language" row from Conversation info: Settings > Voice keeps Swiss German, and replies follow the language the person spoke.

# Round 5
- Grouped workspace topics by Working / Waiting / Review / Backlog with Done collapsed; renamed Links to References with URL, ticket, artifact and plain file-path rows. Added static `statuses-references.html` review screens.
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
