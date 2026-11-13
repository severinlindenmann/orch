- Kept A review; added the summary, compact file actions, bounded preview, expanded requirement, and next-step explanation. Carried headers and file actions through the other states.
- Shared snapshot: 3 need you; Anna and Ben own tickets; Helper is the helper. Newsletter 23 min; survey 12:26; sign 12:32; typo 12:27; question 27 min.
- Motion: retain entry, progress and status transitions; honor reduced motion. Preview stays collapsed until requested.
- Performance target: no new dependencies or external network requests; interactions below 100 ms and animation frames below 16.7 ms. Loading and empty states remain available through the Preview pill.


## Revised after the owner's comment (13 Nov)

The tabs are directly below the ticket header; open Tasks to see each task’s evidence, Files to see its attached files, and Activity to see what happened.

### ticket-review.html

- Expand and every file preview now open the same file viewer with the survey title, details, Open in new tab, Download and Copy link.
- × Close, Esc and clicking outside close the viewer and return focus to the opening control.
- Added counted Tasks, Files and Activity tabs; the survey note belongs to reading the answers and the summary file belongs to writing the summary.

### ticket-working.html

- Kept the compact Progress overview and added working Overview, Tasks, Files and Activity tabs below the header.
- Each task opens its own notes, files and links; the skipped photos and unfinished test mail explain why there is no evidence yet.
- The newsletter plan identifies its two related tasks and opens in the closable viewer; Files also links to the full grid.

### ticket-change.html

- Added tabs with task and activity counts while keeping the Overview.
- The price list is linked to comparing prices and updating the sheet; the shipping-cost request clearly has no result yet.
- Price-list previews use the same closable viewer and file actions.

### ticket-question.html

- Added Overview, Tasks, Files and Activity tabs below the header.
- Tasks and Files show honest zero counts and explain where future evidence will appear; Activity shows the supplier question.

### ticket-copy.html

- Added working tabs and retained the current Overview.
- The printing task opens its completion note; Files explains that no file is attached and links to the full grid.

### ticket-done.html

- Added working tabs and retained the result and compact Progress overview.
- The opening-time task opens its completion note; Files shows zero attached files rather than counting the note as a file.

### opus-ticket-review.html

- Added the same counted tabs with task evidence and file ownership labels.
- Replaced placeholder preview and download links with the actual survey file; the preview has × Close, Esc, outside-click closing and focus return.
- Kept the shared shell and Preview pill, and repaired the embedded survey preview.

Validation: browser checks passed for all seven pages in loaded, empty and loading states, with no page errors. Checked task disclosures, tabs, file opening, Close, Esc, outside-click closing and focus return. Existing motion and reduced-motion settings remain; the new viewer and evidence use brief transitions.


## Revised after the owner's comment (13 Nov)

### opus-ticket-review.html

- Made review checks, history and actions visible, renamed the Properties heading, and gave the title a full row so the actions cannot squeeze it.
- Tasks use separate title and note lines and Done, Skipped or Working labels; task evidence can still be opened.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### ticket-change.html

- Made the short notes, ticket actions and property fields visible without Details or More disclosures; separated the owner control from its label.
- Tasks use separate title and note lines and Done, Skipped or Working labels; task evidence can still be opened.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### ticket-copy.html

- Made the short notes, ticket actions and property fields visible without Details or More disclosures; separated the owner control from its label.
- Tasks use separate title and note lines and Done, Skipped or Working labels; task evidence can still be opened.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### ticket-done.html

- Made the short notes, ticket actions and property fields visible without Details or More disclosures; separated the owner control from its label.
- Tasks use separate title and note lines and Done, Skipped or Working labels; task evidence can still be opened.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### ticket-question.html

- Made the short notes, ticket actions and property fields visible without Details or More disclosures; separated the owner control from its label.
- Tasks use separate title and note lines and Done, Skipped or Working labels; task evidence can still be opened.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### ticket-review.html

- Made the short notes, ticket actions and property fields visible without Details or More disclosures; separated the owner control from its label.
- Tasks use separate title and note lines and Done, Skipped or Working labels; task evidence can still be opened.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### ticket-working.html

- Separated task titles from notes, showed the skipped-photo reason on its own line, and included the current test-mail task in the Tasks tab.
- Tasks use separate title and note lines and Done, Skipped or Working labels; task evidence can still be opened.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### assets/survey-results.html

- Checked the standalone survey result at 1280 × 800; its title, findings and answer count remain readable.
- Kept the real 112-answer survey content and the file used by ticket previews.

Validation: all 39 main pages passed loaded, loading and empty checks at 1280 × 800. Task status words, title and note spacing, owner changes and Undo, file upload and keyboard focus, and Focus headers and earlier-task lists passed browser checks.


## Revised after the owner's comment (13 Nov)

Round 2 — working shared components.

### ticket-change.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

### ticket-copy.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

### ticket-done.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

### ticket-question.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Questions now share recommended choices, a checked written answer, an answered state and Undo; phone and desktop show the same reply.

### ticket-review.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

### ticket-working.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

Round 2 validation: the shared browser sweep passed all 171 loaded/loading/empty page checks and 144 dialog/viewer checks. Targeted phone, question, keyboard, calendar, full-screen and toolbar checks also passed. See `../system/COMPONENT-QA.md` for the complete inventory and results.
