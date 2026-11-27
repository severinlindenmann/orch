- Kept A data; added health status, first-month wording, unavailable-range tooltips, one table tab with data, and a plain skills explanation.
- Shared snapshot: 3 need you; Anna and Ben own tickets; Helper is the helper. Newsletter 23 min; survey 12:26; sign 12:32; typo 12:27; question 27 min.
- Motion: retain entry, progress and status transitions; honor reduced motion. Preview stays collapsed until requested.
- Performance target: no new dependencies or external network requests; interactions below 100 ms and animation frames below 16.7 ms. Loading and empty states remain available through the Preview pill.

## Revised after the owner's comment (13 Nov)

- insights.html: Settings now has an icon and label, with the same 42 px height, background and border weight as the day range control, aligned on the same row.
- insights.html: “All good · nothing needs a look” is a separate small pill with 16 px of space below the subtitle.
- insights.html: Checked header alignment at 1280 and 1920 px; loading, empty and the shared Preview pill still work.


## Revised after the owner's comment (13 Nov)

### insights-settings.html

- Made storage limits an always-visible section below the everyday choices.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### insights.html

- Removed the Details buttons and repeated pop-up facts; connected-service information is now always visible.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### opus-insights.html

- Replaced the Technical details disclosure with a quiet, visible Reference section in the run view.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.


## Revised after the owner's comment (13 Nov)

Round 2 — working shared components.

### insights-settings.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

### insights.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

Round 2 validation: the shared browser sweep passed all 171 loaded/loading/empty page checks and 144 dialog/viewer checks. Targeted phone, question, keyboard, calendar, full-screen and toolbar checks also passed. See `../system/COMPONENT-QA.md` for the complete inventory and results.

## 15 Nov (check-up, #375 phase 3)

- insights.html: Check-up card above the numbers (last check-up line, Run a check-up, Every Monday 07:00 switch, proposals with state chip, Dismiss and one main button; ask-admin rows say "Ask your admin"). Accept opens the master sheet with the plain text and "Show the change". Master design system: no change.

## 17 Nov (no false numbers, ORCH-72)

- insights.html: the Connected services tile says "Not measured yet" (normal text, no big number) while orch cannot see the list of connected services; the small line names how many your helpers used, when any. The first-day view does the same instead of a 0, also for times helpers worked ("No helper runs are recorded here yet"): the record can be empty although helpers worked (ORCH-139). Measured numbers (times helpers worked) stay. Master design system: no change.

## ORCH-1860 (keep the last good reading, ORCH-1855 draft 1)

- insights.html: new preview state "Failed refresh" (`?state=error`). A refresh of one section failed: every number, the chosen tab and the rows read before stay; the master error banner sits by that section's table with "Couldn’t refresh the skills", the time of the last good reading, Try again and the actual error. With nothing read before, the product shows "Couldn’t read …" and no rows (never zeros or the first-day tiles). Master design system: no change (gallery "banner error").

## ORCH-2102 (visual polish)

- insights.html: the four time-and-cost tiles use the master `stat-row four` (values on one line however long a tile's
  small text is; two columns on a phone). "Work over time" is plain text with its button, no longer an image that hid
  the button from screen readers; its sentence is plainer ("Not enough days of work yet to draw a chart."). Table
  cells wrap between words only (no "workspac/e" on a phone). Master design system: no new rule (`mockup.css` cell rule
  gains `overflow-wrap:break-word`).

## Last 7 days (ORCH-2037)

- insights.html: a "Last 7 days" card after the team section: Done and Time to done tiles, then Done and Stuck now lists by name (stuck rows carry the reason). The empty view shows the card's empty state. Same words and parts as the product (`orch insights week`).
