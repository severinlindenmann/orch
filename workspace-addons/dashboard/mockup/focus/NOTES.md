- Merged the B monitoring layout using real tickets, gift-box answers, survey preview, times and pending changes. Removed fabricated live events; rows open the watcher. Kept the alternative.
- Shared snapshot: 3 need you; Anna and Ben own tickets; Helper is the helper. Newsletter 23 min; survey 12:26; sign 12:32; typo 12:27; question 27 min.
- Motion: retain entry, progress and status transitions; honor reduced motion. Preview stays collapsed until requested.
- Performance target: no new dependencies or external network requests; interactions below 100 ms and animation frames below 16.7 ms. Loading and empty states remain available through the Preview pill.

## Revised after the owner's comment (13 Nov)

focus.html
- Every Copy link copies the result address and shows a small “Link copied” message without leaving the page.
- Copy clicks stop before any surrounding row can open another page; a blocked clipboard shows the address without navigating.

focus-help.html
- The result’s Copy link uses the same clipboard action and small confirmation.
- The help sheet and shared Preview pill remain available.

opus-focus.html
- Copy link now copies the real survey result address instead of only changing its label.
- The shared copy action prevents navigation and shows the same confirmation.

focus-ticket.html
- Focus supports technical and non-technical people: plain updates come first, with the live terminal one click away.
- Added the live Now card for “Plan the autumn newsletter”, Task 4 of 4: “Send a test mail to the team”, plus a dimmed five-line terminal peek.
- Added inline recipient answers, messages, a Newsletter draft page preview and a “Pull request: Update opening hours page” review card; both previews open in place.
- The labelled demo advances through link, text and phone checks; pausing stops updates, and no real mail is sent.
- Kept shared navigation, Preview, loading and empty states, entry motion and reduced-motion support.

focus-ticket-terminal.html
- Opens with the live terminal on the left and plain updates, questions, links and messages on the right.
- Terminal commands build and check the autumn draft and prepare a team test; the cursor stays steady.
- The Terminal toggle remembers the chosen mode; answers, messages and review choices survive page changes in this session.
- The layout stacks on narrow screens and includes loading and empty states.

focus-ticket-fullscreen.html
- Opens the terminal view with the sidebar and topbar hidden so the ticket uses the workspace.
- A visible “Exit full screen” button and Escape restore navigation; the ticket header and Preview pill stay available.
- Questions, previews and messages remain beside the terminal during deep work.

Validation: checked all three ticket pages in loaded, loading and empty states at 390, 1280 and 1920 pixels; checked clipboard text and no navigation on all four page types, remembered mode, full screen and Escape, messages after reload and preview opening. JavaScript syntax checks passed.


## Revised after the owner's comment (13 Nov)

### focus-help.html

- Removed the unused Details-toggle code while preserving the help sheet and result actions.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### focus-ticket-fullscreen.html

- Removed DEM-1 from the header and showed earlier tasks as a plain list; spaced the list and kept the message bar clear of the Preview pill.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### focus-ticket-terminal.html

- Removed DEM-1 from the header and showed earlier tasks as a plain list; spaced the list and kept the message bar clear of the Preview pill.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### focus-ticket.html

- Removed DEM-1 from the header and showed earlier tasks as a plain list; spaced the list and kept the message bar clear of the Preview pill.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### focus.html

- Removed the unused Details-toggle code and kept the compact live rows and result actions.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### opus-focus.html

- Removed the Details buttons and ticket keys; the short progress notes now stay visible with space between rows.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.


## Revised after the owner's comment (13 Nov)

Round 2 — working shared components.

### focus-help.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Questions now share recommended choices, a checked written answer, an answered state and Undo; phone and desktop show the same reply.

### focus-ticket-fullscreen.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Questions now share recommended choices, a checked written answer, an answered state and Undo; phone and desktop show the same reply.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### focus-ticket-terminal.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Questions now share recommended choices, a checked written answer, an answered state and Undo; phone and desktop show the same reply.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### focus-ticket.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Questions now share recommended choices, a checked written answer, an answered state and Undo; phone and desktop show the same reply.
- Full-screen previews have a visible Exit full screen button and Escape closes them; focus and scrolling return when they close.

### focus.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Questions now share recommended choices, a checked written answer, an answered state and Undo; phone and desktop show the same reply.

Round 2 validation: the shared browser sweep passed all 171 loaded/loading/empty page checks and 144 dialog/viewer checks. Targeted phone, question, keyboard, calendar, full-screen and toolbar checks also passed. See `../system/COMPONENT-QA.md` for the complete inventory and results.

## Round 3

The revised Focus view puts your blocking question first, keeps returned work beside your instructions, and lets you paste screenshots or drop files without leaving the ticket.

