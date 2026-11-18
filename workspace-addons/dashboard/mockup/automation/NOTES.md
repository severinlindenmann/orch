- Aligned shell counts, helper naming, headers and shared preview controls.
- Shared snapshot: 3 need you; Anna and Ben own tickets; Helper is the helper. Newsletter 23 min; survey 12:26; sign 12:32; typo 12:27; question 27 min.
- Motion: retain entry, progress and status transitions; honor reduced motion. Preview stays collapsed until requested.
- Performance target: no new dependencies or external network requests; interactions below 100 ms and animation frames below 16.7 ms. Loading and empty states remain available through the Preview pill.

## Revised after the owner's comment (13 Nov)

- automation-edit.html: How often now has one full row of choices: Every day, Every week, Every month and Custom, with Every week selected initially.
- automation-edit.html: Only relevant fields appear below, with labels on the left, selectable weekday chips, a compact day-of-month select and a matching time field.
- automation-edit.html: A live plain summary starts with “Runs every Monday at 08:00”; Custom allows a chosen number of days between runs, and shorter months explain when the last day is used.
- automation-edit.html: Checked all four choices, multiple weekdays, loading, empty and the shared Preview pill at 1280 and 1920 px; kept the shared shell, demo ticket data and motion.


## Revised after the owner's comment (13 Nov)

### automation-edit.html

- Reviewed the page for disclosure links and crowded text; the existing plain sections and shared layout remain in place.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### automation.html

- Reviewed the page for disclosure links and crowded text; the existing plain sections and shared layout remain in place.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.


## Revised after the owner's comment (13 Nov)

Round 2 — working shared components.

### automation-edit.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

### automation.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

Round 2 validation: the shared browser sweep passed all 171 loaded/loading/empty page checks and 144 dialog/viewer checks. Targeted phone, question, keyboard, calendar, full-screen and toolbar checks also passed. See `../system/COMPONENT-QA.md` for the complete inventory and results.

- Save repeat (e2e 15 Nov): the window closes at once; the list shows the repeat as "<ticket> · Saving…" until it is stored (try Save in automation-edit.html).
- Bug hunt 17 Nov (ORCH-231): the ticket picker shows the ticket number and "· already repeats"; choosing such a ticket shows "This ticket already repeats … Saving replaces that plan." and Save reads "Replace repeat". Editing a repeat: Delete repeat sits at the left, apart from Save, and asks first in the window ("Delete this repeat? … Keep it / Delete repeat"). Save and Delete close the window at once; the ticket's own row shows "<number> · <title> · Saving…" with the new plan, or "· Removing…", until the list has the change.

## Repeating and Once in two compact tables (ORCH-537, 18 Nov)

- automation.html: the one table is split into "Repeating" (plan, next time, last time, switch) and "Once" (ticket, starts, Start now); one-time rows lose the "Once" / "Not yet" / "One-time wake-up" words they repeated.
- Both tables use the compact table rows (40 px, the quiet line beside the name); a table shows five rows and the rest behind "Show N more".
- Second round (owner: "make all look a bit tighter and compact and nicer", challenged with an outside review): Coming up is the compact week (frequent repeats as one line of pills, one row per day with its starts on single lines, empty days folded into one row); Recent starts is a compact one-line table; long ticket names end with "…" on one line (full name on hover); at phone width a compact table row is the name, one quiet line of facts, then the buttons.
