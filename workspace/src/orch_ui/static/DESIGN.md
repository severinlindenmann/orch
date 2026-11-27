# orch design system: the one master

This folder (`workspace/src/orch_ui/static/`) is the single component library and style guide for the dashboard, every add-on page and every mockup page. Open `gallery.html` (served at `/styleguide` by the dashboard, also at `/kit/gallery.html`, and opened from Settings, About) to see every component in every state with motion Replay.

## The rules (owner, 14 Nov 2026)

1. Build on the master. Use existing components and tokens; never write a page-local look, a copied kit file or a new "system" sheet.
2. Need something missing? Add it here first: (a) the component in `widgets.css` / `widgets.js` (or the file it belongs to), (b) an entry in `gallery.html` / `gallery.js` with its states (default, loading, empty, error where they apply), (c) a test in `workspace/tests/test_orch_ui_kit.py` if it adds a file, then use it from the page.
3. Mockup pages link these files by relative path (`../../../../workspace/src/orch_ui/static/...`); the mockup folder keeps no stylesheet of its own One exception (owner 17 Nov, ORCH-267): a draft that needs new looks keeps them in one `draft.css` in its own draft folder (`mockup/<area>/draft-<ticket>/`), tokens only, every rule under the draft's own body class; product pages never link it. When the owner picks, the chosen looks move into the master (`widgets.css` plus a gallery entry) and every draft folder of that round is deleted in the same pull request. Never write draft rules into `mockup.css` or `widgets.css`.
4. Owner wording rules: one click, no typed words; minimal plain words; no "Details" / "Technical details" toggles (show the detail plainly lower down); no "NetBird" (say "private network"). Old reference examples below that show a Details disclosure are legacy and must not be copied.
5. Never change tokens in a page. Colour and size tokens come from `brand/tokens.json` via `brand/gen_tokens.py` (`tokens.css` is generated).

## Files

