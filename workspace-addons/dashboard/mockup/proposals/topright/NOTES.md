# Ticket page: the buttons top right (draft, lane workspace-topright)

Owner comment (Fable 1 W2): the buttons top right are not aligned, the "..." hides things, and Open chat comes
before Focus. Four static screens on the master design system, same ticket, only the header differs:

- `topright-now.html`: as the product draws it today (`pages/ticket.js` ticketStrip): a cost line above Continue and
  its caret, Open chat with an icon, Properties (small screens), the "..." menu that holds Open in Focus.
- `topright-a.html` (recommended): equal buttons beside the title, Focus first, then Continue, Chat, Properties
  (small screens only). One row at 1440, a 2 x 2 grid at 390. No "..." (its rare items move into Properties). The
  cost is a sentence under the title.
- `topright-b.html`: the same buttons as one bar under the title, on the title's left edge.
- `topright-c.html`: two buttons only: Open in Focus and an "Actions" menu with words.

While a helper runs the first button reads "Watch live"; Continue is then Stop. Drafts only: nothing here is built.
Pictures: `shots/` (390 and 1440).

What the challenge changed (Opus, as IT engineer, business manager, marketing person): the recommendation moved from
A to B (B puts key, title, state and buttons on one left edge; A's buttons float beside the key line); "Chat" became
"Ticket chat" (it clashed with Chat in the top bar); B's bar now ends with the content column; C's phone layout was
broken (title squeezed) and is fixed. Left for the build: on the phone, Focus alone on a full row with the other
three below it; show the moved "..." items inside Properties.
