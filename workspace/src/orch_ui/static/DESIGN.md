# orch design system: the one master

This folder (`workspace/src/orch_ui/static/`) is the single component library and style guide for the dashboard, every add-on page and every mockup page. Open `gallery.html` (served at `/styleguide` by the dashboard, also at `/kit/gallery.html`, and opened from Settings, About) to see every component in every state with motion Replay.

## The rules (owner, 14 Nov 2026)

1. Build on the master. Use existing components and tokens; never write a page-local look, a copied kit file or a new "system" sheet.
2. Need something missing? Add it here first: (a) the component in `widgets.css` / `widgets.js` (or the file it belongs to), (b) an entry in `gallery.html` / `gallery.js` with its states (default, loading, empty, error where they apply), (c) a test in `workspace/tests/test_orch_ui_kit.py` if it adds a file, then use it from the page.
3. Mockup pages link these files by relative path (`../../../../workspace/src/orch_ui/static/...`); the mockup folder keeps no stylesheet of its own.
4. Owner wording rules: one click, no typed words; minimal plain words; no "Details" / "Technical details" toggles (show the detail plainly lower down); no "NetBird" (say "private network"). Old reference examples below that show a Details disclosure are legacy and must not be copied.
5. Never change tokens in a page. Colour and size tokens come from `brand/tokens.json` via `brand/gen_tokens.py` (`tokens.css` is generated).

## Files

