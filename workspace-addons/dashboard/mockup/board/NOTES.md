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
Save ticket (then "Save without starting") shows "Saving…" on the button at once and then opens the new ticket, like Start. Viewer button is "Copy link" (no hint; ORCH-907). Files show the title given when attached, the file name small underneath. Shared links row buttons are always visible (no hover rule).

## ORCH-14 (16 Nov): several tickets at once (epic)

### new.html

- Under the files: "＋ Split into parts". Each click adds a "Ticket N" box with its own text, files and Remove; the button then reads "＋ Add another part" and a line says the ticket becomes an epic. On Start the epic is made first, then one ticket inside it per box; one helper run goes through them in order. The epic page lists them under "Parts of this ticket"; the board card says "Epic · N of M done"; a ticket inside says "Part of …".

## ORCH-156 (17 Nov): existing tickets under an epic, no empty epic box, order inside a lane

### new.html
- An empty "Ticket N" box stops the save with "Ticket N is empty. Write what needs doing in it, or remove it." (it used to drop out silently, and an epic with only empty boxes became a plain ticket). Nothing is made until it is filled or removed.

### Ticket page (Properties, Add a ticket)
- Properties has "Part of" (it replaces the "Sub-ticket of" line): a select with "Not part of another ticket" or any open ticket, epics first (marked "(epic)"), never the ticket itself or one inside it. The header line "Part of …" follows it.
- An epic's "+ Add a ticket" window keeps the title box and adds "Or pick a ticket that already exists"; picking one hides the title box, Add moves that ticket in.

### board.html
- Inside a lane the person drags a card above another to put them in order (a drop on empty space puts it last); the order is kept per lane. Cards that came into the lane since stay on top. The card's ⋯ menu adds "Move up" and "Move down" under the lanes (by keyboard, no dragging), only where the card can move.

## Revised after the owner's answer (16 Nov, ORCH-62)

### list.html

- Every ticket sits in the group of its own status; a ticket that only waits for another one has its own group "Waiting for another ticket" with "Waits for ORCH-12" under the title.
- Steps read "3/4" with a bar, on one line. No Status and no Owner column (the group says the status); a chip only for an Idle or Stuck helper, with "Nothing running for 18 min".

## ORCH-69 (owner picked A, 16 Nov)
- Board and list cards carry no Start helper or Resume button: starting a helper costs budget, so it is never the easiest click. A To do card shows its title, its line and its meta only; a paused card keeps its "Paused" line. A helper starts from the ticket page (Start helper / Resume) or from Home. New ticket keeps Start and Save.

## Phone (17 Nov, ORCH-73)

- `list.html`: up to 720 px the table gives way to grouped short rows (master `.short-group`): number and title, one fact, Answer where you are needed, else steps n/m or an Idle chip. The List/Board switch shows only on wide screens.
- `list.html`, `../home/home.html`, `../review/review.html`, `../ticket/ticket-working.html`: the phone bottom bar (master `.tabbar`) Home, Tickets, Review with the one needs-you number, More opens the side menu.

## ORCH-185: no lost input or silent cuts (17 Nov)

- New ticket: text typed and then closed with Cancel, Esc or Back is kept and comes back the next time with "Your unsent text from before is back. Discard".
- New ticket: an added picture shows a small thumbnail in its file row (kit `.thumbnail`).
- Date picker (kit): today is marked with a ring and `aria-current="date"`; it opens as a small 340 px popup, not the 480 px dialog width.
- `new.html` and `new.js` show the draft line with Discard and the picture thumbnail.
- Board: a sub-ticket that has its own card in the same column is no longer listed again inside its parent's card; sub-tickets in other columns still are.

## Releases (ORCH-37, owner picked "a release is a parent ticket", 17 Nov)

- `list.html`: a release is its own group above the status groups ("Release 26 · 1 of 4 done", Open release), with its epic, the epic's tickets and its other tickets as one tree; each row carries its status chip. Finished releases start folded.
- `../ticket/ticket-working.html`: Properties has a Release switch under Part of; Part of offers releases first, marked "(release)".
- ORCH-906 (owner picked it, 20 Nov): an epic or a release carries a small "Epic" / "Release" chip (kit `.chip`, like the status chip) after its title in the list row and on a board card without sub-tickets, beside the ticket number in the ticket page header (in the line above the title while a helper runs), and first in the phone row's fact line ("Epic · 4 min ago") (a card with sub-tickets already says "Epic · n of m done"). A release with no tickets yet reads "Release 27 · No tickets yet", not "0 of 0 done". `orch ticket list` puts the kind first in the brackets; `orch ticket show` has an "Epic:" line as it has a "Release:" line.
## Triage button (ORCH-151, 17 Nov)

