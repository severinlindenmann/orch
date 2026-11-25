# New ticket page: three drafts (25 Nov, not the product yet)

Owner: "start now should also be next to it, maybe challenge this full new ticket page again, like you have more space
to use and can make it better." Static screens on the master design system; nothing here is built. The product page
is `web/pages/newticket.js`; its mockup stays `board/new.html` until the owner accepts a draft.

| File | What |
|---|---|
| `new-ticket-a.html` | **A (recommended):** two columns. Left: the request, its files, Save ticket and Start now side by side, each with its own line; "Show me the plan first" under Start now. Right: helper list, then the optional settings. Phone: the helper is one row above the buttons. |
| `new-ticket-a-parts.html` | A with four files and three parts, to show the busy state. |
| `new-ticket-b.html` | **B:** one wider column. Helper and due date sit beside the two buttons in the bar of the request box. |
| `new-ticket-c.html` | **C (not recommended):** the form left, "what happens next" boxes with one button each right. |

## What we saw on the real page (develop, 25 Nov, seeded throw-away workspace)
- The card is 640 px wide on a 1440 px screen; the page is 1031 px tall, so "Done when" and Cancel are below the fold.
- Save ticket and Start now are stacked beside the text box and make the box narrower.
- Two grey lines explain the buttons; "Show me the plan first" belongs to Start now but sits six rows lower.
- An added file shows above the "Optional" line, away from the place where files are added.
- "Split into parts" makes boxes named "Ticket 1": two words for one thing.
- Helper is a plain list box with "(default)"; nothing says what a helper is good at.
- Open the page: under 1 s. Save to the new ticket's page: about 1.5 s (the saving moment).

## What the challenge changed
Opus (as IT engineer, business manager, marketing person) preferred A; Codex (pictures only) preferred B. Both asked
for the same fixes, now in A and B: each button has its own line right under it, the cost sits under Start now, the
plan choice moved under Start now, the request keeps its label, files and parts became real buttons with a drop hint,
Cancel comes last on the phone, the phone names the helper before the buttons, and the busy state is drawn.
Not taken: renaming "Human review needed" and the helper names (wording changes, outside this draft).

## Left for the build
- The layout is carried by inline `style` attributes here; the build adds it to the master with a gallery entry (R6.2).
- States not drawn: no helper set up, one helper (plain line, no list), six helpers, loading, error, a refused file.
- Keep the button row in view when many files or parts are added.
- The UX checklist was not run in full; pictures were looked at for 1440x900 and 390x844 only (no 1280, 1920, 320).
