- Added the collapsed Preview pill and shared script; added the reusable 48px summary thumbnail and consistent header timestamp treatment.
- Shared snapshot: 3 need you; Anna and Ben own tickets; Helper is the helper. Newsletter 23 min; survey 12:26; sign 12:32; typo 12:27; question 27 min.
- Motion: retain entry, progress and status transitions; honor reduced motion. Preview stays collapsed until requested.
- Performance target: no new dependencies or external network requests; interactions below 100 ms and animation frames below 16.7 ms. Loading and empty states remain available through the Preview pill.


## Revised after the owner's comment (13 Nov)

Round 2 — working shared components.

### components.html
- Linked Shell, Components, Gallery and Motion and kept the shared Preview pill.
- Used the same live components as the area pages, including keyboard controls, visible close buttons and reduced motion.

### gallery.html
- Linked Shell, Components, Gallery and Motion and kept the shared Preview pill.
- Used the same live components as the area pages, including keyboard controls, visible close buttons and reduced motion.
- Added clickable examples with a state selector for default, hover, focus, open, selected, disabled, loading and error, plus a short usage note.

### motion.html
- Linked Shell, Components, Gallery and Motion and kept the shared Preview pill.
- Used the same live components as the area pages, including keyboard controls, visible close buttons and reduced motion.

### shell.html
- Linked Shell, Components, Gallery and Motion and kept the shared Preview pill.
- Used the same live components as the area pages, including keyboard controls, visible close buttons and reduced motion.

Round 2 validation: the shared browser sweep passed all 171 loaded/loading/empty page checks and 144 dialog/viewer checks. Targeted phone, question, keyboard, calendar, full-screen and toolbar checks also passed. See `../system/COMPONENT-QA.md` for the complete inventory and results.
