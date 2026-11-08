# Workspace look (7 Nov)
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
