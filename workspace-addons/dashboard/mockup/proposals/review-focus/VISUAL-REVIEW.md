# Focused review: visual and UX review (ORCH-2178, 25 Nov)

Clicked through by hand in headless Chromium at 1280x800 and 390x844 (dev, marketing, data; the folder's `shots/` for
the rest). Measured numbers are from the live page. Most important first.

## 0. The five things that decide "smooth"
1. **The answer is below the fold on almost every card.** First answer button top: dev Short 729 px (card 2: 815),
   data Take your time 737-795, after the check reveal 886-1105 (viewport 800). At 390: 1003-1161 before the check,
   1287-1509 after (viewport 844), so 1.5 to 2 screens of scrolling per card. The kit deck has the answers as a sticky
   bar (`.swipe-actions`); the draft turned that off (`.rf-actions{position:static}`). Fix: bring the sticky bar back,
   at 390 above the `.tabbar` (kit already offsets toasts for it, `widgets.css` line 1028).
2. **Nothing moves, so every change is a jump.** `document.getAnimations()` is empty on every step except the
   spinner. Card swap, Undo line, fact reveal, panel, zoom and round end all hard-cut; three of them also shift layout
   (see 3).
3. **18 controls in one card** (dev Short card 1: 22 buttons on the page, 17 in the card, 11 Tab presses to reach the
   answer). The foot alone is 11 controls. This is the busy-ness he named.
4. **No keyboard and no focus handling.** 1/2/3, J/K, arrows, Esc: nothing happens. Esc does not close the panel.
   After a tile click focus is on `main`; after an answer, a check answer or opening the panel it falls to `body`.
5. **Layout shifts.** Undo line pushes the whole run down 60 px and pulls it back up after 6 s (docH 1290 to 1230,
   scroll 397 to 337). Run it grows the card by 240 px and pushes the answer row from 729 to 849. The check reveal
   grows the card by 150-420 px above the answers.

