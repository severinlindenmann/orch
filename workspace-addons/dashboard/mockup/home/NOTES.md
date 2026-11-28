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
- Stuck tickets (ORCH-426), same `?stuck=1`: all work that stopped is one block at the very top of Needs you, each row marked with the Helpers list pill (Stuck; Idle for a helper idle under 20 min): a helper waiting on your OK on its screen, a step whose checks keep failing (Open, Nudge, Start fresh), the Reviewer not sure (Open), a pull request left open, an idle helper. Shown whether or not the ticket needs a person's review. The title and the Needs you pill count these rows ("4 stuck tickets · 1 idle helper" in the subtitle), and so do the top bar, Menu, the Focus bar and the wall: one number everywhere (ORCH-705); a ticket the Reviewer was not sure about is that row, not also a result to check. The same stuck rows reach a paired phone as one text each while the relay is on. `?shots=1` hides the Preview pill for pictures.
  "The pull request passed its checks but was not merged, and no helper is working on it." has `Merge` (the person's own GitHub login, exactly the commit shown) and `Start helper` (`Nudge` when a helper sits idle on it).
  "The helper has been idle for 14 min with nothing running." has `Nudge` and `Start fresh`.
  A click answers with a toast and the row leaves. Hidden without the flag, so the shared demo count (3) stays.
- A set of review cards on one ticket (16 Nov, ORCH-65): one row with the set name (the helper's group, else the ticket), "N cards to look at", the first three proposal pictures with their card titles, and "Look at all N", which opens Review at the first card (`#card-set`).

## Factory start question (16 Nov 2026, ORCH-60)

- `home.html?factory=1`: a Factory start question is a few lines, as the owner accepted on 16 Nov: "Factory proposal",
  `Start "<title>"?`, the one-line goal, "Runs about … · needs you for about … · up to … of helper time", who asked and
  "Read proposal" (the proposal on the Factory page; the same words as there, ORCH-479). Buttons Not now, Change it, Start: same weight, Start
  last, Change it answers Edit. Never the whole proposal text on Home. Lower in the list: one row with "Read proposal".

## Factory draft ready (18 Nov 2026, ORCH-479)

- `home.html?draft=1`: a Factory draft that is ready for Plan the run waits on Home as on the Factory page: "Factory
  draft", its title, "Read the draft, then plan the run or ask for changes.", "Helper wrote it … · Read draft",
  and Plan the run, Ask for changes (same weight; Ask for changes opens a box with Send and Cancel). It counts in
  "N things need you" ("1 draft to read"). Review shows it as a card: Plan the run, Ask for changes (the comment
  sheet), link Read draft. Factory, Home and Review then show the same waiting items and the same number. Hidden
  without the flag, so the shared demo count (3) stays.

## What helpers need on Home (17 Nov 2026, ORCH-45; drawn and chosen on ORCH-43)

- Built in the product as drawn. `home.html?login=soon`: a login, connection or key that runs out within three days is
  one row in Needs you (after the first question) and counts in "N things need you": "The <name> ends on <day> at
  <time>." and "After that helpers stop on N tickets: <links>". `?login=stopped`: one that stopped working is the red
  banner at the top ("The <name> stopped working", or "cannot be reached" for a connection), "Helpers stopped on N
  tickets and start no new work: <links>" ("and start no new work" only for the main helper). `?login=several`: one
  banner "N things stopped working", the names, `See what to fix` (Settings › Helper, the list). Each thing that
  stopped counts in the title ("N things need you", manager 17 Nov), not in the Needs you badge. Nothing shows when all works or nothing was checked yet; a shared copy shows none of it.
- `?login=approve` (#1549): a workspace check file that is new or changed waits for the person: the red banner says
  "The <name> waits for you to approve it" and its one button is `Approve`. The window shows what the check runs in
  full (with Copy) and Approve sends the CLI's own `orch checks approve <name> --hash <h>` with the content the page
  showed; `?renew=approve&step=approve-done` is the success line, `?renew=approve&step=approve-changed` the file that
  changed after the page showed it (nothing approved, the rows are read again). No terminal command on the row.
- The `Renew` button is the renew step (ORCH-46). Until it is in the product, the same place shows `Check again`
  (word list #8; it runs every check once more and a toast says the new state), and `Try again` for a connection that
  cannot be reached; both outlined (one filled button per view).

## Why no helper starts (17 Nov 2026, ORCH-266)

- `home.html?line`: one amber banner at the top while tickets wait in line and orch names a reason, as one short
  line and never the list of waiting tickets (ORCH-1100, owner picked design B on 20 Nov 2026): "Helper limit
  reached." with `Allow more helpers` (Settings › Helper), "Computer too busy to start more work.", "Usage limit
  reached." or "Disk almost full."; any other reason is shown as orch words it. Nothing shows for the short pause
  between two starts, when nothing waits, or in a shared copy.

- ORCH-1741 (owner 23 Nov, "39 things wait on you"): a ticket in Review whose pull request waits in the merge queue (or that a helper is repairing for the queue) is no result row and no count: one quiet line "N in the merge queue, nothing to do" under the list. It comes back as a result to check when the queue gives up on the pull request. A ticket never shows two rows: an open question or "passed its checks but was not merged" takes the place of its result row; the Check card also says why the Reviewer was not sure. Merged work with nothing open and a security review with an ok close by themselves.

## Polish pass (25 Nov 2026, ORCH-2086)

- The product now matches this page for the first question: answer tiles share the row (each at most 400 px, so 1920
  is not stretched) with "Suggested" beside the answer, no extra "Needs you · Choose an answer" line under the
  Needs you badge, and the quiet button under the tiles sits on the left edge at phone width.
- Finished: the title, result and time sit close together (8 px), as drawn; links keep their 44 px touch area
  without stretching the line. No change to this page's markup was needed.

## 26 Nov 2026 (ORCH-2169, RP8 B, RP4)

- Menu labels follow the owner's naming: "Relay" (was Contacts) and "Publish" (was Shared / Shared links).
- Home needs area: one quiet notice line "New contact: Marketing, connected by your admin. Their messages are on the
  Relay page." with source "Relay" and a quiet "OK" button (same row pattern as `need-notice`). Added because RP8 B
  lets a contact the admin connected show up without a click. Relay task questions use the RP4 words
  ("Allow this task", "Always allow tasks from <name>", "Decline"); see `relay/relay.html`.

## 28 Nov 2026 (ORCH-2431, parked tickets)

- The first question has a quiet "Not now" beside "Write your own": it parks the ticket (a dialog asks until when:
  tomorrow, next Monday, in a week, a day and time, or "When I bring it back"). A parked ticket, and every ticket in
  Backlog, gives no row on Home or Review and is not in the Needs you number; its question is kept.
- Needs area: one quiet line "2 parked, they ask nothing until they come back" with Show (same row pattern as the
  sync notes line). Show lists each parked ticket with its reason ("Until Mon 09:00", "Until you bring it back",
  "In Backlog") and one "Bring back" button. On Review the question card has the same quiet "Not now" in its foot.

## Home after the walk of 28 Nov (O-01 D, CX-01, W-017, W-054 A)

- `home.html`: blocked work first ("Blocked now": one line and one action per row: a sign-in that stopped, a service work depends on, a helper that could not start, a merge that waits, a helper that waits for an OK). Questions and results are one line that opens Review ("8 questions and 18 results wait in Review"); no question or result card on Home. The numbers are one row. Finished is the five newest titles with one short result each. No "What changed", "In progress" or "Not started" card.
- Helpers (CX-01): a finished ticket with nothing running reads "Finished" with Open ticket; one whose process still runs says "Ticket finished; helper still running" and keeps Stop; a run that cannot be read says "Not known".
- Preview controls: Loaded, Loading, Day one (W-017: "Write your first ticket", one filled New ticket), Blocked, Nothing blocked. `?paused` shows the calm line of a paused automation, `?line` the full start line, `?login=soon` a login that runs out soon (quiet row at the foot).
- The rows use the product's own page sheet (`pages/home.css`), linked like `chat.html` links its page sheet.