- Adopted ideas 4 and 17: one turn status, a short task strip, and a full-screen workspace that preserves the chosen mode.
- Adopted 5–9: one recipient question with addresses and consequences, a visible queue count, phone handoff, versioned results inspected beside the composer, queued instructions with Take back and a separate interruption action.
- Adopted 2, 3 and 13: linked task/command blocks, copy actions, search and navigation to a resolved warning. Adopted restrained 11 and 14: outcomes, durations and ticket/step links.
- Revised 1, 10 and 12 as challenged: following starts off, reading pauses it, updates enter in 150 ms, timestamps describe the recorded work, and conversation has one optional filter. Deferred takeover, blanket permissions and rollback (15, 16, 18).
- The owner's explicit additions take precedence over two research proposals: 100 MB per attachment and three columns at 1920px in terminal mode. FileReader progress is local demo preparation, not a remote upload; no real email is sent.
- Rechecked the [command-block reference](https://docs.warp.dev/terminal/blocks) and [session-state reference](https://linear.app/developers/agent-interaction). Their grouped output and explicit input-waiting state support the chosen design; the design challenge determined the final hierarchy.

## Revised after the owner's comment (13 Nov)

### focus-ticket.html
- Made compact the default, with the recipient question first, a single turn status and a one-line trace linking to terminal mode.
- Kept versioned newsletter, change-review and test-report cards visible while writing; reviews show what changed and do not imply publication.
- Added screenshot paste, page-wide file drop, thumbnails, removal, limits, local progress and ticket attachment entries through the shared composer.
- Added queued instructions with Take back, explicit Interrupt now, following controls and saved draft, attachment and reading state.

### focus-ticket-terminal.html
- Added command/output blocks with task links, highlighting, search, copy actions and a resolved-warning jump.
- Used work log, terminal and collaboration columns at 1920px, with the blocking question and composer visible at 1280×800.
- Kept preview inspection beside the same composer and preserved the selected work across mode changes.

### focus-ticket-fullscreen.html
- Removed the sidebar and topbar; kept the topic, turn status and visible Exit full screen action.
- Escape returns to the previous mode; entering from compact keeps compact, and entering from terminal keeps terminal.
- Kept the question, sent-back work and attachment composer in the focused workspace.

### focus.html
- Added the same recipient question, newsletter preview, opening-hours change and test-mail report cards.
- Shared the newsletter status and recipient answer with the ticket workspace; used Paused without a contradictory Working label.

### newsletter-preview.html and review-preview.html
- Added real local destinations for Open externally, with version labels and the same newsletter and opening-hours content.
- Included a return to Focus and the shared Preview pill.

Validation: browser checks passed for all 15 loaded/loading/empty combinations across the four Focus pages and gallery. Checked 1280×800 and 1920×800 layout geometry, question visibility, composer visibility, command links, review inspection, file selection, screenshot paste, whole-page drop, Take back, full-screen mode preservation and Escape. JavaScript syntax checks passed. No files outside focus/ and system/ were edited.

## Revised after the owner's comment (13 Nov)

### focus-ticket.html
- Removed viewport and card height limits: the page scrolls, returned cards fit their contents, and the full conversation is reachable.
- The composer stays in the main column and sticks at the bottom once reached, without covering the cards above it; its hint is “Paste a screenshot or drop files · up to 100 MB each”. File types appear only in a refusal message.
- Question buttons use the shared 14 px text and 36 px minimum height; Follow the helper uses the shared switch.
- Terminal steps use shared button and chevron styling with keyboard controls; the active step stays open.
- Kept demo content, loading and empty states, motion, Preview and the chosen mode when entering or leaving full screen.

### focus-ticket-terminal.html
- Removed viewport and card height limits: the page scrolls, returned cards fit their contents, and the full conversation is reachable.
- The composer stays in the main column and sticks at the bottom once reached, without covering the cards above it; its hint is “Paste a screenshot or drop files · up to 100 MB each”. File types appear only in a refusal message.
- Question buttons use the shared 14 px text and 36 px minimum height; Follow the helper uses the shared switch.
- Terminal steps use shared button and chevron styling with keyboard controls; the active step stays open.
- Kept demo content, loading and empty states, motion, Preview and the chosen mode when entering or leaving full screen.

### focus-ticket-fullscreen.html
- Removed viewport and card height limits: the page scrolls, returned cards fit their contents, and the full conversation is reachable.
- The composer stays in the main column and sticks at the bottom once reached, without covering the cards above it; its hint is “Paste a screenshot or drop files · up to 100 MB each”. File types appear only in a refusal message.
- Question buttons use the shared 14 px text and 36 px minimum height; Follow the helper uses the shared switch.
- Terminal steps use shared button and chevron styling with keyboard controls; the active step stays open.
- Kept demo content, loading and empty states, motion, Preview and the chosen mode when entering or leaving full screen.

Validation: all 18 ticket-page checks passed at 1280×800 and 1920×1080 across loaded, loading and empty states, including card sizing, question buttons, result inspection, queued instructions, Take back and refused attachments.

Final component validation: the requested `node base/scripts/qa-components.cjs 1280` sweep reports no problems for any Focus or system page; the same checks pass at 1920 pixels. The full sweep reports one unrelated problem in `board/new.html`, outside these folders.