## 1. Visual quality
- **Card head meta row** (all teams): a stray underlined "·" sits before the ticket number (the separator is inside
  the link's underline); at 390 and with the panel open the row wraps and a line starts with "·". Fix: separators as
  `gap` on `.swipe-meta`, never as text; keep kind + ticket on line 1, drop the lane name from the head (it is said
  again in "Why this is in …").
- **Three boxes with three different frames stacked** (`.rf-check` dashed, `.rf-fact` strong border + brand left
  edge, `.rf-ctx` filled, plus `.rf-waits` warning box and the `.banner` inside the check). Five box looks in one
  card. Fix: one framed box per card (the fact, `.rf-fact`); the check question becomes a plain heading + buttons, no
  dashed frame (dashed already means "mockup control" on this page); "Where were we?" loses its fill and sits as
  quiet text (`--text-muted`, `--fs-2`) or behind More.
- **Fact box inner padding is off** vs the card: card children use `margin:0 var(--s4)`, head and foot use the kit's
  own padding, so head text (x=281), boxes (x=273) and foot (x=281) do not share a left edge. Fix: one inset
  (`--s5`) for head, body and foot.
- **Type scale**: title `--fs-4` 20/28 is right. "What matters" label is `--fs-meta` muted and reads weaker than the
  dt labels under it; `.rf-rows dt` (12) against dd (14) is fine but the dt column is 160 px wide for 12 px words:
  set `minmax(96px,max-content)`. "If you wait:" is bold label + normal text while "You decide:" is muted label +
  bold text: two opposite label styles on adjacent lines. Use `.rf-lead` (muted, 400) for both labels.
- **Answer buttons**: Take your time shows three outline buttons with unequal gaps (the disabled one carries a
  caption that widens its grid cell: "Put it live now" then a 100 px hole before "Don't release"). Fix: caption under
  the row as one `.meta` line, buttons in a plain `gap:var(--s3)` row.
- **Stuck card** (dev ORCH-2188): four equal outline buttons in two rows ("Open the session", "Nudge", "Start
  fresh", "Open the ticket"), and "Open the ticket" appears again in the quiet row. NOTES says the first is filled;
  it is not. Fix: "Open the session" `.btn.primary`, Nudge and Start fresh outline, drop the duplicate.
- **390: "Copy" breaks into "Cop / y"** next to the command (`dev-390-02`). Fix: `flex:none;white-space:nowrap` on
  the button, command wraps instead; or the kit icon button with `aria-label`.
- **390 start tiles**: the count sits right, vertically centred against four lines of text, so number and label no
  longer read as one unit; desktop has it under the label. Keep the desktop order (label, number, one line).
- **Start tile text**: four lines per tile (count, time, "Nothing held up", description). "Nothing held up" in two of
  three tiles is noise. The `.chip` "2 hold up work" makes that tile 8 px taller in content than its neighbours'
  text block (baseline of the last line differs: 480 vs 488).
- **Zoom** (`dev-1280-r2-18`, `-14`): the title is 14 px bold in a full-screen view, the caption 12 px bottom-left
  far from the picture ("Click a spot to comment."), and 180 px of dead space above the picture. Fix: title
  `--fs-4`, hint directly under the toolbar row, stage centred in the remaining height. The slider knob has
  `--lift-shadow` on a 24 px dot: heavy; use a 2 px `--bg` ring instead.
- **Panel at 1280** squeezes the card to about 530 px: title wraps to two lines, reminder chips to two rows, quiet
  actions to two rows, pull request rows wrap to four lines beside a 150 px "Open on GitHub". Fix: panel 40% with
  `min-width:360px`, pull request rows as `.card-row` with the link as an icon button, and the foot collapsed (see 2).
- **Progress row**: "Back to the start" is a ghost button on the right edge at desktop and its own full row at 390
  (40 px of nothing). Fix: a back arrow icon button left of the group name, same row at every width.
- **Round end**: an Undo line (for the last card) directly above a list where every row has its own Undo: the same
  word six times. Drop the line on this screen. "Back to the start" is primary while "Next N in <group>" (the faster
  path) is not offered when cards still wait in another group.
- **Quick look list** is the cleanest screen. Two nits: the kind chip and the title compete (chip first); put the
  title first and the kind as icon only with a title attribute; "Look closer" x5 could be the whole row as a button.

## 2. Busy-ness: what to cut, and the card foot
**Default card, top to bottom (nothing else visible):**
1. Head: kind icon + ticket number (link) + due time. One line.
2. "You decide: <question>" and "If you wait: <one line>".
3. The fact box (or the check question first on Take your time).
4. One quiet line: "You said on 21 Nov: '…' · open" (the single most useful line of "Where were we?"). The goal line,
   "Since then" and the stale note open with a small "Where were we?" disclosure (kit `details` + `.chevron`).
5. Sticky answer bar: the answers (max 3) and, at the right end, one ghost button **More**.

**The More row** (kit `.dropdown` / `details.menu` with `.menu-item`, at 390 a `dialog.sheet`):
- Send back… (opens the comment box with the three one-tap reasons as `.chip-btn` under it; the box is not in the
  page until asked)
- Later… (opens the three reminder chips; plain "Later" with no reminder is the default and one more tap)
- Ask about this · Open the session · Open the ticket
- Needs more time (moved here from the "Why this is in …" line)
That takes the card from 18 controls to 5-6 (ticket link, open, 2-3 answers, More) and removes the border-top foot
block (about 250 px at 1280, 420 px at 390).
- Cut "Why this is in Short decision: …" from the card; the group name is already in the progress row. Keep the
  reason as the `title`/first line of More.
- Cut the second-person line and the waits box down to one `.meta` line each under "If you wait"; the full warning
  box only when the answer is blocked.
- Start screen: cut "How Review works for you" to one ghost link "How Review works" (opens a `dialog.dialog`); cut
  "Nothing held up"; merge "Next deadline" into the tile that holds it (a `.rf-due` line in that tile) so the screen
  is: heading, chips, three tiles, one Reviewer line. That is four blocks instead of six.
- Panel: Ticket tab shows Done when + Tasks only; Pull requests, History, Files as collapsed sections.

## 3. Motion spec (tokens from `tokens.css`, keyframes and classes from `motion.css`, helpers from `motion.js`)
All transform and opacity only, one focal animation at a time, never blocks input, nothing at idle.

| Moment | Spec | Reuse |
|---|---|---|
| Tile to run | Card enters: `orch-page` (4 px up + fade), `--dur-settle` `--ease-enter`. No tile-grows-into-card. | `orch.enter(col)` / `.page-enter` |
| Card leaves after an answer | Old card fades and drops 8 px, `--dur-exit` `--ease-exit`; | `orch.leave(card, rect)` |
| Next card enters | starts when the old one is gone: `orch-page`, `--dur-base` `--ease-enter`. Total under 300 ms. | `.page-enter` on the card |
| Answer to Undo line | The line is always reserved space (min-height `--touch`) so nothing shifts; text fades in `orch-fade` `--dur-base` `--ease-enter`, out `--dur-exit` `--ease-exit`. No countdown bar. | `.toast[data-state]` pattern, or use `orch.toast` itself |
| Progress bar | width, `--dur-base` `--ease-move`; "2 of 4" changes at once. | kit `.progress>span` (already there) |
| Counters (tile count, sidebar 13 to 12) | No ticking (contract: numbers never animate). One `.status-change` pulse, `--dur-settle`, on the tile whose count changed when you come back to the start. | `.status-change` |
| Panel open | 24 px slide + fade, `--dur-slow` `--ease-enter`; card column narrows with `orch.flip(col, fromRect, {scale:false})`. At 390 the same as a sheet. | `orch-sheet` keyframes, `orch.flip` |
| Panel close | `--dur-exit` `--ease-exit`; column slides back with `orch.flip(…,{scale:false})`. | `orch.leave(panel, rect)` |
| Panel tab switch | 0 ms (contract), keep the panel height: `min-height` stays, scroll resets. | none |
| Fact box reveal after the check | Space for the box is reserved before the answer (a `.skeleton` block the box's size, not the line "What matters shows after your answer"), then content fades in `orch-fade` `--dur-settle` `--ease-enter`. Answers unlock with the colour transition `--dur-fast` `--ease-move`. | `.skeleton`, `.btn` transition |
| Terminal lines | Each line `orch-row` (`.row-new`), `--dur-exit` `--ease-enter`, no stagger; keep the 300-420 ms step timer, scroll to bottom without smooth scroll. | `.row-new` |
| Run it result | "Ran at 21:14" replaces the answer row in place (same height), `.status-change` once. | `.status-change` |
| Zoom open | Picture grows from its thumbnail: `orch.flip(zoomPic, thumbRect)`, `--dur-slow` `--ease-move`; backdrop `orch-fade` `--dur-base`. Close: `orch.leave`, `--dur-exit`. | `orch.flip`, `orch.open/close`, `UI.fullscreen` |
| Pin drop | `orch.flip` from the click point is too much; `orch-row` `--dur-exit`. | `.row-new` |
| Round-end recap | Rows enter with the page stagger (20 ms steps, max 8), `--dur-base` `--ease-enter`. An undone row leaves with `orch-collapse` `--dur-fast`. | `orch.enter(list)` with `data-row`, `orch.resolve(row, focusTarget)` |
| Quick look "OK all N" | Rows collapse together (no stagger), `--dur-fast` `--ease-exit`. | `.row-out` |
| Hover / press on tiles and answers | `--dur-fast` `--ease-move` (tile uses `--ease-out` today; same curve as enter, switch to `--ease-move`). | kit `.btn` transition |
| Reduced motion | Everything instant; the kit's global rule already covers CSS; `orch.flip/leave/enter` return early. Reserved space (Undo line, fact box) is what keeps it calm here, so it must not depend on animation. | `orch.reduce()` |

## 4. UX flow
- **Keyboard**: 1/2/3 answer (show the digit as a `kbd` hint on desktop only), J or ArrowRight = Later/next, K or
  ArrowLeft = back one card, U = Undo while the line shows, M = More, Esc closes zoom, then panel, then More.
  Never fire while a `textarea`/`input` has focus. Take your time: 1/2/3 answer the check first, then the decision.
- **Focus**: after a tile or an answer, focus the new card's `h3` (`tabindex=-1`), and announce "2 of 4" through one
  `aria-live=polite` region (none exists today). After the check answer, focus the first unlocked answer. Panel
  open: focus its heading; close: back to the trigger (`orch.open/close` does this for dialogs; mirror it). After
  the 6 s line goes, do not move focus.
- **Scroll**: every new card starts at scroll 0 with the Undo line in reserved space; today the line plus the mock bar
  push the card's title 60 px lower on every card after the first.
- **Where the eye goes**: today the brand-edged fact box and the filled "Where were we?" outweigh the question.
  With one framed box the order becomes question, fact, answers.
- **Phone**: sticky answer bar in the thumb zone above the tab bar, answers full width stacked (max 3) with More as
  the last, smaller row; swipe is not needed. The panel sheet covers the card, which breaks "the decision stays
  open": keep a one-line sticky strip with the question and the answers at the bottom of the sheet. 8 of 25 controls
  are under 44 px at 390 (chips, ghost sm buttons); they all move into More, where `.menu-item` is 44 px.
- **Panel does not follow the card**: after "Next card" it still shows the previous ticket (NOTES question 10). For
  a short attention span that is a wrong-context trap: follow the card, or show a `.banner` "This is ORCH-2185, not
  the card on the left · Show this card's ticket".
- **Run it**: the card waits for "Next card" after a good run. Auto-advance after the result line has shown for one
  beat is smoother, with the result in the Undo line ("Ran at 21:14 · see terminal · Undo").
- **Check question**: a wrong guess gets the same neutral "What it is: …" as a right one. Good (no quiz feeling);
  keep it, but mark the picked chip only, do not grey the others to disabled-looking.
- **Missing states**: loading (first paint and panel tabs: `orch.skeleton`), empty start ("Nothing waits on you",
  `UI.empty`), an empty group tile (disabled tile at .6 opacity fails contrast: keep text colour, drop the pointer,
  say "Nothing waits here"), answer failed to save (error toast + the card stays), panel failed to load, terminal
  not connected, chat send failed, Undo no longer possible after a run.

## 5. Keep
- "You decide:" + "If you wait:" as the first two lines; the fact always open; the big number facts.
- Three calm tiles with count and minutes; rounds of at most 5; the round-end list with Undo per line.
- Quick look as a list first, "OK all N" only under it, "Each one can be taken back afterwards."
- The check question before the fact on Take your time, with the neutral reveal.
- Ideas with Keep / Later / No per row and "Save, N left for later".
- The card staying visible beside the panel at desktop; "Open on GitHub" as the only link that leaves.
- Before and after with Side by side / Slider; one click to pin with words.
- The "You said on <day>: '…' · open" line with its source.
- The dashed mockup bar clearly reading as not product.
