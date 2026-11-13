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
