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

## Redraft 2 (25 Nov, lane workspace-topright-2): where do move, copy and the rest go

Owner on round 1 and 2: "we need some of the actions still like moving a ticket etc so where do we do that one" and
"still not satisfied, we need be able to use these options like move a ticket, or copy etc etc. something more like
A + C or i dont know challenge it with another idea".

### What a ticket can do today (walked on develop, sample workspace, `shots2/now-*.png`)

- Header by state: Start helper / Continue (with the Start choice behind its caret), Watch live while a helper works,
  Looks good / Send back in Check, Reopen when Done, Answer, Mark Done.
- Open chat. Properties (button on small screens; a column on wide ones).
- The "..." menu: Open in Live, eight bare lane names that move the ticket (Backlog, To do, Working, Waiting, Check,
  Done, Won't do, Superseded), Repeat…; while a helper works: Stop, Copy watch command, Copy take-over command.
- Elsewhere on the page: title and note edit in place, Add a sub-ticket, the write box, the tabs.
- Only on the list and board: Move up / Move down inside a lane, drag between lanes.
- **Not in the product today:** copy the ticket link, make a copy of a ticket, delete a ticket (Won't do is the
  closest), open the ticket's folder, print or export. The drafts add the first two (the owner asked for "copy");
  they are new and small. Open folder is not drawn: it would only work on the computer orch runs on (R4.1a). Delete
  is not drawn: orch has no delete, Won't do closes a ticket and keeps its history.

What the walk showed: the menu is bare centred words, nothing says the lane names move the ticket, Open in Live and
Repeat… sit in the same list as the lanes, and the pill says "In progress" where the lane is called "Working".

### The four options (same ticket, `topright2-*.html`, pictures in `shots2/`)

- **A (recommended), the owner's "A + C":** the bar under the title keeps Open in Live, Continue and Ticket chat and
  gets a fourth equal button "Actions". Its menu has two parts side by side, left aligned with icons: "Move to" (all
  lanes, the current one ticked) and "This ticket" (Copy link, Make a copy, Add a sub-ticket, Repeat…; Properties on
  small screens). The state pill opens the same Move to list, as a second way in. While a helper works
  (`topright2-a-working.html`): Watch live, Stop takes Continue's place, the two terminal commands sit last in the
  menu under "For developers".
- **B:** the state pill beside the number is the only way to move the ticket; the bar ends with a short "More" menu
  for Copy link, Make a copy, Add a sub-ticket, Repeat….
- **C:** no menu. An "Actions" block on top of the Properties column: a "Move to" select and the same four rows,
  always visible on a wide screen; on the phone inside the Properties sheet.
- **D (Codex, gpt-6-astra, its own idea):** "Manage ticket" beside the ticket number (Move to… as a second step,
  Copy link, Make a copy, Repeat…); Open in Live and Open chat right of the title; the paid start as a quiet
  "Continue" below them with "Uses paid helper time". Codex's own objection: ticket actions and helper actions sit in
  two places, and moving takes two picks.

`?closed` shuts the menu of a draft page, `?more` opens option B's second menu, `?sheet` shows C's phone sheet.

### What the challenge changed (Opus as IT engineer, business manager, marketing person)

Ranking A, C, B, D. Changed after it: the state pill in A now also opens Move to (B's idea folded in); "Duplicate"
became "Make a copy"; the "New" tags and the word "now" left the menu; the terminal commands moved last under "For
developers" with Properties above them; the write box's send button is outlined in these drafts so Open in Live is the
only filled button. Not taken: moving Continue to the end with its price on the button (the owner accepted the order
Live, Continue, Ticket chat in round 1). Left for the build: the Done state (Continue becomes Reopen) and the state
with the Live and Repeat add-ons off; C's phone sheet needs a close button; the pill says "In progress" where the
lane says "Working" (one word for one thing, R7.5).
