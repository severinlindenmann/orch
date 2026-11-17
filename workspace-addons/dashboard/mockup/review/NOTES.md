# Review (15 Nov 2026)

- `review.html` is the Review page of the dashboard (`#review`, product: `web/pages/review.js` + the kit's `review.js`): heading "Review" with
  the count, the deck, and the "All cards" list beside it (hidden below 1100 px). Same demo cards as the approved draft
  (`proposals/swipe-review/`, left untouched).
- Reached from Home: "Review all" in the needs-you block (`home/home.html`). It is not in the sidebar.
- The topbar "New ticket" is an outline button here; the answer is the primary action.
- The product page also has the Waiting / Answered switch above the deck (kit `UI.reviewPage`); this static page shows the Waiting side only.
- No Decisions tab: the ticket page shows card answers under its questions ("Earlier answers"), with "What applies now" on top: `../ticket/ticket-answers.html`.
- No extra chip on a card: an answer is a plain click.
- 16 Nov (ORCH-65): cards carry the whole question text, a marked suggestion ("Suggested: Build it" on the card and under
  the button; "Suggested" on an option), a Today tile beside the options of a choice, the helper's links in the footer
  (Mockup, Issue …), pictures that fit their pane on a dark ground with a zoom button per side, and sets
  ("Home look") in the All cards list with "n of m waiting".
- No swipe (owner 16 Nov): the card does not move with the finger or mouse and does not fly away; answers are the
  buttons and the arrow keys, the answered card fades.
- 16 Nov (ORCH-110): a choice whose options have no pictures (a plain question) shows plain option rows with the whole
  title and its description: no dark frame, no empty picture box, no zoom, and the letter chip only for short ids (A, B).
- 16 Nov (ORCH-77): "Accepted for you" card under "All cards" (the Reviewer's Done-for-you tickets of today): ticket link, the why line, a Send back button that asks for a short note, or "Sent back". Hidden when nothing was accepted. It stays on a phone width (below the deck) while the All cards aside hides. Settings > General has the switch "Accept small finished work for me".
- 17 Nov (ORCH-79): Settings > General has the switch "Merge releases without my click" under "Accept small finished work for me" (off by default; only the owner turns it on). On: a release Merge card with every check green merges by itself and the card shows as answered by the release keeper.
