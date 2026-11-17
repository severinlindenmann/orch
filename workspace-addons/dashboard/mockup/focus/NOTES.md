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

## fb17 (14 Nov): Focus inside the dashboard shell
- The accepted target is `proposals/fb17-focus-shell.html`: tickets left, the live session in the centre (Pause while it writes), one result panel on the right (Looks good / Send back only when the helper is done). The product matches it; the older pages in this folder (focus-ticket*.html) show the stand-alone page, which still exists when Focus is opened outside the dashboard.
- Live session (fb17 PR 2): the centre of the shell shows the helper's real screen (read-only for everyone, typing for the person's own dashboard session). See proposals/fb17-focus-shell.html (the `term` block). With no live session the centre says why in one line.

- UX round item 4 (owner: focus-one-ticket): when something needs the person, Focus opens on the next ticket that needs them (oldest question, then oldest result), with "See everything on Home" and "Live now and areas" beside it. The start page (Live now, areas, jobs) shows when nothing waits.

- Fix wave b6 (15 Nov): "Watch live" on a running ticket (agent bar and the ticket's "Live session" card) opens Focus on that ticket (`#addon/focus/t/<ticket>`, Live tab is the default). The card's terminal commands sit behind one small "Copy command" menu. "Tickets in focus" lists tickets a helper is working on first, then the most recently updated. Home: the phone-mode "ended" notice is one toast (then marked seen); the sidebar shows "Pick your name" (opens the person menu) until a person is chosen.

## Focus draft D: the agreed Focus mockup (ORCH-251, ORCH-262, 17 Nov)
focus-v4d.html (script focus-v4d.js) is the one Focus mockup the owner picked: the live wall of sessions (Needs you as a big card, working tiles, idle rows, zoom into one) with a bar under every dashboard page that opens into a layer (right, bottom, split or full screen), chat or terminal per session, the result widgets and the Features sheet. Demo data and a simulated terminal; picks stay in this browser. It is the visual source of truth for building the new Focus behind the Preview switch.
The earlier drafts (v2, layer v3, v4 A/B/C) were removed once D was chosen; they live in the git history of PR 1262.

## The Preview switch for the new Focus (ORCH-264, 17 Nov)

focus-preview.html
- What Focus shows while Settings > Add-ons > Focus > Preview is on: an empty shell with the Preview tag and a way back. The wall, bar and layer of draft D fill it in later tasks.

../settings/addon-detail-focus.html
- New row Preview: "Try the new Focus", off by default.

## The layer, built (ORCH-338, 17 Nov)

focus-v4d.html stays the source of truth for the layer; nothing in the draft changed. The dashboard now has it behind
the Preview switch: one dock under every page (outside the page content, so it stays open when the page changes) with
a panel at the bottom, on the right or full screen, minimise to the bar, close to the side. Place and size are kept per
browser; the top edge of the bottom panel and the left edge of the right one resize it (drag or arrow keys). Esc goes
one step back: an open menu, full screen, then the panel to the bar. One session for now; the pane says where the chat
and terminal come. Master: `.live-*` in widgets.css (style guide: Live layer), icons dock-bottom, dock-right,
dock-side, full-screen, full-exit.
## The bar is built (ORCH-337, 17 Nov)

- The bar of draft D is in the dashboard behind the Preview switch (`pages/livebar.js`), with its look in the kit
  (`.lbar` in `widgets.css`, gallery section "Live bar"). Same groups, words and fold steps as `chipsHTML` here.
- Two changes from this draft: an open list scrolls inside its box (here it runs past it), and when even symbols and
  numbers do not fit, needs you stays and the rest becomes one More count (fold 4), so nothing is cut at 320 wide.
- New, Open and Where Focus sits come with the layer; the bar keeps an empty `.lbar-end` slot for them.

## The split, built (ORCH-339, 17 Nov)

focus-v4d.html stays the source of truth; nothing in the draft changed. Behind the Preview switch the layer now holds
1, 2 or 3 sessions side by side (stacked in the right panel), in the order of the bar's chips. One pane is selected
(brand line on top); the title of another selects it. Every pane has pin, add beside (the next live session; off at
three), place, full screen, minimise and close; closing a pane gives its room to the others and selects its neighbour.
Narrow panes (three at 1280, more than one on the right, a phone) fold pin and place into More, as in the draft. A
phone shows only the selected session and has no add beside. The split and the selection are kept per browser and
stay while the page changes. Pins are kept in this browser (the bar's key) until the wall stores them in orch.
Master: `.live-*` in widgets.css (style guide: Live layer); click-through step 12.

## Earlier sessions, built (ORCH-363, 17 Nov)

orch keeps the last 10 sessions per ticket on this computer (the ones in use included; only the ids are forgotten,
never the tool's own files). Behind the Preview switch each pane has a History button (in More when the pane is
narrow) that shows the draft's "Earlier sessions" list instead of the session: time, first message, number of
messages and the tool, newest first; the one in use says In use, one whose conversation is not on this computer has no
Reopen. Reopen starts the helper on that conversation (`orch run start <ticket> --session <id>`); while a helper works
the buttons are off with one line why. The draft's Start choice above the list (continue, fresh start, tool and model)
is the Start task; this draft lost only its "To build" chip and note. Master: `.live-hist*` in widgets.css (style guide:
Live layer); click-through step 26.