- `board.html`, `list.html`: a Triage button beside the page title. It opens a small menu that says what happens and lists the lanes with their counts as tick boxes (Backlog to Check ticked, Done, Won't do and Superseded not); Start triage opens a dated Triage ticket and starts one
  helper that goes through every open ticket (brings it up to date, groups related ones, closes what is no longer
  needed). Owner (17 Nov): not only open tickets, also backlog, running and other lanes, by choice. Shown only while tickets exist, never on a shared copy; a second click while a Triage ticket is open
  says so in a notice.
- Owner 17 Nov (more compact, draft B picked): count and Start triage on one line, the lanes as tick boxes in two columns, one short line under (master `.menu-pop-wide`).
- Owner 18 Nov (ORCH-1096): Start triage turns into the kit's busy button (spinner + "Starting…") and the menu stays open while orch opens the ticket (about a second); then the new Triage ticket opens at once and the helper starts there ("Getting started…"), as with New ticket. No more grey button and a 30-second wait.


## Manager view (ORCH-189, owner approved 17 Nov)

- `list.html`: Due column (red when past, amber today) and Time · cost column (helper time and money at list price);
  quick views This week and Stuck; the Stuck pill also for an old question, no news for a day or past due.
- `../insights/insights.html`: Helper time, Cost, Tickets finished, Stuck now and a By person table on top.
- `../ticket/ticket-change.html`, `ticket-question.html`: Time · cost in Properties (the helper's first-run estimate
  beside what it took so far).
- ORCH-297: a ticket nobody started shows "Before Start: about 20-40 min · $2.00-$4.00" in the same Time · cost
  line (the middle half of this workspace's finished tickets; none until 3 are finished). Insights gets one bar,
  "This week against the budget" (`insights.html`, `#week`), read from the weekly limit set in Usage; no bar when
  Usage has no weekly limit or reading.
## ORCH-240 (17 Nov, owner's words)

- The filter "Group" is now "Part of", with "Any ticket" for no choice; the list column "Steps" is "Tasks".
- The to-do lines of a ticket are "tasks" everywhere ("+ Add task", "2 of 5 tasks", "Added a task"); the
  sub-tickets of a plain ticket are headed "Sub-tickets".
- The board fits at 1440: lanes shrink to 210 px, empty lanes to 76 px, empty Won't do and Superseded lanes
  are hidden until they hold a card. A sub-ticket with its own card is not listed again in its parent's card.
- On the phone the List/Board switch shows too; the Board is lanes side by side that you swipe.

## Prepare words in the list (ORCH-742, 19 Nov)

A saved ticket in Backlog says quietly where Prepare stands after its title: "· Preparing…" while the helper reads the
links, "· Prepared" once it filled the ticket (described by the helper, not checked). ORCH-20 and ORCH-21 show it; they
open the Prepare states of the ticket page (`../ticket/ticket-prepared.html`, `../ticket/ticket-preparing.html`).
- Big workspaces (ORCH-523): every group and lane draws its first 50 rows (lanes 30) and ends with a quiet
  "Loading more…" line; the next rows come when it scrolls into view. Done counts every finished ticket and
  brings older ones from the server a page at a time. A typed search runs on the server over every ticket.

## ORCH-576 (owner picked draft C, approved 18 Nov): status rows

- `board.html` now draws the board as status rows (`board-rows.js` with the data in `board-rows-data.js`, kit classes
  only): every status is one row of small tiles, the most urgent first: Needs you, Check, Working, Waiting, To do,
  Backlog, Done, Won't do. A row shows two lines of tiles, then "Show N more"; Done and Won't do start folded.
- A tile is the title (2 lines, ticket key in front) and one line: tasks ("2/5 tasks"), ONE signal, "Part of: <title>",
  one add-on icon, the ⋯ menu.
- The signal, most important first: Answer, Test results, late date, what the helper says (quiet, stuck), "Replaced by",
  "Finished today", "Waits for", "Until 21:00", Paused, the parts bar.
- An Epic or Release has a tag in front and a parts bar "1/3 done" instead of the tasks; the bar opens the list of its
  parts. A part says "Part of: <title>"; one click shows "Parts of ..." with a scope bar and "Back to all tickets".
  "Waits for" and "Replaced by" show the two tickets side by side the same way.
- The add-on icon is the most important add-on fact (red failed, blue running, green fine); a number says how many;
  a click opens all facts. One icon per tile, none when no add-on has anything to say.
- Moving: drag a tile onto a row (the row says "Move to <row>"), or ⋯ > Move to, Move up, Move down. Waiting asks
  "Wait until when?". Every move shows a toast with Undo; tiles glide to their new place (not with reduced motion).
- Phone: one column of tiles, the ⋯ stays visible, a strip of row names at the top jumps to a row.

### new.html (ORCH-1852)
- Order: title, "One sentence is enough. Everything below the buttons is optional.", then the request and its buttons side by side (stacked, buttons right under the text, on a phone): What needs doing? beside `[Save ticket]` and, with a helper, `[Start now]` under it. One or two lines under them say what the buttons do. Then "Optional": files, Split into parts, Helper, Due date, Show me the plan first, Human review needed, Done when, and `[Cancel]` at the end. Nothing is hidden behind a toggle.
- Save ticket is the filled button and the default for Enter with Cmd or Ctrl. With a helper: "Save ticket puts it in Tickets. Your helper may prepare it with a short plan; no work starts." (prepare on save off: "… as you wrote it. Nothing starts.") and "Start now has your helper begin the work at once. This uses its time and may cost money." Start now is outlined, never the default.
- Preview pill "No helper" (`?helper=none`): no Start now, no Helper row, and "Save ticket puts it in Tickets. No helper is set up yet, so nothing is prepared or started now. Set up a helper".

## Tickets page polish (ORCH-2091)

- `list.html`: the toolbar is two steady rows at every width: List/Board/Calendar, Person and search on the first,
  the view chips (All … Done this week) on their own row under it; the table starts one gap below.
- An empty workspace shows only the master empty state (one sentence, one New ticket button), no toolbar.
