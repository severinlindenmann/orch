- Kept the A priority layout; added question context, survey thumbnail, explicit Changes to add action, and readable progress.
- Shared snapshot: 3 need you; Anna and Ben own tickets; Helper is the helper. Newsletter 23 min; survey 12:26; sign 12:32; typo 12:27; question 27 min.
- Motion: retain entry, progress and status transitions; honor reduced motion. Preview stays collapsed until requested.
- Performance target: no new dependencies or external network requests; interactions below 100 ms and animation frames below 16.7 ms. Loading and empty states remain available through the Preview pill.


## Revised after the owner's comment (13 Nov)

### home.html

- Reviewed the page for disclosure links and crowded text; the existing plain sections and shared layout remain in place.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### opus-home.html

- Removed the three Details disclosures and their repeated ticket references from the needs-you rows.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.


## Revised after the owner's comment (13 Nov)

Round 2 — working shared components.

### home.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Questions now share recommended choices, a checked written answer, an answered state and Undo; phone and desktop show the same reply.

Round 2 validation: the shared browser sweep passed all 171 loaded/loading/empty page checks and 144 dialog/viewer checks. Targeted phone, question, keyboard, calendar, full-screen and toolbar checks also passed. See `../system/COMPONENT-QA.md` for the complete inventory and results.

## Owner feedback 14 Nov (lane owner-fb-v2)
Home: the question is body text; answering moves the card out, the next one in, the badge counts down and a toast says "Answered · Undo" (`../sweep/d-home-answer.html`). "What changed" (from completion notes) sits under the columns and replaces the Notes page (`../proposals/fb23-home-what-changed.html`).

## Review stack (15 Nov 2026)

- Needs-you block: "Review all" button (primary) opens `../review/review.html`. Its number is the same set of questions and results Home already counts; the Home total is unchanged.
