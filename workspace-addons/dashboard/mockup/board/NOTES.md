- Merged the B board with five readable scrolling columns, inline search, owners, real times, and pending changes; aligned List and New metadata. Kept the alternative.
- Shared snapshot: 3 need you; Anna and Ben own tickets; Helper is the helper. Newsletter 23 min; survey 12:26; sign 12:32; typo 12:27; question 27 min.
- Motion: retain entry, progress and status transitions; honor reduced motion. Preview stays collapsed until requested.
- Performance target: no new dependencies or external network requests; interactions below 100 ms and animation frames below 16.7 ms. Loading and empty states remain available through the Preview pill.

## Revised after the owner's comment (13 Nov)

- `new.html`: Helper choices now have different names and a short description: everyday tasks, coding, or writing.
- `new.html`: Added a small calendar with month controls and Today, Tomorrow, Next week and No date choices.
- `new.html`: There is no reason to limit a ticket to four files, so you can now add as many as you need, up to 100 MB each.
- `new.html`: Files can be picked or dropped in, added over several visits, and removed individually from a compact list; loading, empty and motion previews remain available.


## Revised after the owner's comment (13 Nov)

### board.html

- The ticket window now shows its reference quietly without a Details toggle.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

- A due with a time reads "Due 18:30" on a card, and "Late since 09:00" in the warning colour once it has passed (the ticket page Due row shows the same words).

### list.html

- Put Changes to add on its own line beneath the ticket title and removed the repeated status line so the words do not run together.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### new.html

- Showed the optional completion field plainly and hid the native file input visually while keeping the styled drop zone and keyboard access.
- The completion condition is optional; people can describe what should be true when the work is finished.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### opus-board.html

- The alternative board now shows the ticket reference plainly in its ticket window.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.


## Revised after the owner's comment (13 Nov)

Round 2 — working shared components.

### board.html
- Added the same working phone-question switch as Home to keep the sidebar consistent.
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

### list.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

### new.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Replaced the local calendar with the shared date picker; arrow keys move between days and choosing a date returns to the form.

Round 2 validation: the shared browser sweep passed all 171 loaded/loading/empty page checks and 144 dialog/viewer checks. Targeted phone, question, keyboard, calendar, full-screen and toolbar checks also passed. See `../system/COMPONENT-QA.md` for the complete inventory and results.

## Revised after the owner's comment (13 Nov)

### new.html

- Kept the shared calendar and connected its popover to the shared Escape handling; Escape closes only the calendar and leaves the New ticket window open.
- The No date button stays clickable and toggles the calendar; clicking outside closes it and returns focus to the button.
- Checked date selection, arrow keys, clearing the date, focus return, and loaded, loading and empty previews at 1280 × 800.
- Ran `node /Users/lume/orch-dev/state/ux-challenge-1113/mockup/base/scripts/qa-components.cjs 1280`: all 60 pages passed, including `board/new.html`, with no reported problems.

## Owner feedback 14 Nov (lane owner-fb-v2)
New ticket: 560 px, the box starts at 3 rows and grows, Start opens the new ticket, Save stays on the list (`../sweep/d-new-ticket.html`). Files tab: `../sweep/d-files.html`.

- A Working ticket with no news for 6 hours shows "No news since 09:20" (day first when not today) on its card and in the list, on its ticket page ("Your helper is working. No news since 09:20."), and as a quiet row on Home that is not counted as needing you. Open the ticket with `?quiet=1` to see it.
## Fix wave 15 Nov (b4)
Save without starting shows "Saving…" on the button at once and then opens the new ticket, like Start. Viewer button is "Copy local link" with the hint "Works only on this computer". Files show the title given when attached, the file name small underneath. Shared links row buttons are always visible (no hover rule).

## ORCH-14 (16 Nov): several tickets at once (epic)

### new.html

- Under the files: "＋ Make it an epic with several tickets". Each click adds a "Ticket N" box with its own text, files and Remove; the button then reads "＋ Add another ticket" and a line says the ticket becomes an epic. On Start the epic is made first, then one ticket inside it per box; one helper run goes through them in order. The epic page lists them under "Tickets in this epic"; the board card says "Epic · N of M done"; a ticket inside says "Part of the epic …".

## Revised after the owner's answer (16 Nov, ORCH-62)

### list.html

- Every ticket sits in the group of its own status; a ticket that only waits for another one has its own group "Waiting for another ticket" with "Waits for ORCH-12" under the title.
- Steps read "3/4" with a bar, on one line. No Status and no Owner column (the group says the status); a chip only for an Idle or Stuck helper, with "Nothing running for 18 min".

## ORCH-69 (owner picked A, 16 Nov)
- Board and list cards carry no Start helper or Resume button: starting a helper costs budget, so it is never the easiest click. A To do card shows its title, its line and its meta only; a paused card keeps its "Paused" line. A helper starts from the ticket page (Start helper / Resume) or from Home. New ticket keeps Start and Save.

## Phone (17 Nov, ORCH-73)

- `list.html`: up to 720 px the table gives way to grouped short rows (master `.short-group`): number and title, one fact, Answer where you are needed, else steps n/m or an Idle chip. The List/Board switch shows only on wide screens.
- `list.html`, `../home/home.html`, `../review/review.html`, `../ticket/ticket-working.html`: the phone bottom bar (master `.tabbar`) Home, Tickets, Review with the one needs-you number, More opens the side menu.

## Manager view (ORCH-189, owner approved 17 Nov)

- `list.html`: Due column (red when past, amber today) and Time · cost column (helper time and money at list price);
  quick views This week and Stuck; the Stuck pill also for an old question, no news for a day or past due.
- `../insights/insights.html`: Helper time, Cost, Tickets finished, Stuck now and a By person table on top.
- `../ticket/ticket-change.html`, `ticket-question.html`: Time · cost in Properties (the helper's first-run estimate
  beside what it took so far).
