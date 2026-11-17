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

## Clear old (16 Nov 2026)

- Needs-you head: a quiet `Clear old` button (only when a question is older than a week). One click hides them with the toast "Cleared 37 old questions · Undo"; the helper sees each as dismissed. No setting, no new page.

## Work that stopped short (16 Nov 2026, ORCH-26)

- Needs-you block, `home.html?stuck=1`: two rows with two one-click buttons each, built from the existing need row, no new style.
  "The pull request passed its checks but was not merged, and no helper is working on it." has `Merge` (the person's own GitHub login, exactly the commit shown) and `Start helper` (`Nudge` when a helper sits idle on it).
  "The helper has been idle for 14 min with nothing running." has `Nudge` and `Start fresh`.
  A click answers with a toast and the row leaves. Hidden without the flag, so the shared demo count (3) stays.
- A set of review cards on one ticket (16 Nov, ORCH-65): one row with the set name (the helper's group, else the ticket), "N cards to look at", the first three proposal pictures with their card titles, and "Look at all N", which opens Review at the first card (`#card-set`).

## Factory start question (16 Nov 2026, ORCH-60)

- `home.html?factory=1`: a Factory start question is a few lines, as the owner accepted on 16 Nov: "Factory proposal",
  `Start "<title>"?`, the one-line goal, "Runs about … · needs you for about … · up to … of helper time", who asked and
  "Read the whole proposal" (the proposal on the Factory page). Buttons Not now, Change it, Start: same weight, Start
  last, Change it answers Edit. Never the whole proposal text on Home. Lower in the list: one row with "Read proposal".

## What helpers need on Home (17 Nov 2026, ORCH-45; drawn and chosen on ORCH-43)

- Built in the product as drawn. `home.html?login=soon`: a login, connection or key that runs out within three days is
  one row in Needs you (after the first question) and counts in "N things need you": "The <name> ends on <day> at
  <time>." and "After that helpers stop on N tickets: <links>". `?login=stopped`: one that stopped working is the red
  banner at the top ("The <name> stopped working", or "cannot be reached" for a connection), "Helpers stopped on N
  tickets and start no new work: <links>" ("and start no new work" only for the main helper). `?login=several`: one
  banner "N things stopped working", the names, `See what to fix` (Settings › Helper, the list). Each thing that
  stopped counts in the title ("N things need you", manager 17 Nov), not in the Needs you badge. Nothing shows when all works or nothing was checked yet; a shared copy shows none of it.
- The `Renew` button is the renew step (ORCH-46). Until it is in the product, the same place shows `Check again`
  (word list #8; it runs every check once more and a toast says the new state), and `Try again` for a connection that
  cannot be reached; both outlined (one filled button per view).