| File | What |
|---|---|
| `tokens.css` | Generated tokens: colour, type, spacing, shape, motion durations and easings. |
| `components.css` | Shell, sidebar, topbar, page, card, button, input, badge, chip, table, tabs, segmented, progress, empty/error, skeleton, tooltip, toast, dialog, sheet, menu, the one `.chev` chevron. |
| `widgets.css`, `widgets.js` | Added 14 Nov: status icon set, pill, empty/error/loading state, stat tile, labelled progress, sortable table, `data-tip` tooltip, sheet, dialog S/M/L, strip, board, file card, type utilities. `UI.statusIcon`, `UI.state`, `UI.stat`, `UI.progress`, `UI.table`, `UI.sheet`, `UI.chevron`. |
| `review.js`, `review.html`, `review-boot.js` | Review stack (15 Nov): `UI.reviewPage` (Waiting deck on `UI.swipeDeck` + Answered list), `UI.answerRecord` and `UI.appliesNow` (answers under a ticket's questions), `UI.reviewFetchApi` (same-origin api of the page `orch review` serves). `review.html` is that page, `review-boot.js` signs in from the `#t=` fragment and starts it. Voice in the deck only with `voice:true`. |
| `interaction.css`, `overlay.js`, `select.js`, `date.js`, `components.js` | Dialog lifecycle, custom select (one SVG chevron), calendar, toast with Undo (`UI.toast`), menus, tabs and segments keyboard. |
| `motion.css`, `motion.js` | Motion tokens in use (see Motion contract). |
| `icons.js` | One icon set, `icon('check', 16)`. |
| `preview.css`, `fileviewer.*`, `evidence.js`, `blocks.*` | File and result previews, viewer, proof, blocks. |
| `question-card*.js`, `composer.*` | Question card, chat composer. |
| `gallery.html`, `gallery.js`, `gallery.css`, `state-controls.js`, `samples/` | The living style guide, its fixtures, and the Loaded / Loading / Empty / Error switcher the mockup pages use. |
| `mockup.css` | Mockup-only layout, linked only by the dashboard mockup pages (merged from the former per-draft sheets, #795 D1). Every rule is scoped with `body.mk-<draft>`; not for product pages, no new rules (R6.2). |
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
| E States | E1 skeleton shaped like the result within 100 ms when a load may pass 1 s, no page spinner · E2 master empty state, one sentence, one button, only after loading · E3 error: what happened, what to do, one button, next to its source · E4 stale, partial or offline keeps the data, "Updated … ago" · E5 0 / 1 / many, plurals, a 200-character title, a long word · E6 missing permission or add-on: hidden, or disabled with the reason |
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
| With reduced motion asked for, no animation or transition still runs | H10 | same |
| Rendered text at least 4.5:1 (large 3:1) against the colour behind it | H1 | same |
| No console error, uncaught exception or failed request on the gallery and on every Focus and Insights screen | (load health) | same, and `e2e/focus_insights_smoke.cjs` |
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
  flush to ONE right edge (`.page-heading` + `.page-heading-actions`); no in-page breadcrumb, no back link, no frame
  header (Factory, Focus, Sync all break this). Topbar crumb = "Tickets › DT-4" only. Content starts at the same y on
  every page (`.page`, 32 px top). Two widths only: full (default, no max-width) and `.form-width` (`--form-width`,
  1024 px) for a form page such as Settings; both left-aligned. The top bar holds one outlined `New ticket`; the page's
  own main action is the only filled button. Phone mode while on = an outlined chip after the breadcrumb (menu),
  never a banner.
- SX-5 Buttons: Primary (one per page, counts the topbar), Secondary, Ghost, Danger; icon buttons have aria-labels;
  "Got it", pill buttons, underlined text actions, full-width outline buttons are deleted.
- SX-6 Selects and chevrons: one Select (36 px, border like inputs, SVG chevron), the same chevron on nav groups, ticket
  groups and the workspace switcher (fb26).
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
  page (Messages, Factory).
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
- SX-16 Skeletons: every route and every add-on frame shows a skeleton shaped like its final layout within 100 ms
  (BP-61/62); never text + bars together; "No items" only after loading finished (BP-56).
- SX-17 Motion tokens: hover/press 100 ms, open/close 150 ms (QA-09), page change 200 ms, panels 240 ms, enter
  ease-out / exit ease-in (BP-70), reduced-motion = instant; used by: route change, tab switch, dialog, list
  insert/remove (Home answered card), status pill change (one pulse), skeleton → content cross-fade.
- SX-18 Words: helper / step / result / ticket / schedule / phone / Check (status) / Check result (action) / Looks good
  · Send back; the person = chosen name (fb13); "agent", "artifact", "autopilot", "relay", "copy" (worktree), "Exact
  text", "Reference" are banned on level 1 (BP-78, F2, F3).
- SX-19 Dates: "today 10:32", "Mon 08:00", "14 Nov 2026, 10:32", 24 h, elapsed as "running 53 min" (F4, round-2 note).
  Built: `UI.stamp(value, {time:false, now})` and `UI.clock(value)` in `date.js` are the only way to write a date or time on a page (the dashboard's `date()`, `time()` and `DashHelpers.stamp` call the same rules). Never `toLocaleString`.
- Ticket header strip (14 Nov): `.strip` = one status pill (`UI.statusIcon`), the title, one sentence, one main action, then the tabs. No stepper. The helper is just "Helper"; the review state is always "Check" with "Looks good" / "Send back".
- File cards (14 Nov): one `.file-tile` per file (thumbnail, name, kind · size · date). A CSV thumbnail is a `.mini-table`, Markdown is rendered (`FileViewer.renderMd`). A toolbar (search, sort, cards/list) only above 6 files.
- SX-20 One source per count and status: sidebar badge = Home headline = Tickets group count; a newer system event

## Behaviour notes (owner feedback 14 Nov)

- "You: <name>" (kit menu above Settings): pick a person or Add person (name only). The chosen person is the actor of tickets and history lines made from the dashboard.
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
| Type | 12/16, 14/18, 14/20, 20/28, 28/36 px | Metadata, compact body, body, section, page title. Four font sizes. |
| Weight | 400 / 500 / 600 | Normal, emphasis, heading. No bold wall of text. |
| Spacing | 2, 4, 8, 12, 16, 24, 32, 40, 48, 64 px | Use scale for padding and gaps; 1 px borders are not spacing. |
| Shape | 8 px controls, 10 px cards, 12 px dialogs, round status pills | No nested rounded boxes for ordinary rows. |
| Elevation | `--lift-shadow`, `--shadow` | Menus, toast, dialog and sheet only. |
| Density | `--row-height:40px`, compact 32 px; `--card-padding:16px`, compact 12 px | Comfortable default, apply view-wide. |

Semantic hues are bounded to neutral, teal, blue, green, amber and rose. Status colours have similar perceptual lightness (Lab L* about 74–80), with matching dark fills. Do not introduce purple review, orange add-on labels or rainbow workspace navigation. Data charts reuse these colours with direct labels, never colour alone (BP-09, BP-12–17).

Computed sRGB contrast, before browser rendering: primary text on the lightest surface **11.63:1**, supporting **6.79:1**, quiet **5.65:1**; input border **3.46:1**; focus teal **7.42:1**; teal button label **8.48:1**; working / needs / done / failed badge pairs **6.65 / 7.25 / 6.81 / 6.73:1**. All normal text pairs exceed 4.5:1 and interactive boundaries exceed 3:1. Decorative card dividers are deliberately softer, since content grouping is also supplied by spacing and surfaces. Recheck contrast whenever introducing another background.

## Shell and navigation

One inverted L: sidebar plus topbar, at most one contextual detail panel (BP-02). Sidebar is 232 px at 1280 and 1920. Below 1280 it becomes a 64 px icon rail. Icons have accessible names and focus labels; nothing is mouse-only. The workspace switcher and ticket views use native disclosures, including a popout on the rail. The phone switch has an accessible full label. At short heights the nav can scroll; the page never needs a forced desktop minimum width.

Three core links: Home, Tickets, Chat (Notes live on Home). Add-ons are a labelled native disclosure containing Automation, Focus, Insights, Sync, Shared links, Contacts. Settings is anchored at the bottom. This preserves the requested full route map without eleven undifferentiated top-level destinations (BP-50). Add-ons begin expanded for discovery. Ticket views are chips on the Tickets page (All, Needs me, Working, Done this week, + Save view), not a sidebar group (owner 14 Nov). In the application, persist the user's disclosure preference; these static pages deliberately do not store anything.

Only Home carries an attention count. Do not give every destination a badge. A ticket view query (`?view=needs-you`, `?view=working`, `?view=done-week`) is the proposed area contract. The board designer must implement those queries; the links are integration targets, not local filter implementations.

**Contacts lives under Add-ons.** It manages devices and workspace access. The bottom sidebar switch “Send questions to my phone” is a quick control, not a navigation shortcut. Settings contains notification preferences and the timeout, saved in place. Never give Settings a tab that silently redirects. If a Settings section needs device management, show an explicit link “Manage devices in Contacts →” while leaving the Settings section open (BP-47–49).

Topbar: current location and Ask the helper / New ticket. These are navigation actions. Inside a decision view, make the decision its sole prominent action and style global New ticket as outline. Breadcrumbs only for nested pages: Tickets › Customer survey; current location is not a link (BP-24, BP-51). Demo new-ticket links use `../board/board.html?new=1`; area authors should wire that query to their composer. The shell intentionally has no active route until it is adopted by an area.

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
- **Progress:** known steps use a labelled count and 4 px bar, or the four-stage stepper. Do not invent percentages for open-ended work. Announce meaningful stage changes, not every tick. Long jobs show elapsed time, current action and Leave running / Cancel (BP-63).
- **Side panel:** editable owner, due and definition of done. Keep extra properties under one Details disclosure. Production edits save immediately, with rollback on failure and Undo where appropriate (BP-28).
- **Menus / tooltips:** native details for simple menu disclosures; normal links/buttons retain natural keyboard navigation. These are not ARIA application menus. Close on Escape as shown; application click-away handling may be added. Tooltips only reinforce shortcuts, never explain a primary label.
- **Dialog / sheet:** native `showModal()` supplies focus containment, Escape dismissal and focus restoration; safe action gets autofocus. Do not nest dialogs. Use one sheet over the current ticket for preview; retain underlying scroll. Close immediately so dismissal never feels blocked.
- **Toast:** one visible at a time, 5 seconds for success, with Undo or Open for meaningful changes. Queue in the application; the reference replay replaces the previous demo toast. Error toasts persist until dismissed; blocking errors also stay by their source. Never disappear a focused toast action in the application: pause the timer while hovered/focused (BP-58).

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
| Settings | Workspace name, helpers, notifications, dark appearance, access. Save feedback in place. | Technical and advanced settings in one disclosure per section. No redirecting tabs. |
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
| Dialog / side panel | 200 / 240 ms | Enter; 8 / 24 px travel. Dismiss instantly. |
| Toast | 200 ms enter / 120 ms exit | Enter / `--ease-exit: cubic-bezier(.6,0,.8,.6)`. |
| Progress | 150 ms | Move; label changes immediately. |
| Status | 200 ms once | Subtle border pulse; no persistent movement. |
| Skeleton | 1600 ms | Low-contrast shimmer only under `[aria-busy=true]`. Instant content swap. |

**Conflict resolved:** the system brief explicitly requests a 150 ms page transition; BP-71 prohibits fading every route. The class and Replay example exist but are opt-in for first entry only. Routine navigation has no page fade. Skeleton-to-content and numbers never animate. A reorder in the real app should use FLIP on the moved item only (120 ms), not animate the entire list.

One focal animation at a time, no input blocked by animation. `prefers-reduced-motion: reduce` disables every transition, pulse, shimmer and transform animation; all controls still change state. No ambient movement at idle. The motion page's separate Replay controls are independent experiments, not an instruction to run every animation together.

## Accessibility and interaction contract

Skip link; semantic landmarks; ordered headings; named icon buttons; visible 2 px focus with 3 px offset; no clipped focus rings on ordinary cards. Native radio, checkbox, disclosure, select and dialog behaviours are intentional. Status has readable words and a symbol (BP-15, BP-75–77). Toolbar controls are normally 32–40 px, never below 24×24. No essential hover-only controls. In forced-colours mode, buttons/status boundaries and focus remain visible.

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

- Native `dialog.showModal()` and `dialog.close()` use one shared lifecycle: close button, Escape, backdrop, focus containment and restoration, scroll lock, 150 ms entry / 100 ms exit. Reduced motion is instant. `UI.fullscreen(element, opener)` moves existing content into that same lifecycle and restores it on close.
- Native selects are enhanced automatically, including dynamic controls. They retain their form values and change events. Use `data-prefix="Sort"` for labels inside the trigger and `UI.select.sync()` after programmatic value changes outside click/change/reset handlers.
- `UI.toast(message, undo)` and `UI.copy(url)` provide one notification pattern. Details menus with `.menu` and ARIA tablists get shared keyboard behaviour. Page handlers may update domain content, but should not add separate keyboard or overlay lifecycles.
- `UI.date(valueInput, trigger, oldCalendar)` provides the shared calendar. `UI.question.render(host, config)` provides recommended choices, custom input, answered state and Undo. `UI.phone()` opens demo pairing and the same question component in a phone frame.
- `gallery.html` is the clickable source of truth. Each example has a state selector and a usage note. `COMPONENT-QA.md` records the audit and browser results.
