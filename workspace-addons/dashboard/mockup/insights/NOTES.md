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