| File | What |
|---|---|
| `tokens.css` | Generated tokens: colour, type, spacing, shape, motion durations and easings. |
| `components.css` | Shell, sidebar, topbar, page, card, button, input, badge, chip, table, tabs, segmented, progress, empty/error, skeleton, tooltip, toast, dialog, sheet, menu, the one `.chev` chevron. |
| `widgets.css`, `widgets.js` | Added 14 Nov: status icon set, pill, empty/error/loading state, stat tile, labelled progress, sortable table, `data-tip` tooltip, sheet, dialog S/M/L, strip, board, file card, type utilities. `UI.statusIcon`, `UI.state`, `UI.stat`, `UI.progress`, `UI.table`, `UI.sheet`, `UI.chevron`. |
| `widgets.css`, `widgets.js` (17 Nov, ORCH-73) | Phone: `.tabbar` / `UI.tabbar(items)` bottom bar (Home, Tickets, Review with the one needs-you number, More = the side menu; only up to 720 px, the top bar and side menu step aside), `.short-group` / `UI.shortGroup` short rows (number and title, one fact, one thing on the right: steps pill, chip or Answer), `.phone-only` / `.wide-only` to show one of two layouts by width. |
| `widgets.css` (20 Nov, ORCH-1081) | Tickets calendar `.cal-*` (owner picked draft C): bar (previous / next / Today, title, Month / Week), month as week rows with one Weekend cell (`.cal-grid`, `.cal-row[data-when=past|now|next|later]`, `.cal-cell`, `.cal-chip`, `.cal-more`), the Late list (`.cal-lane`), the week as day rows (`.cal-drows`, `.cal-drow`, `.cal-card`), the phone lists (`.cal-phone`, `.cal-pwk`, `.cal-prow`, `.cal-plate`). Built by the dashboard's `tickets.js` `calendarView`; plan in `DashHelpers.calendar`. Gallery: Tickets calendar. Icons `calendar`, `chevron-left`. |
| `review.js`, `review.html`, `review-boot.js` | Review stack (15 Nov): `UI.reviewPage` (Waiting deck on `UI.swipeDeck` + Answered list), `UI.answerRecord` and `UI.appliesNow` (answers under a ticket's questions; every record names its ticket key and title, tiles are about 344x216 and a click or Enter opens one large in `UI.reviewViewer`: fits the width, tall pictures scroll, words in full in lines of at most 75 characters, ← → to the card's other tiles; ORCH-172), `UI.reviewFetchApi` (same-origin api of the page `orch review` serves). `review.html` is that page, `review-boot.js` signs in from the `#t=` fragment and starts it. Voice in the deck only with `voice:true`. Since 18 Nov (ORCH-477, owner pick B): a deck card is as tall as what it holds at every width (no fixed frame, no `--swipe-card-h`); the answers are one bar pinned to the bottom of the screen (`.swipe-actions`, sticky) with the "If you approve" line in it (`.swipe-bar-then`); a result's file tiles open large in the page in `UI.reviewViewer` (← →, Close, Esc, "Open in new tab" inside; a PDF in the browser's own view without its toolbar) and a PDF tile shows its first page (`FileViewer.thumb({src, name})`, the icon stays without a PDF view). Compare: `deck.tick(ref)` / `deck.compare([a, b])` put two cards, or two options of one choice (`deck.optionRefs(item)`), side by side (`.swipe-pair`), each with its own answers; only the suggested answer is filled (two suggested sides: none); Close and Esc go back to one card. Every "All cards" list uses `deck.tickBox(ref, label)` (`.review-tick`, `.review-queue-item`); the list stands left of the deck (`.review-layout`) at every desk width and a phone shows "All cards · 1 of N" with ← → (`.swipe-jump`) and one side at a time with a switch naming both (`.swipe-pair-switch`). Gallery: "Review compare". Round 2 (18 Nov, owner sent back): the list is the kit's own, `deck.drawList(el)` (`.review-list-head` with "All cards" and one "Compare" button, `.review-group` with the ticket name and a count only when more than one waits, `.review-row` with icon, a two-line title and the deadline under it, the current card tinted with a 3 px mint left edge); ticks show only in Compare mode (`deck.setPicking(on)`, at most two; `deck.showPair()` opens them; Cancel, Close or Esc ends it); the phone's full list (`deck.openOverview()`) draws the same rows and gives focus back to its opener. A card reads in one column (`--review-card-w` 760 px, centred with its tabs on a wide screen): title, then one meta line (type · deadline · ticket key; `item.dueAt` within a day makes the deadline amber), the words box on `--surface-2`, files in equal boxes (2 columns, 3 from 1600 px, 1 on a phone) that never crop. One answer bar everywhere: the consequence line, then Later left and the answers right (44 px, 12 px apart, only the suggested answer filled). A programmatic focus of the deck shows no ring (`.quiet-focus`); a keyboard focus does. Gallery: "All cards list". Draft 24 Nov (ORCH-1804): `reviewPage({ticketPanel:id => href})` gives every card an "Open ticket" link (`swipeDeck` option `ticketLink(item)`, `.swipe-ticket`, in place of a stuck card's plain "Open"); the page shows that ticket beside the deck (`.review-layout.with-ticket` + `.review-ticket`, `.review-ticket-h`, `.review-ticket-b`) in place of All cards: the ticket page itself in one column, sticky under the top bar, scrolling by itself, with "Open full page" and Close; its filled buttons read as outline. A phone shows it in the card's place. Gallery: "Review ticket panel". ORCH-2024, ORCH-2113: with the All cards list empty (nothing to review, or one card alone) and nothing else in the rail the layout is one column, so the Waiting / Answered switch lines up with the page heading and the empty state or the card sits in the 760 px card column under it (mockup `review.html?empty=1`, `review.html?one=1`). ORCH-2184 (Focused review C, with `decisionFirst` and more than 5 cards): `UI.attentionTiles(groups, {onPick})` draws Quick look / Short decision / Take your time as `.stat-tile.attn-tile` buttons over the deck (`.review-attn`); a tile starts a round of up to 5 (`.attn-round` bar with "Back to the start" and the keys line), the deck's `endView` is the round's "What you decided" (`.attn-end`, `.attn-decided`); deck keys 1 2 3 J K M U Esc; motion `orch.enter`. Gallery: "Attention tiles". ORCH-2186 (Focused review E, with `decisionFirst`): `item.ideas` draws one `.swipe-idea` row per idea in `.swipe-ideas` with a `.segmented.swipe-idea-sort` Keep / Later / No (full width on a phone) in place of the plain list; the ok answer is "Save" / "Save, N left for later" and answers ok with `note.ideas` `{keep, no, later}` (numbers from 1); `UI.ideasWord(sorted, total)` words the answer ("2 kept, 1 no, 5 for later"). Gallery: "Ideas card". |
| `interaction.css`, `overlay.js`, `select.js`, `date.js`, `components.js` | Dialog lifecycle, custom select (one SVG chevron), calendar, toast with Undo (`UI.toast`), menus, tabs and segments keyboard. |
| `motion.css`, `motion.js` | Motion tokens in use (see Motion contract). |
| `icons.js` | One icon set, `icon('check', 16)`. |
| `preview.css`, `fileviewer.*`, `evidence.js`, `blocks.*` | File and result previews, viewer, proof, blocks. |
| `results.css`, `results.js` (17 Nov, ORCH-263) | Result widgets, look from Focus draft D: `UI.result(item, {size: 'sm' \| 'lg', state})` for the 16 kinds (Markdown, text and logs, code, JSON and YAML, table, web page, PDF, picture, video, audio, chart, change, pull request link, archive, plain link, unknown file), each loaded, empty, loading, error and too big; `UI.resultOverlay(list, i)` the big overlay (← → between results, × Close, Esc, a click outside). `UI.result.kindOf(name)` picks the kind. No fetching: the page hands in the content. Gallery: Result widgets. The dashboard feeds them from a ticket's real files, evidence, check runs and links in one place (`pages/results-feed.js`, ORCH-697: `resultsHost(ticket)` on wall tiles, in a session's chat, on the Results shelf of a Focus pane and on the ticket page; the shelf `.live-shelf` in `widgets.css` (ORCH-1356) is a column beside the chat in full screen and in the bottom layer from 900 px, a one-row strip above it on the right and on a phone); `.results-host`, `.result-links` and `.result-more` lay them out. |
| `widgets.css` (19 Nov, ORCH-834) | Switch list from the Skills page (draft A): `.switch-table` (on a `.data-table`: a switch or an "Always on" chip in the first cell, name with one quiet line, `td.nowrap` for short words, a row click opens the side panel; on a phone each row stacks), `.list-tools` (the segmented filter and the search above a list) and `.facts` (label and value pairs in a side panel). Gallery: Content, Switch list. |
| `widgets.css` (20 Nov, ORCH-840) | `.sheet-actions`: Save and Cancel stay in view at the foot of a side panel (`dialog.sheet`) while its form scrolls (Skills page, Edit). Gallery: Content, Switch list. |
| `widgets.css` (25 Nov, ORCH-2065) | Setting row (`.setting-row`): a switch only where flipping it saves the setting. When the change happens somewhere else (Chat), the row states today's behaviour from the record and its action is a secondary `btn outline sm` that names the destination ("Change in Chat"), never a switch that flips back. Gallery: Setting row. |
| `widgets.css`, `widgets.js` (26 Nov, dashboard decisions D4-D6, owner picked A) | One look per page state, the same on every dashboard and add-on page: `UI.pageEmpty({title, text, step})` (`.page-empty`): a page with nothing in it yet says what is missing and in one sentence what shows up here, with the first step right there (the page's own input with its green button, or one green button); no step where the helper fills the page. `UI.pageNotice({what, still, action, tone})` (`.page-notice` on `.banner.attn`/`.error`): when something is wrong ONE notice right under the page name: what happened (bold), what still works, one green button (Start Factory, Try again); the page keeps its name and what it can still show; Home says the same sentence once; never a command to type, never "this computer". `UI.settingsButton({href})` (`.settings-btn`): an add-on's one Settings button (gear + Settings, outline), first among the page top's buttons; it opens that add-on's part of Settings (`#settings/addons/<name>`), whose "Back to <page>" returns to where the person came from. Gallery: One look per page state. |
| `widgets.css` (23 Nov, ORCH-1739) | Add several at once (owner pick A): `.pick-list` / `.pick-row` (real checkboxes, `.pick-why` for one added because another needs it), `.consent-list`, the run's steps `.run-steps` / `.run-step.is-now\|is-done\|is-bad\|is-skip` with `.run-ic`, `.run-sub`, `.run-reason`, `.progress.indeterminate` (no honest percentage), `.elapsed`, `.done-list`, `.banner.slim`, `.dialog-head`, `.link-quiet`, and `dialog.dialog.sheet-phone` (a bottom sheet with sticky actions under 600 px). Built by the dashboard's `pages/addon-add.js`. Gallery: Add several at once. |
| `widgets.css`, `widgets.js` (25 Nov, ORCH-2034) | Pick several and change them at once: a checkbox per row (`.pick-cell`, `.row-pick`, 32 px target; the header box picks every shown row, indeterminate when some are), the picked row `tr.is-picked`, and `UI.bulkBar({count, busy, actions, clear, label, key})`: the bar that stays at the foot of the screen while rows are picked ("3 selected", the actions as menus that open upwards, Clear; `busy` "Saving 2 of 5…" with a spinner, the actions wait; `data-toast-clear`). Built by the dashboard's `tickets.js` (Status, Priority, Epic). Gallery: Pick several. |
| `qr.js` | QR code picture for a link (`OrchQR.svg(text)`, byte mode, ECC M, null when too long), used by Share my places (ORCH-1273). |
| `docs.css`, `docs.js` (19 Nov, ORCH-735) | The Documentation page: `UI.docs(host, data, {at, link, settings, sel})` draws the overview (three layers, Start here, lines for what works together, live facts) or one page (page list at the left, a flow in lanes You / orch / Helper / Outside / Server, a state diagram or side-by-side flows, Under the hood with live facts, commands and places). Data: `contracts/docs-pages.md`; sample `samples/docs-sample.js` (generated). Gallery: Documentation page. Positions are set through CSSOM (no style attributes). |
| `term.css`, `term.js`, `xterm*.js`, `LICENSE-xterm.txt` (19 Nov, ORCH-744) | The helper's real screen, `UI.term({label, onInput, onSize})` on the terminal bridge: xterm.js 5.5.0 with its WebGL renderer and fit addon, vendored unchanged (licence and checksums in `LICENSE-xterm.txt`; the xterm.css rules it needs are in `term.css` on tokens). Watching only by default, **Let me type** switch, Copy, a paste with a line end asks once, the screen follows its box while typing. Gallery: Terminal. |
| `browser.css`, `browser.js` (22 Nov, ORCH-1493, ORCH-1494) | The helper's browser, live: `UI.browserView({label, onStop, onHide})` on the browser add-on's stream (`/api/browse/stream`). Screen pictures on a canvas scaled to its box, tabs (two or more), up to three cards of what the browser stopped, Stop, Hide, pinch to zoom. `UI.browserPeek({onOpen, wide})`: the small live preview, the one way in. `.bview-beside`: the view next to the steps. Take over and give back (ORCH-1495): `control` option, `handle.control({state, mine, asking})`. Gallery: The helper's browser, live. |
| `widgets.css` (19 Nov, ORCH-834) | Switch list from the Skills page (draft A): `.switch-table` (on a `.data-table`: a switch or an "Always on" chip in the first cell, name with one quiet line, `td.nowrap` for short words, a row click opens the side panel; on a phone each row stacks), `.list-tools` (the segmented filter and the search above a list) and `.facts` (label and value pairs in a side panel). Gallery: Content, Switch list. |
| `question-card*.js`, `composer.*` | Question card, chat composer (`UI.composer`: words, pasted screenshots, picked or dropped files; `voice:true` adds Record, `UI.voiceRecorder`, words only from on-device speech to text; `send:false` inside the Review comment sheet, ORCH-422; `layout:'row'` is draft D's message box in a Focus pane: previews above one line of clip, words and Send, ORCH-695). |
| `gallery.html`, `gallery.js`, `gallery.css`, `state-controls.js`, `samples/` | The living style guide, its fixtures, and the Loaded / Loading / Empty / Error switcher the mockup pages use. |
| `mockup.css` | Mockup-only layout, linked only by the dashboard mockup pages (merged from the former per-draft sheets, #795 D1). Every rule is scoped with `body.mk-<draft>`; not for product pages, no new rules (R6.2). |
| `widgets.css` (#863, #1025, #1901) | List row with visible actions (`.row-acts` at the end of a `.list-row` or a block list `li.acc-li`; gallery `#list-row-actions`); file card `.file-grid` / `.file-tile` with list view and loading cards, moved here from the ticket page (gallery `#file-card`); a `.switch` keeps its 36 × 24 track in a tall row (gallery `#switch-row`). |
| `tokens.css` (#908) | Link-tile brand colours `--link-*` and the phone-mode page colours `--mm-dark-*` / `--mm-light-*` come from `brand/tokens.json`; `widgets.css` uses only these variables, `brand/tests/test_contrast.py` checks the phone-mode text. |
| `COMPONENT-QA.md` | The 13 Nov component audit (QA-01..30). |
| `demo.html` | Older question-card and proof demo. |

## How to add a component

1. Read this file and open `gallery.html`; check it does not already exist (search the gallery and `components.css`).
2. Write the CSS on tokens only (no hex colours, no px outside the spacing scale, durations from `--dur-*`).
3. If it needs script, add a builder to `widgets.js` that uses `textContent` for text.
4. Add the gallery entry with every state; run the gallery check (`uv run pytest tests/test_orch_ui_kit.py`) and the UX checks (`node workspace/src/orch_ui/tests/ux_checks.cjs`).
5. Use it from the page; update the matching mockup page in the same PR.

## UX/UI checklist (owner, 16 Nov 2026)

Every UI change (page, component, state, words on screen, motion, mockup, visual fix) and every review of one passes
this list before it is called done. It extends the rules above and never overrides them: owner rules > this file and
`AGENTS.md` R6/R7 > the checklist > general practice. The procedure is skill `orch-ux-checklist`
(`.agents/skills/orch-ux-checklist/`); thresholds, how to check each item and the sources (WCAG 2.2, NN/g, web.dev,
GOV.UK, Material) are in its `references/CHECKLIST.md` and `references/RESEARCH.md`.

**How:** screenshots at exactly 1280x800, 1920x1080 and 390x844 (plus 320 for reflow), one set per state the change
touches (loaded, loading, empty, error, stale, long content), one with keyboard focus on the main action and a
before/after pair around the main click. Answer every item yes / no / n.a.; fix every "no" or say why. The PR body
says `UX checklist: 61 items, N n.a., all others yes` (or the "no" lines with reasons), `Screenshots:`,
`Mockup: updated <where>`, `Master: <change or none>`. A change of look, flow or words goes to the owner as a review
card with the before and after pictures.

**Never ship with a "no":** A1, A3, B2, D2, E3, H1, H3, H5, I1, L1.

| Group | Items |
|---|---|
| A Design system | A1 no new CSS, `<style>` or hex outside the master · A2 tokens only, 4-pt spacing, radius 8/10/12 · A3 master components only, new ones in the gallery · A4 SX-2 type scale, SX-1/SX-4 edges judged at exactly 1280 · A5 mockup changed in the same PR and matching · A6 polish: one edge per side, status icon in pills, no lone-initial avatars, ellipsis, nothing clipped |
| B Hierarchy | B1 5-second test: what, why, what can I do · B2 exactly one filled button per view, counting the top bar; New ticket outlined · B3 at most 7 facts per card, 5 KPIs, no Details toggles · B4 long text at most 3 lines on level 1, prose at most 76ch · B5 no repeated sentence, counts match everywhere |
| C Navigation | C1 active nav, crumb, title = nav label · C2 every view, tab and filter has a URL; Back keeps scroll · C3 no dead ends, every state has a next step |
| D Actions | D1 verb labels that name the outcome, no OK or Submit · D2 costly action: cost and time above it, not filled, not autofocused, a cheaper choice beside it · D3 destructive: Danger style, set apart, Undo over confirm · D4 dialog footer `[tertiary] … [Cancel] [Primary]` · D5 a disabled control says why, next to it |
| E States | E1 skeleton shaped like the result: its place is held at once, it shows after 300 ms (`.skeleton-page`, `.skeleton-late`), no page spinner, no bare "Loading…" text · E2 master empty state, one sentence, one button, only after loading · E3 error: what happened, what to do, one button, next to its source · E4 stale, partial or offline keeps the data, "Updated … ago" · E5 0 / 1 / many, plurals, a 200-character title, a long word · E6 missing permission or add-on: hidden, or disabled with the reason |
| F Feedback | F1 response within 0.1 s · F2 1-10 s inline spinner with a label; over 10 s the step, elapsed time and Cancel · F3 toast 5 s, names the object, Undo; error toasts stay · F4 live updates `role=status`, never steal the scroll |
| G Forms | G1 visible labels, `autocomplete` / `inputmode` · G2 a default chosen, choices before typing · G3 validate on continue, error next to the field plus a summary |
| H Accessibility (WCAG 2.2 AA) | H1 text 4.5:1, large text 3:1 · H2 control borders and focus 3:1 · H3 everything by keyboard, visual order, no trap, Escape returns focus · H4 focus visible and never under a sticky bar · H5 targets at least 24x24 CSS px (touch 44x44) · H6 name, role and state; axe 0 serious · H7 one h1, ordered headings, landmarks, skip link, unique title · H8 colour never the only signal · H9 320 px and 200% text, no page sideways scroll · H10 reduced motion = no motion |
| I Responsive | I1 no page sideways scroll or clipping at 1920 / 1280 / 390 / 320 · I2 main action above the fold at 1280x800; 1920 not stretched · I3 phone: navigation reachable, thumb reach, nothing hover-only, text at least 12 px |
| J Motion | J1 token durations (100 / 150 / 200 / 240, exit 120), at most 240 ms · J2 every animation has a job, ease-out in, shorter ease-in out, nothing moves at idle · J3 only transform and opacity, CLS at most 0.1 · J4 at most 3 flashes a second, a pause for motion over 5 s |
| K Performance | K1 p75 LCP at most 2.5 s, INP 200 ms, CLS 0.1; first paint under 1 s · K2 old content stays while loading, no spinner over 1 s |
| L Words | L1 wording and banned-word tests green · L2 Helper, Evidence; the SX-18 bans the test misses; new nouns owner-approved · L3 sentence case, at most 25 words, no IDs, jargon or raw values · L4 errors say what happened and what to do, no blame, no "invalid" · L5 dates only through `UI.stamp` / `UI.clock` · L6 one word per thing everywhere |
| M Helper trust | M1 before a start: what, helper time, your time and cost in at most 3 lines · M2 evidence on the same screen as "Looks good" · M3 a plain timeline of what the helper did · M4 stop or undo visible at the decision and on the ticket |

### Checked automatically in CI

| Check | Items | Where |
|---|---|---|
| Master gallery at 1280, 390 and 320 px wide: no page sideways scroll | I1, H9 (width part) | `workspace/src/orch_ui/tests/ux_checks.cjs` (job `page-smoke`) |
| Every control at least 24x24 CSS px, or 24 px clear of the next one (WCAG 2.5.8; links inside a sentence exempt) | H5 (pointer part) | same |
| Every control reached with Tab shows a focus mark (outline or ring), first 60 Tab stops | H4 (mark part) | same |
| Every control has a name (text, `aria-label`, a label, `title`); an icon-only button needs `aria-label` | H6 (name part) | same |
| Keyboard path by real key presses: a modal dialog takes focus, keeps Tab and Shift+Tab inside with a focus mark, closes on Escape and gives focus back to its opener (or the menu button when the opener was a menu item); a menu opens with Enter, ArrowDown moves into it, Escape closes it with focus back on its button, Tab out closes it; arrow keys move between tabs and choose one | H3, H4 | same |
| With reduced motion asked for, no animation or transition still runs | H10 | same |
| Rendered text at least 4.5:1 (large 3:1) against the colour behind it | H1 | same |
| No console error, uncaught exception or failed request on the gallery and on every Insights and dashboard screen | (load health) | same, and `e2e/focus_insights_smoke.cjs` |
| A planted page with one fault of each kind must trip every check above (the checks cannot go blind) | — | `ux_checks.cjs --selftest` |
| Every text token on every surface 4.5:1; status text on its soft colour; text on filled buttons; control borders and the focus colour 3:1 on every surface | H1, H2 | `brand/tests/test_contrast.py` (job `brand`) |
| No new stylesheet, `<style>` block or hex colour outside the master | A1 | `scripts/check_style.py` |
| Wording and banned words | L1 | `brand/tests/test_wording.py`, `scripts/check_banned_words.py` |

Run them locally before the PR: `node workspace/src/orch_ui/tests/ux_checks.cjs` (needs `playwright` with a
Chromium) and `python -m pytest -q brand/tests`. A new master component shows up in the gallery and so is checked by
the first rows without any extra work.

### Checked by hand

- **By eye on the screenshots, every time:** A3-A6, B1, B3-B5, C1, C3, D1-D5, E1-E6, F1-F3, G2, G3, H4 (focus hidden
  under a sticky bar, toast or sheet), H8, I2, I3, J2, K2, L2-L4, L6, M1-M4. They need judgement or a real flow; no
  cheap test answers them.
- **Could be automated, not in CI yet (run by hand when the change touches them):** A2 (tokens only), B2 (one filled
  button), C2 (URL per view), F4 (`role=status`), G1 (labels and `autocomplete`), H3 (keyboard run, Escape), H5 touch
  44x44, H6 (axe-core, as in `e2e/full/web/stepper.mjs`), H7 (headings, landmarks), H9 200% text, J1, J3, J4, K1
  (Lighthouse or a DevTools trace), L5 (`UI.stamp` only). The automatic checks above run on the master gallery only;
  product pages and mockups are checked by these hand steps and the screenshots.

## Sweep rules SX-1..20 (14 Nov)

- SX-1 Content width: one column x=256 to 1240 at 1280, max 1200 centred at 1920 for reading pages, full-bleed only
  for board and tables; banners, notices, frames (Factory/Focus) and dialogs' backdrops obey the same edges (BP-01).
- SX-2 Type scale: 28/36 page title, 20/28 section and dialog title, 16/24 row and card title, 14/20 body, 13/18
  meta, 12/16 eyebrow and labels; monospace 13/20 only inside file previews and the terminal. Nothing else (BP-07).
  Today: question cards and completion notes at 20 px bold, tab counts at 11 px mono, "Updated" value at 16 px.
- SX-3 Spacing: 4-pt scale; 20 px card padding, 16 px row padding, 24 px between cards, 32 px between sections; the
  shell never shifts (F15) and the sidebar never scrolls at 800 px (F12).
- SX-4 Page header (UX round 15 Nov): h1 + one muted line (no eyebrow; a date goes into that line), actions right,
  flush to ONE right edge (`.page-heading` + `.page-heading-actions`); no in-page breadcrumb, no frame header.
  One top for every page (owner D1 A, 26 Nov, ORCH-2282): `UI.pageTop({title, text, back, settings, actions})` draws it
  for every page and add-on page; on the right Settings (outline) comes first, the page's one filled button last. A
  page inside another page (a ticket, New ticket, an add-on's settings, a Factory order) has `← <parent>` above its
  name (`.page-back`, `UI.pageBack`), the same on the computer and the phone. A switch or setting never sits in the top.
- Side menu (owner D2 A, 26 Nov, ORCH-2283): Home, Tickets, Review, Chat, Contacts, then Add-ons in one list without
  pins; `More (n)` / `Fewer` unfolds the rest in place (Lessons too), the page that is open always shows, and
  `Change this list` (at the end of the unfolded list) shows one switch per add-on, `Done` closes it. Topbar crumb = "Tickets › DT-4" only. Content starts at the same y on
  every page (`.page`, 32 px top). Two widths only: full (default, no max-width) and `.form-width` (`--form-width`,
  1024 px) for a form page such as Settings; both left-aligned. The top bar holds one outlined `New ticket`; the page's
  own main action is the only filled button. Phone mode while on = an outlined chip after the breadcrumb (menu),
  never a banner.
- SX-5 Buttons: Primary (one per page, counts the topbar), Secondary, Ghost, Danger; icon buttons have aria-labels;
  "Got it", pill buttons, underlined text actions, full-width outline buttons are deleted.
- SX-6 Selects and chevrons: one Select (36 px, border like inputs, SVG chevron), the same chevron on nav groups, ticket
  groups and the workspace switcher (fb26).
- Workspace switcher (ORCH-1273, owner picked draft A on 21 Nov): one menu with "On this computer" and "Saved places"
  (the person's own dashboards, relay and publish pages, kept in this browser by `places.js` of the dashboard). It
  lists other networks only because the person added them; the 8 Nov rule "a workspace in another network is never
  listed" is lifted. Add place, the keep question for places from a link and Share my places are steps inside the
  menu (`.sw-head` with a back arrow), never a dialog over it; the "…" menu of a row never covers another row.
- SX-7 Segmented and radio: one segmented control (raised surface = selected, ring = focus only) for List/Board,
  7/30/90 days, Every day…Custom, 4/8/12/24 h, All/People/Helper; one radio style (Sync rows, helper tools, "What a
  helper may do"); green fill is reserved for primary and toggles-on; a "Suggested" tag never fills.
- SX-8 Toggles: a toggle sits at the right end of a settings row with title + one-line description; a toggle that
  cannot work yet is disabled with the reason in the description (phone toggle).
- SX-9 Status icon set: SVG icons for To do / Working / Needs you / Check / Done used in pills, group headers, board
  columns, sidebar badges and the stepper (if it survives); no "!" "◇" "○" "✓" text glyphs; each status one colour
  (amber only for "needs you", live colour for Working, green for Done, neutral for To do and Check).
- SX-10 Empty state: one component ≤ 240 px tall: icon from the page's own icon, one sentence "what will appear and
  when", one secondary button; never inside a card with a title, never with search/filters above it, never twice on a
  page (Messages, Factory). `UI.state({action:{label, href, target}})` draws that button as a link when the next step
  is another page (gallery `#w-empty-link`); a filter or search that shows nothing offers Show all / Clear search.
- SX-11 Error state: same shape as SX-10 with the red dot: cause in plain words, the next step, one button that does
  it; technical text behind "Details" (Publish, Can't reach the workspace, sync "secret" error fb9).
- SX-12 Toasts and notices: toast = bottom right, 5 s, one visible, names the object, Undo where possible; error toast
  persists; page notices only for blocking states and only one, under the topbar, inside SX-1 width; system events
  (update started/finished) are toasts.
- SX-13 Dialogs: sizes S/M/L, one icon-only close, title 20/28, footer rule [tertiary] … [Cancel] [Primary]; info-only
  dialogs become inline text; the question card never opens a dialog.
- SX-14 List row: 40-48 px, one line, [status icon] title · owner avatar · one time fact · attention marker; the row is
  the click target, the single action appears on hover/focus and always in the group header; no "…" per row.
- SX-15 Card: 20 px padding, title 16/24, optional meta right (time only), one action in the footer row; cards hold
  previews or grouped content, never a single sentence (Autopilot off, Finished today, Insights empty).
- SX-16 Skeletons: every route and every add-on frame holds a skeleton shaped like its final layout within 100 ms
  (BP-61/62); it fades in only after 300 ms (`.skeleton-page`, `.skeleton-late` in motion.css), so a fast load never
  flashes grey and a slow one never shows a blank or jumps; never text + bars together (a small region uses skeleton
  lines with the words for screen readers only); "No items" only after loading finished (BP-56).
- SX-17 Motion tokens: hover/press 100 ms, open/close 150 ms (QA-09), page change 200 ms, panels 240 ms, enter
  ease-out / exit ease-in (BP-70), reduced-motion = instant; used by: route change, tab switch, dialog, list
  insert/remove (Home answered card), status pill change (one pulse), skeleton → content cross-fade.
- SX-18 Words: helper / step / result / ticket / schedule / phone / Review (status, ORCH-2140) / Test results (action, ORCH-2172) / Looks good
  · Send back; the person = chosen name (fb13); "agent", "artifact", "autopilot", "relay", "copy" (worktree), "Exact
  text", "Reference" are banned on level 1 (BP-78, F2, F3).
- SX-19 Dates: "today 10:32", "Mon 08:00", "14 Nov 2026, 10:32", 24 h, elapsed as "running 53 min" (F4, round-2 note).
  Built: `UI.stamp(value, {time:false, now})` and `UI.clock(value)` in `date.js` are the only way to write a date or time on a page (the dashboard's `date()`, `time()` and `DashHelpers.stamp` call the same rules). Never `toLocaleString`.
- Ticket header strip (14 Nov): `.strip` = one status pill (`UI.statusIcon`), the title, one sentence, one main action, then the tabs. No stepper. The helper is just "Helper"; the review state is always "Check" with "Looks good" / "Send back".
- Working ticket (ORCH-70, owner 16 Nov): `.strip.strip-plain` without a box; `.strip-kicker` above the `t-title`
  (key · helper pill · helper · minutes); one Watch live; Stop and the copy commands in the ⋯ menu; no helper bar.
- File cards (14 Nov, master since #1025): one `.file-tile` per file in a `.file-grid` (thumbnail, name, kind · size · date; gallery `#file-card`). A CSV thumbnail is a `.mini-table`, Markdown is rendered (`FileViewer.renderMd`). A toolbar (search, sort, cards/list) only above 6 files.
- SX-20 One source per count and status: sidebar badge = Home headline = Tickets group count; a newer system event

## Behaviour notes (owner feedback 14 Nov)

- Person block, look A (`.side-foot.person-row`, ORCH-1880): one row at the foot of the menu: the person (avatar, name, kit menu), then Phone, Settings and Documentation as icons with their words on hover. The menu: pick a person or Add person (name only). The chosen person is the actor of tickets and history lines made from the dashboard.
- Sign-in state (ORCH-850): a dot on the person's avatar (`.avatar>.dot`): green (`.dot.ok`) = "Signed in", grey = "View only" (with "A helper opened this page, so you can only look. To make changes, open orch yourself." when a helper started the dashboard). The words are the tooltip, the label and a screen-reader status. Read from `/api/session-state`, per browser.
- "Send questions to my phone" is shown only when a relay is set up and a phone is paired. The Shared links tab only exists once sharing is set up (the add-on stays in Settings > Add-ons).

## Reference: the 13 Nov shared visual system

The text below is the original system guide. Where it conflicts with the rules above, the rules above win.

# orch shared visual system

A calm workspace with enough information to make the next decision. Bring back old core's aligned rows, darker navigation, restrained cards and useful side panels. Keep the owner's plain language and remove technical decoration.

## Files and use

- (legacy name) the mockup `system.css`: standalone tokens, primitives, shell, states, result frames, motion and responsive rules. No imports or dependencies.
- `shell.html`: reusable app chrome with an intentionally empty `<main id="content" class="page">`. Copy the shell; set the active route's `aria-current="page"`. Its empty canvas is an integration slot, not a product empty state.
- `components.html`: complete visual reference with local examples, native controls, density switch, typed previews and Loaded / Loading / Empty / Error controls.
- `motion.html`: explicit Replay demos; all motion is idle until requested.
- `sample-*`: offline fixtures for the preview gallery. They are illustrative content, not product data.

Area pages use `<link rel="stylesheet" href="../system/system.css">`. Copy the same sidebar and topbar from shell.html. Do not change global tokens in an area stylesheet. Retain existing `btn`, `primary`, `outline`, `ghost`, `card`, `card-h`, `card-row`, `badge`, `chip`, `skeleton`, `nav-item`, `eyebrow`, `meta`, `page`, `topbar`, `sidebar`, `workspace`, `ws-switch`, `wsb`, `avatar`, `columns`, `stepper`, `ticket-stepper`, `progress`, `input`, `tabs`, `switch`, `menu`, `menu-pop`, `dialog`, `sheet` names. New classes describe their purpose rather than a page-specific appearance.

For the eventual restyle, load system.css after today's kit and page CSS, then remove conflicting page overrides rather than escalating specificity. This is a shared foundation, not a guarantee that every old page-specific selector has been replaced. New mockups only need system.css and their own layout rules. Never import the existing nested kit on top of this file.

## Token contract

| Role | Token / value | Rule |
|---|---|---|
| Canvas / navigation | `--bg #101216`, `--sidebar #0c0e11` | Navigation recedes; work remains central. |
| Card / raised / hover | `--surface #181b20`, `--surface-2 #20242b`, `--surface-3 #2a3038` | Cards are flat, overlays are raised. |
| Divider / interactive border | `--border #30363f`, `--border-strong #79838f` | Quiet dividers do not identify controls. Inputs use the strong border. |
| Text | `--text #edf0f3`, `--text-muted #b2bac5`, `--text-faint #a0aab6` | Primary, supporting, metadata. Never lower opacity for metadata. |
| Action | `--brand #61d5b8`, `--on-brand #092b23` | One teal accent; dark label on filled teal. |
| Working | `--working / --info #8fbef5` | Blue, `◉ Working`. No looping live dot. |
| Needs you / review | `--needs-you / --review / --warning #e5be72` | Amber, `! Needs you` or `◇ Ready for review`. Distinct words and symbols. |
| Done | `--done / --success #98cda3` | Green, `✓ Done`. |
| Paused | `--paused / --text-muted` | Neutral, `Ⅱ Paused`. |
| Failed | `--failed / --danger #f3a3a5` | Rose, `× Failed`; include a plain next action. |
| Type | 12/16, 13/18, 14/20, 16/24, 20/28, 28/36 px | Labels, metadata, body (buttons too), row title, section, page title: the SX-2 scale, nothing under 12 px. |
| Weight | 400 / 500 / 600 | Normal, emphasis, heading. No bold wall of text. |
| Spacing | 2, 4, 8, 12, 16, 24, 32, 40, 48, 64 px | Use scale for padding and gaps; 1 px borders are not spacing. |
| Shape | 8 px controls, 10 px cards, 12 px dialogs, round status pills | No nested rounded boxes for ordinary rows. |
| Elevation | `--lift-shadow`, `--shadow` | Menus, toast, dialog and sheet only. |
| Density | `--row-height:40px`, compact 32 px; `--card-padding:16px`, compact 12 px | Comfortable default, apply view-wide. |

Semantic hues are bounded to neutral, teal, blue, green, amber and rose. Status colours have similar perceptual lightness (Lab L* about 74–80), with matching dark fills. Do not introduce purple review, orange add-on labels or rainbow workspace navigation. Data charts reuse these colours with direct labels, never colour alone (BP-09, BP-12–17).

Computed sRGB contrast, before browser rendering: primary text on the lightest surface **11.63:1**, supporting **6.79:1**, quiet **5.65:1**; input border **3.46:1**; focus teal **7.42:1**; teal button label **8.48:1**; working / needs / done / failed badge pairs **6.65 / 7.25 / 6.81 / 6.73:1**. All normal text pairs exceed 4.5:1 and interactive boundaries exceed 3:1. Decorative card dividers are deliberately softer, since content grouping is also supplied by spacing and surfaces. Recheck contrast whenever introducing another background.

## Shell and navigation

One inverted L: sidebar plus topbar, at most one contextual detail panel (BP-02). Sidebar is 232 px at 1280 and 1920. Below 1280 it becomes a 64 px icon rail. Icons have accessible names and focus labels; nothing is mouse-only. The workspace switcher and ticket views use native disclosures, including a popout on the rail. The phone switch has an accessible full label. The person block is one row (look A, ORCH-1880); on the rail it stacks: the person keeps only its letter with its sign-in dot and opens its menu beside the rail, then Phone, Settings and Documentation as icons, so the rail never scrolls sideways (ORCH-1636, checked by `ux_checks.cjs`). At short heights the nav can scroll; the page never needs a forced desktop minimum width.

Core links: Home, Tickets, Review, Chat, Contacts (Notes live on Home). Below them the eyebrow "Add-ons": the add-ons the person pinned, then "Show more (n)" that unfolds the rest in place (ORCH-1184, owner picked draft A). Every add-on row has a pin button (`.nav-row` + `.nav-pin`, faint until the row is pointed at or focused, always shown on a phone, filled while pinned); nothing pinned yet = the first six. The open page stays in the menu even when it is not pinned. From 1280 px a button beside the orch name (`.side-toggle`) closes the menu to the 64 px icon rail (`.shell[data-side=rail]`) and opens it again; Show more on the closed rail opens the menu unfolded. Settings is anchored at the bottom. The default menu never scrolls at 1280x800; an unfolded Show more may. This preserves the full route map without eleven undifferentiated top-level destinations (BP-50). Ticket views are chips on the Tickets page (All, Needs me, Working, Done this week, + Save view), not a sidebar group (owner 14 Nov). In the application, the pins, Show more and the closed menu are kept in the browser (`orch.nav.pins`, `orch.nav.more`, `orch.nav.side`); these static pages deliberately do not store anything.

Only Home carries an attention count. Do not give every destination a badge. A ticket view query (`?view=needs-you`, `?view=working`, `?view=done-week`) is the proposed area contract. The board designer must implement those queries; the links are integration targets, not local filter implementations.

**Contacts is a core link** (no longer under Add-ons). It manages devices and workspace access. The bottom sidebar switch “Send questions to my phone” is a quick control, not a navigation shortcut. Settings contains notification preferences and the timeout, saved in place. Never give Settings a tab that silently redirects. If a Settings section needs device management, show an explicit link “Manage devices in Contacts →” while leaving the Settings section open (BP-47–49).

Topbar: current location and Chat / New ticket. These are navigation actions. The topbar Chat opens the same page as the sidebar Chat and carries the same name; never a second name for it such as "Ask the helper" (ORCH-299). Inside a decision view, make the decision its sole prominent action and style global New ticket as outline. Breadcrumbs only for nested pages: Tickets › Customer survey; current location is not a link (BP-24, BP-51). Demo new-ticket links use `../board/board.html?new=1`; area authors should wire that query to their composer. The shell intentionally has no active route until it is adopted by an area.

**Phone (up to 720 px, ORCH-73, owner 16 Nov).** One bottom bar replaces the side menu and the top bar: Home, Tickets, Review (the one needs-you number), More (opens the side menu, which brings the top bar and its actions back). Lists are short rows, never a squeezed table: render the table with `.wide-only` and the `UI.shortGroup` list with `.phone-only`. Every page fits 390 px and 320 px without sideways scroll.

## Layout at both desktop sizes

| Viewport | Sidebar | Page gutter | Reading layout | Work views |
|---|---:|---:|---|---|
| 1280×800 | 232 px | 24 px | 1000 px available; main + 296 px panel + 24 px gap | Board/table use all available width. |
| 1920×1080 | 232 px | 32 px | Content max 1280 px, centered; 320 px panel | Board/table/analytics `.page.wide` use available width. |
| 900–1279 | 64 px rail | 24 px | Panel 256 px; 16 px gap | Controls wrap; never squash text to 11 px. |
| Under 900 | 64 px rail | 16 px | Context panel stacks below content | Local table overflow allowed; no body overflow. |
| Under 600 | 64 px rail | 16 px | Single-column cards and previews | Topbar wraps and stops being sticky. |

Use `.columns` for story + properties; `.grid-2` for equal samples; `.grid-3` for three short units; `.grid-2.grid-wide-3` moves to three columns at 1600+. Do not add a third story column just because the screen is wide. Prose is capped at `76ch` using `.reading`, below the ~90-character ceiling. A board may retain five status columns when each fits at least 180 px; otherwise use a local horizontal board track or switch to the list, never body overflow. Every column has a count; empty columns say “None” (BP-01, BP-20).

For ticket lists use `.page.list-page`, a one-line header, one 32 px toolbar, 8 px gaps, a 32 px table head, then 40 px rows. Budget at 1280×800: 56 chrome + 16 top pad + 36 heading + 8 + 32 toolbar + 8 + 32 table head + 15×40 rows = **788 px**. Extra subtitles or banners reduce that capacity; put the summary beside the title and don't stack filter bars. Compact gives 32 px rows. The shared gallery demonstrates the row sizes with four representative rows; the consuming list must validate the fifteen-row target (BP-04, BP-82).

## Components and usage

- **Buttons:** `.btn.primary` for the next decision; `.outline` for alternatives, `.secondary` for a low-emphasis filled action, `.ghost` for details, `.danger` only for a named destructive action. Default 36 px; sm 32, xs 24, lg 40. Icon buttons require a full accessible name. At most three toolbar actions before selection (BP-11, BP-23, BP-76).
- **Inputs:** persistent label, hint underneath; `aria-invalid` and `aria-describedby` for errors. Placeholders never replace labels. Native select / checkbox / radio are deliberate. A checkbox styled `.switch` represents a boolean preference.
- **Segments / tabs:** segments switch a view or local setting; tabs switch a section within the same context. Native radio segments work without script. Real tabs need `tablist`, `tab`, `tabpanel`, selected state, roving focus and arrow keys, as implemented in motion.html. A section-link nav remains ordinary links (components.html).
- **Status:** one status phrase per unit, never the same status in header, banner and footer. A board column can supply the status label to its cards; do not repeat it just to add colour. A standalone card uses the labelled badge. Owner, one time fact and an optional preview complete the card. No IDs or technical chips.
- **Rows versus cards:** use rows for a collection, cards for a result preview, a decision or a genuinely separate group. Rows share one outer frame, not a card per line. Cards have no shadow. Compact applies to cards as well as rows. Use `data-density="compact"` on the view or native radios inside `.density-scope`. `<html data-density="desktop">` gives a mouse screen (721 px and wider, hover) 32 px buttons and 36 px inputs; touch screens keep 44 px. The workspace badge (`.wsb.s16/s26/s32/s46` with `data-c`), the look picker (`.lk-*`) and the sidebar switcher (`.ws-switch`, `.sw-menu`) live in `widgets.css` (gallery: "Workspace look").
- **Avatars / helper chips:** initial or helper symbol plus visible name. A lone initial does not identify responsibility. No decorative stacks of avatars.
- **Changed lines on a card (diff):** `UI.docBox` shows `diff` lines as added (green) and removed (red tint), a file's name above its lines, and a risky added line marked red with a short reason pill (`risk`, ORCH-429: the CI workflow Merge card). Red means "look at this", never decoration; at most 30 lines, the rest behind the card's link.
- **Progress:** known steps use a labelled count and 4 px bar, or the four-stage stepper. Do not invent percentages for open-ended work. Announce meaningful stage changes, not every tick. Long jobs show elapsed time, current action and Leave running / Cancel (BP-63).
- **Side panel:** editable owner, due and definition of done. Keep extra properties under one Details disclosure. Production edits save immediately, with rollback on failure and Undo where appropriate (BP-28).
- **Menus / tooltips:** native details for simple menu disclosures; normal links/buttons retain natural keyboard navigation. These are not ARIA application menus. Close on Escape as shown; application click-away handling may be added. Tooltips only reinforce shortcuts, never explain a primary label.
- **Dialog / sheet:** native `showModal()` supplies focus containment, Escape dismissal and focus restoration; safe action gets autofocus. Do not nest dialogs. Use one sheet over the current ticket for preview; retain underlying scroll. Closing starts at once (120 ms exit, nothing to wait for) and focus goes back to the opener when it is really closed.
- **Toast:** one visible at a time, 5 seconds for success, with Undo or Open for meaningful changes. Queue in the application; the reference replay replaces the previous demo toast. Error toasts persist until dismissed; blocking errors also stay by their source. Never disappear a focused toast action in the application: pause the timer while hovered/focused (BP-58).
- **Fingerprint and contact trust (ORCH-1203):** `.fingerprint` is always 8 groups of 4 in two rows of four, the same pattern on both sides (`.lg` to compare, `.sm` in a table). A contact that needs an Accept is a `.card.trust-ask` (`data-tone` warn or bad): state badge with icon and word, one line why, the check line right above the fingerprint, the name field and Accept right below. A new key without the old one gets the careful Accept (outline, empty name, one warning line). `.trust-layout` puts this workspace's own fingerprint beside them and the rest in a table; under 1280 px it stacks asks, own, others. Gallery: Fingerprint and contact trust.

## Information density rules

Two levels only. Level 1 answers “What is happening, why does it matter, what can I do?” Level 2 is one click away. Maximum seven facts per card/header, five KPIs. No nested Details inside Details (BP-18, BP-79–82).

| Page type | Visible at a glance | Behind one click |
|---|---|---|
| Home | Needs-you count, each item's title, reason, one action; working count. Needs-you first. | Finished work, full result, older history. All-clear includes last three finished items. |
| Board / list | Title, status, named person/helper, one update/ETA fact, attention reason when needed, at most one 64 px result thumbnail. | Description, steps, full file set, properties. A peek retains selected row and scroll. |
| Ticket detail | Title, status, who, next action, reason if blocked, elapsed/ETA. Story: request → steps → results → next step. | Raw timestamps, IDs, costs and logs in Details. History defaults to three events; completed steps one line each. |
| Focus | Current step, who is working, elapsed time, steps completed, latest result and the one action needed. | Full transcript, logs, older steps. Updates do not steal scroll; show “N new” when reading earlier work. |
| Insights | 3–5 meaningful KPIs with period deltas; 1–2 labelled charts; one shared time-range control. | Breakdown tables, individual helpers, raw values. No empty chart shell or fake zero. |
| Automation | What will happen, next time, on/off state, last outcome, action for a failure. | Schedule rule, older runs and advanced conditions. |
| Notes / chat | Note title or conversation, useful excerpt, author/helper, last change; the current message and reply action. | Earlier conversation, file collection, source details. Preview attached files in context. |
| Sync / Shared links / Contacts | Connection or sharing state, destination/person, last success, next needed action. | Storage path, technical connection facts, detailed history and advanced sharing options. Never put secrets in a preview. |
| Settings | Workspace name, helpers, notifications, dark appearance, access. Save feedback in place. | Technical and advanced settings under one “More settings” heading at the end of the tab, shown plainly (no fold, ORCH-1693). No redirecting tabs. |
| Results | Typed visual preview, name, type, size, age; Open / Download / Copy link. | Full viewer, source view, remaining files. |

## File and result previews (BP-30–37)

Every type gets a real, useful representation, not merely a filename. `.preview-body` reserves 192 px in the reference collection; area pages can use `aspect-ratio` for their known media dimensions. Board thumbnails are at least 64×64. One file gets a larger inline frame; more than six files gets six thumbnails plus a “+N more files” tile and a type filter. The reference gallery deliberately shows all types at once for inspection.

| Type | Preview | Full view / fallback |
|---|---|---|
| Image | Contained thumbnail, informative alt text | Sheet/lightbox; fit/zoom; Escape closes. SVG sample is local and contains no script. |
| PDF | Actual local PDF object, first page | Browser PDF viewer / download. Browsers without inline PDF show the summary and explicit fallback. Production uses a first-page thumbnail to avoid embedded browser toolbars. |
| HTML | Local page in `<iframe sandbox>` with no permissions | Full separate page; never allow scripts and same-origin together. Production content must remain isolated. |
| CSV / XLSX | Header, row numbers, column selector and rendered cells | Same frame for parsed XLSX. CSV parsing beyond 512 KB: partial rows + Download full file. XLSX parsing is an application responsibility. |
| Markdown | Rendered heading, paragraphs and list | One Show source disclosure; long documents can open separately. |
| Code / JSON | Highlighted tokens, line numbers and folded extra content | Full source one click away, wrap or local horizontal scroll. |
| Text | Wrapped monospace excerpt | Full text open/download. |
| Audio / video | Native controls with a local playable sample; duration | Browser-supported playback, no autoplay; unsupported codecs show download fallback. |
| Unknown / binary | Type glyph, name, size, age and explanation | Download; never an endless loader. |

Every preview uses **Open, Download, Copy link**, in that order, always visible and keyboard reachable; Share can follow when relevant. `file://` clipboard access varies, so Copy link announces a fallback if unavailable. In the app use stable share URLs rather than file URLs. A static single-file sheet demonstrates the frame; multi-file sheets must add previous/next buttons, Left/Right keys and a file position label, and preserve their state in the URL (BP-32, BP-54).

Above a 10 MB browser-render budget, show a bounded first-page/first-rows preview with an explicit partial-preview sentence. Limits are defaults to validate per renderer, not claims that every type uses the same parser. Failure keeps the same frame and says “Can’t preview this file” with Download. Do not expose raw renderer errors. Never insert untrusted HTML into the main document.

### Result widgets (ORCH-263)
Use `UI.result` for anything a helper hands back, on Focus and on ticket pages alike; do not build a page-local card.
Small (168 px high) is a glance and the whole card opens the overlay; big sits on a ticket page with Download and Open
big in its head; the overlay shows one result large. A plain link is a row that opens in a new tab and never gets an
overlay. States: empty says what is missing in one sentence, loading keeps the shape (skeleton, `aria-busy`), error
says "Can't preview this file." with Try again and Download, too big says so and shows the first part
(`item.shown`) or, for media, only the sentence. Text goes in with `textContent` only; a web page only in an
`<iframe sandbox="">`.

### Live bar (ORCH-337, ORCH-2198)
`.lbar` is the one row under every dashboard page while the new Focus is in Preview (dashboard `pages/livebar.js`).
It holds the page's name, one **Helpers** menu button (`.lbar-helpers`) and New: no chips, no counts in the row
(owner pick J b, 26 Nov: calmer). The button shows an orange ◆ when something needs you, never a number (the number is
on the Review badge). The menu (`.lbar-pop`) lists every session in groups (`.lbar-gh`, heading and count): Needs you,
Working, Quiet (in line and idle); each `.lbar-row` has its symbol, key, name and "Open", opens its pane, and has More
(Stop, End). A pinned session comes first in its group; an open one is marked (`aria-current`). Search from 9
sessions. The menu opens inside the window on the side of the bar with room (`data-at` above or below: below when the
bar sits at the top in full screen) and scrolls there. On a phone New is an icon (`data-fold` 3), above the tab bar.
The pinned mark is the `pinned` icon (a thumbtack); `pin` is a place.
At its right end **New** opens a `.live-pop` of four `.live-opt` choices for a session without a ticket (Empty helper,
Chat helper, Plain terminal, Manager), each a `.live-opt-t`: the name, then what it does as `.meta`; one already open
says "Already open: go to it". The same four are buttons at the top of Focus. A new one is pinned (ORCH-364).

### Live wall (ORCH-360)
`.wall` is the new Focus page in Preview (dashboard `pages/livewall.js`): one summary line ("3 need you · 4 working ·
9 in line · 8 idle", then "24 sessions"), a filter, then bands that fold (`.wall-band`, `.wall-bt` with
`aria-expanded`): Pinned, Needs you and working, In line, Idle and no session. Needs you and working are tiles
(`.wall-tile`); a needs-you tile is orange (`data-s=needs-you`) and comes first, its sentence is the question and it
has no peek. A working tile shows a peek of its last three lines (`.wall-peek`). In line and idle are one line each
(`.wall-line`). From 12 sessions the bands carry `data-many` and a long list scrolls inside itself; at 1100 px and wider
the bands sit side by side. A tile opens its session in the layer; nothing is answered on the wall itself.
The filter finds a session by its key, name, title and the words on its tile ("Check", "Idle"); one that sits in Needs
you is also found by "Needs you" (ORCH-2045). The summary keeps counting the whole workspace, and with a filter a band
without a match is left out. Typing only filters: nothing is sent or started.
A search opens a folded band that holds a match for as long as the search runs (`aria-expanded` says what is on
screen); a fold click during a search counts for that search only, and clearing it brings back the saved folds
(ORCH-2063). The filter sits between the summary and the bands in the page order too, so Tab goes from it to the first
match. A one-line title that is too long ends in an ellipsis.

### Pin and rename (ORCH-361)
Every wall tile and line has a pin button (`btn icon sm ghost`, the `pinned` icon, `aria-pressed`); a pinned session
moves to the Pinned band, gets a chip in the bar and comes first in the layer. A session without a ticket starts
pinned. The selected pane's title is a button ("Click to rename"): it turns into `.live-ren`, one `.input` (60
characters at most) and Save name; Enter keeps it, Esc leaves it. The own name shows on the tile, the pane and the chip
(a chip shows the own name, else the ticket key); an empty name goes back to the title. Pins and names are kept by orch
for the workspace, so every browser shows the same.

### Live groups (ORCH-345)
An epic or a factory order whose helpers work on its sub-tickets is ONE tree, `.gtree`, in three modes
(`data-mode`): `preview` on its wall tile (`.wall-tile[data-group]`: "5 helpers · 2 small helpers · 1 needs you", the
first five rows), `tree` beside a pane (`.live-gwrap`: the switcher left, the session right) and `strip` (one line that
scrolls inside itself) when the pane is narrow (`.live-pane[data-narrow]`: split, right side, phone). Rows are
`.gtree-row` in `li[data-depth]` with a solid guide line; a small helper's row (`li[data-small]`) has a dashed guide and
a dashed `.chip.gtree-tag` "Small helper", says "watch only" and opens its helper. Only "Main helper" and "Small helper"
carry a tag. The selected row is `aria-current` (brand edge), a helper that needs you is orange (`data-s=needs-you`).
A helper that needs you turns the whole tile orange. The pane's message box (`.live-msg`) starts with `.live-to`:
"Message to: Write the texts (ORCH-301). Only this helper gets it." In the bar's Helpers menu the group is one row with
the helper count (`.lbar-n`), the same number as its tile.

### Chat view of a session (ORCH-687)
A ticket's pane has Chat | Terminal in its header (`.segmented.live-view`, `aria-pressed`; in a narrow pane "Show
terminal" / "Show chat" in More). Chat is the default and the choice is kept per browser. `.live-chat` (`role=log`) is
the ticket read as a conversation, oldest first: a done step and other events are one muted line (`.live-ev`, "✓ Step 2
done: … · 14:21"); the helper's words are `.live-chat-msg` on the left (`surface-2`), your words on the right
(`data-w=y`, `brand-soft`), each with "Helper · 14:38" or "You · 14:55" above, and its links (`.live-links`) inside.
The waiting question is never a message: it is the orange card (`.live-ask`, `needs-you` edge, `warning-soft`) above
the chat, answered there with its options or own words.

### Role page: a ticket that runs by itself (ORCH-827)
A ticket with a repeat (draft A2, picked by the owner on ORCH-812) has the chip "↻ Runs by itself" in the kicker, Run
now and Pause (Turn on while paused) in the header, and the tabs Overview · Runs · Schedule · Chat · Files. Overview:
"Its job" (two sentences, Full instructions in a `.disclosure`), the last run as a run card (`.role-run`), the next
run as a strip (`.role-strip` with `.role-fact` blocks). Runs: one `.role-run-row` per run (a `details` whose summary is
a `.card-row`: dot, "Run 7 · not finished", "today 12:01 · 7 min · $1.11", Details), opening `.role-run-detail` in
place. Schedule: `.setting-row`s, each changed by one click. Chat (`.role-chat`): the `.live-chat` thread with each run
as a run card, the person's notes as their messages, a question as the orange card, and the box `.role-say` ("Tell it
something for the next run") with `.role-say-hint` under it. Skipped runs say "no cost"; numbers nobody measured say
"unknown", never 0.

### Terminal (ORCH-744)
`.term` is the helper's real screen wherever a page shows it (the new Focus pane in Terminal view, dashboard
`pages/liveterm.js`, fed by the terminal bridge's stream). One line on top says what you can do now ("Watching ·
select text to copy it", "Typing: your keys go to the helper · Shift+Tab stops", "Watching only · typing is off in
Settings"; when the page gives the switch's address it says only "Watching only" beside a **Turn typing on** link to it), then **Let me type** (a `.switch`, shown only when the workspace allows typing) and Copy (the selection,
else all of the terminal's text). Typing on gives the box a brand edge and a blinking cursor (still with reduced
motion). Nothing goes out while watching; a paste with a line end shows `.term-ask` ("Paste 3 lines into the helper's
screen?" Paste / Cancel) first; Ctrl+C or Cmd+C with a selection copies. The screen is xterm.js on a canvas (WebGL,
loaded before the terminal opens so no inline style is added); its colours are read from the tokens. A program's
clipboard writes and title changes are ignored; links open only for http and https, with noopener. While watching the
screen keeps the helper's size and scrolls; while typing it follows its box. States: loading (skeleton), live,
reconnecting (the last screen stays, typing off until the person turns it on again), typing off, closed, no screen
(one sentence why), no WebGL (one sentence, the chat view instead).

### The helper's browser, live (ORCH-1493)
`.bview` shows screen pictures of the helper's browser wherever a page shows it.
One line on top says what you see ("Helper is driving", "Connection lost. Trying again…") and, when the
picture is older than 10 seconds, "Last change 30 s ago" (a quiet page is still live, never "lost"); Stop sits at
the end of that line. The tabs show as a row when there are two or more, the current one filled. What the browser
stopped or closed (a page message, a file request, a download, a new tab) shows as a `.bview-card` above the
picture, the site's own words in quotes as plain text, at most three; answer buttons never sit inside the picture.
States: connecting and connection lost (the last picture stays, greyed), live, ended (one sentence why), no browser.
The picture is drawn from JPEG frames, newest first; nothing is kept after the view closes.
Places (ORCH-1494, the owner's pick "Use A" on ORCH-1341): the small live preview `.bpeek` (`UI.browserPeek`) is the
one way in. It sits on top of the ticket's Activity, in the Focus pane (under what the helper does now), between the
ticket chat and its message box, and on the Browser page (the add-on's tab, `wide`); in the Focus pane and the chat it is `compact` (one row). It is a button: a small picture
(at most one new one every 1.5 s), "The helper is browsing <site>", the newest time, one "Helper is driving" pill,
"Open". A click opens the live view in the ticket next to the steps (`#ticket/<id>?browser=open`; on the ticket it
opens in place and the preview gets the brand edge); there is no header button. An ended browser is one quiet line,
"The helper's browser ended at 14:20.", for a day; no browser shows nothing. In the ticket the view sits in
`.bview-beside` (side by side from 960 px of column, else on top of the steps) with Stop and Hide in its bar. On a
touch screen the picture is the real 1280-wide page scaled to the width: pinch to zoom (1 to 4 times, it never leaves
its box), one finger moves it, a double tap goes back; Ctrl + wheel does the same on a computer. The Browser page
lists "Live now" (a card per ticket: its title, then its wide preview) and "Ended today" (links to the tickets with
the time), else one empty state. Home shows nothing of it in watch-only.
Take over and give back (ORCH-1495, desktop first; a phone may tap and pinch): `UI.browserView({control})` adds
"Take over" (outline) to the line on top and one owner bar `.bview-ctl` above it (CSS order; `role=status` line, at
most one filled button). Finishing (the helper ends its step first): spinner, "The helper is finishing its step…
Then you are in control." with "Stop its step now". In control: the view fills the window (`.bview[data-full=true]`,
above the dock and the live bar; on a phone the bar sits at the bottom), `brand-soft` bar: "You are in control. The
helper is paused. What you type goes to the site, not to orch.", under it "When you give back, the helper starts on a fresh page and can see what the site itself shows (for example your sign-in or recent searches); orch kept nothing you typed." and "Keys go to the site. F6 moves to these buttons.";
buttons Give back to the helper (filled), Back to the ticket (the person keeps control, the view goes back in place
with "Full view"), Stop browser. Keyboard focus goes to the picture; Esc goes to the site and never gives back.
Paused (the page that had control went away, for example the ticket is opened again later): "The helper is paused.
Nobody is in control…", under it the same "When you give back, the helper starts on a fresh page…" line as in
control (ORCH-1858), with Give back and Take over again; opening the paused view takes or gives nothing. Another page in control: one line, no buttons. The helper asking (`orch browse ask-person`): the bar on
`warning-soft`, "The helper needs you in its browser." with its words and one Take over; the small preview says
"Waiting for you" with the words, and Home shows one `banner attn` line with "Open the browser".

### Voice into the message box (ORCH-696)
Only while the relay is on: a microphone (`btn icon sm ghost`, "Speak") sits in `.live-msg-row` between the words and
Send. While listening `.live-voice` (`role=status`, `surface-2`, `r1`) above the row shows a moving level
(`.live-voice-wave`, still with reduced motion), "Listening 0:04", Stop and Cancel; Esc cancels and the microphone is
hidden. Then "Writing down your words…", then the words land in the box and `.live-vhint` under it says "From your
voice. Check the words, change what is wrong, then send." (gone on the first key). Nothing is sent by itself. A
refusal (microphone blocked, nothing heard, the relay said no) is one plain sentence in the same place (`role=alert`).
The recording itself is `UI.voiceRecorder` (composer.js) with `words:false`, its own controls drawn by the page.

## Loading, errors and performance

The brief asks for shell + skeleton within 100 ms while the numeric checklist says not to show indicators for sub-second work. Reconcile by expected latency (BP-05, BP-55–67):

1. Cached/warm/local: retain content; commit the update immediately, no skeleton or spinner.
2. Known cold/slow route (expected >1 second): show persistent chrome and the correctly shaped skeleton within 100 ms. If latency is unknown and the request is still pending at 1 second, show the reserved loading frame then. Never flash an empty state first.
3. Initial large areas: skeletons match final row heights, card blocks, header lines and media ratio. Mark the region `aria-busy="true"`; hide decorative skeletons from assistive technology; give a polite loading/completion message. Use one coherent indicator per region, not a spinner in every card.
4. Module/action lasting 2–10 seconds: inline spinner within the same button width, with a visible “Saving…” label. Whole-page spinners are not an option.
5. Over 10 seconds: current step + elapsed or real determinate progress, and cancel/background action. Do not loop a skeleton for a helper's entire job.
6. Refresh: keep old data, refresh in place, quietly update “Updated … ago”. Do not blank the page, jump the scroll, or shimmer over existing results.
7. Empty is a settled response: explain what appears, how to start, and provide an action. Errors stay near the source with Retry; codes only in Details.

Production targets: local feedback <100 ms; warm route <300 ms; cold data route <1 s where practical; FCP ≤1.8 s, LCP ≤2.5 s, INP ≤200 ms, CLS ≤0.1. API reads p50 <150 ms/p95 <500 ms; small writes optimistic immediately with confirmation <1 s. Prefetch on focus/65 ms hover, skipping Save-Data and slow connections. Persist view, selection, filter and time range in the URL; restore scroll on Back. None of these runtime or network metrics is claimed as measured by this static deliverable.

## Motion contract (BP-69–74)

| Motion | Duration | Curve / rule |
|---|---:|---|
| Hover / press / toggle | 100 ms | `--ease-move: cubic-bezier(.4,0,0,1)`; press translates 1 px. |
| Menu / popover | 150 ms | `--ease-enter: cubic-bezier(0,.4,0,1)`; only enter. |
| Explicit first-page entry | 150 ms | Enter, 4 px travel + fade. Opt-in `.page-enter`, never on refresh. |
| Add / remove a row | 120 / 100 ms | Enter / exit; no stagger. Apply actual removal after exit; reduced motion removes instantly. |
| Tab switch | 0 ms | Immediate, preserve panel geometry. |
| Dialog / side panel | 200 / 240 ms enter, 120 ms exit | Enter; 8 / 24 px travel. Exit with `--dur-exit`; focus goes back after the close. |
| Toast | 200 ms enter / 120 ms exit | Enter / `--ease-exit: cubic-bezier(.6,0,.8,.6)`. |
| Progress | 150 ms | Move; label changes immediately. |
| Status | 200 ms once | Subtle border pulse; no persistent movement. |
| Skeleton | 1600 ms | Low-contrast shimmer only under `[aria-busy=true]`. Instant content swap. |
| Grow / move into place (Focus zoom, pin, split) | 240 ms | `orch.flip(el, fromRect)`: from where it was to where it is, transform + opacity, `--ease-move`; `{scale:false}` only slides. Only after a person's action, never on a data refresh. |
| Focus layer closes | 120 ms | `orch.leave(el, rect, host)`: the old panel fades and drops 8 px where it was, `--ease-exit`, inert, then goes. |

**Conflict resolved:** the system brief explicitly requests a 150 ms page transition; BP-71 prohibits fading every route. The class and Replay example exist but are opt-in for first entry only. Routine navigation has no page fade. Skeleton-to-content and numbers never animate. A reorder in the real app should use FLIP on the moved item only (120 ms), not animate the entire list.

One focal animation at a time, no input blocked by animation. `prefers-reduced-motion: reduce` disables every transition, pulse, shimmer and transform animation; all controls still change state. No ambient movement at idle. The motion page's separate Replay controls are independent experiments, not an instruction to run every animation together.

Durations come from the `--dur-*` tokens (never above 240 ms for a one-shot; only endless loops such as spinners and shimmer use longer). `interaction.css` carries the one global `prefers-reduced-motion` rule that zeroes every animation and transition duration. Checks: `brand/tests/test_motion_lint.py` (static) and the reduced-motion step of `workspace/src/orch_ui/tests/ux_checks.cjs` (H10, in the browser).

## Accessibility and interaction contract

Skip link; semantic landmarks; ordered headings; named icon buttons; visible 2 px focus with 3 px offset; no clipped focus rings on ordinary cards. Native radio, checkbox, disclosure, select and dialog behaviours are intentional. Status has readable words and a symbol (BP-15, BP-75–77). Toolbar controls are normally 32–40 px, never below 24×24. No essential hover-only controls. In forced-colours mode, buttons/status boundaries and focus remain visible.

Layers and overlays (ORCH-1360): anything fixed over the page (the Focus layer and bar) keeps the page's room for itself
(`--live-pad`, and `scroll-padding-bottom` on the root so Tab scrolls the next link clear of it); a full-screen layer makes
the page and the side menu inert. Something only shown behind (the cards under a review card) is `aria-hidden` and inert.
A focusable resize grip (`role=separator`) says `aria-valuemin`, `aria-valuemax` and `aria-valuenow`. A box that
scrolls has something focusable in it or is focusable itself. `UI.progress(value, max, unit, label)` names its bar
(default "Progress"). Faded, not-picked options keep 4.5:1 text; a chip you can click is 24 px tall; a link inside text
is underlined.

The consuming application must supply the full command palette and keyboard routes: Cmd/Ctrl+K toggles search, Escape closes, G-then-letter routes, ? shortcut help, arrows/J/K for lists, Enter opens (BP-52–54). The static shell does not advertise a search control that cannot work. Add shortcuts progressively and never intercept typing inside fields. URL persistence, optimistic updates, toast queues and multi-file viewer navigation are integration behaviours, not implemented backend features here.

## Copy rules

Sentence case. Familiar nouns: helper, step, result, file, needs you, ready for review. Actions name the outcome: “Accept result”, “Ask for changes”, “Download file”. No “OK”, “Submit”, raw IDs, branch names, vendor names or unexplained abbreviations in default content. If connection details genuinely require it, say “private network”, and keep technical explanation in Details. A primary label should never need a tooltip. Use one useful sentence before a long list (BP-08, BP-11, BP-78, BP-80–81).

## What changed vs today and why

- Larger page titles and consistent body text make the main point easier to find.
- Compact, aligned rows put useful work on screen without making text smaller.
- Cards group decisions and previews instead of putting every line in its own box.
- Status always has a word and a symbol, so colour is never the only clue.
- Teal marks actions; quieter status colours keep the whole page from competing for attention.
- Each work item shows who is responsible and one useful time fact.
- Files show real content, with the same three actions in every preview.
- Loading, empty and failed states look different and keep the same space.
- Contacts has one clear home; Settings no longer disguises a page jump as a tab.
- Short, optional motion explains changes, while reduced-motion settings are respected throughout.
- Wide screens get useful columns; reading lines stay a comfortable length.
- Technical details move one click away, leaving plain-language summaries in view.

## Validation and handoff

Reviewed the supplied screenshots, brief, checklist, old-core token source, current tokens/components/motion, current style/look/page styles and rendered HTML structure. No challenge findings or owner feedback files were present during this pass. Do not infer approval from their absence.

Static validation covers HTML structure/local references, JS syntax, CSS token references and calculated contrast. The manager must capture shell/components at 1280×800 and 1920×1080, check the rail at 1024 and stacking below 900, Tab through dialogs/previews, test reduced motion and measure the actual application's performance. No browser was run, and no runtime accessibility, CLS or Web Vitals pass is claimed. Area authors should cite BP rules above when diverging from the reference and keep the same tokens and chrome.


## Working shared components — 13 Nov revision

Load `interaction.css` after page styles and load `overlay.js`, `select.js`, `date.js`, and `components.js` before page scripts. Keep `preview-controls.js` at the end of each shell page.

- Native `dialog.showModal()` and `dialog.close()` use one shared lifecycle: close button, Escape, backdrop, focus containment and restoration, scroll lock, 150 ms entry / `--dur-exit` (120 ms) exit. Reduced motion is instant. `await orch.close(dialog)` (= `UI.overlay.close`, = `dialog.close()`) settles only after the native close, the stack pop, the scroll unlock and the focus return, so the next line can open another dialog or read `document.activeElement`. Repeated closes share one promise; reopening during the exit cancels it. Tab pressed during the exit is replayed on the page, never inside the fading dialog. Focus goes to the opener; if it left the page, to the control with the same `data-key`/`id`, else the control that was next to it, else the nearest container. Never add page delays around a close. `UI.fullscreen(element, opener)` moves existing content into that same lifecycle and restores it on close.
- Native selects are enhanced automatically, including dynamic controls. They retain their form values and change events. Use `data-prefix="Sort"` for labels inside the trigger and `UI.select.sync()` after programmatic value changes outside click/change/reset handlers. Type to jump works like a native select (ORCH-2051): keys typed within 1 s form one prefix (a whole key such as SALES-097), one letter again cycles, Escape closes without choosing; typing only moves focus, Enter, Space or a click chooses. Focus given to the hidden native select goes to the trigger. Open choices wrap to show their whole text; the trigger edge is `--input`.
- `UI.toast(message, undo)` and `UI.copy(url)` provide one notification pattern. Details menus with `.menu` and ARIA tablists get shared keyboard behaviour. Page handlers may update domain content, but should not add separate keyboard or overlay lifecycles.
- `UI.date(valueInput, trigger, oldCalendar)` provides the shared calendar. `UI.question.render(host, config)` provides recommended choices, custom input, answered state and Undo. `UI.phone()` opens demo pairing and the same question component in a phone frame.
- `gallery.html` is the clickable source of truth. Each example has a state selector and a usage note. `COMPONENT-QA.md` records the audit and browser results.
