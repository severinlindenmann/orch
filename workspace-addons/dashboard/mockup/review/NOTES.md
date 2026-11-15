# Review (15 Nov 2026)

- `review.html` is the Review page of the dashboard (`#review`, product: `web/pages/review.js` + the kit's `review.js`): heading "Review" with
  the count, the deck, and the "All cards" list beside it (hidden below 1100 px). Same demo cards as the approved draft
  (`proposals/swipe-review/`, left untouched).
- Reached from Home: "Review all" in the needs-you block (`home/home.html`). It is not in the sidebar.
- The topbar "New ticket" is an outline button here; the decision is the primary action.
- The product page also has the Waiting / Answered switch above the deck (kit `UI.reviewPage`); this static page shows the Waiting side only.
- The ticket page has a Decisions tab only when the ticket has decisions: `../ticket/ticket-decisions.html`.
