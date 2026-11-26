# Focused review: clickable mockup (ORCH-2178)

A draft of the Review page, built on the kit, with five teams' data, for the owner "to test and feel". Not a pull
request until he picks (drafts rule, ORCH-267). Open `index.html`, or `focus.html?team=data|marketing|sales|support|dev`.

## What it is
- Start: three tiles (count, time, how many hold up work), project chips, one "Next deadline" line. No lists.
- A tile opens a round of at most 5 cards; the five lanes order the cards inside it, cards of one project stay together.
- Every card: "You decide" and "If you wait" first, then the deciding fact (always open), then "Where were we?" (what
  the ticket is for, what you said with day and source, what happened since, a stale note), then why it is in this
  group, the answers, send back with your own words, Later with a reminder. Undo line for 6 s after every move.
- Quick look shows its list first; "OK all N" is under the list. Only the orch dev team has a rule that lets cards
  pass by themselves, shown with its name and "Change rule".
- Take your time: no answer is filled, one check question (DROPPED 26 Nov) comes first, the buttons open after it.
- Ideas: 3-point brief, Keep / Later / No per idea, saving part is fine.
- Round done: what you decided (5 lines, each with Undo), what still waits, back to the start.
- Nothing is saved; a reload starts again. "Mockup: pick a team" at the top is a mockup control, not product.

## Aligned with work in flight (pull requests 3201 and 3204, not merged yet)
- The twelve kind names and their icons (review.js CARD_ICON of 3201), shown as `.swipe-kind` on every card.
- The five lane names; "Checked by the Reviewer" is one line on the start screen, not cards (except the rule card of
  the orch dev team). "The Reviewer proposes to accept: ..." with that button filled (sales: fair leads; dev: 108 fixes).
- Result cards: the helper's first summary sentence as the title of the fact box, pictures first, a "Still open"
  banner, "Send back" becomes "Send back with your comment" once words are typed.
- "Suggested" is the kit word. "Decide" is not used as a group name.
- Not shown here: the Home tiles (Needs you / In progress / Not started / Finished today); this draft is the Review page.

## New words (R4.2: each needs the owner's yes)
Group names: **Quick look**, **Short decision**, **Take your time**.

On the start screen: "Pick where to start" · "Next deadline:" · "All projects" · "about N min" · "N hold up work" /
"Nothing held up" · "Small and tested. One line each." · "One clear question each." · "Big, public or hard to take
back." · "N put off for later" / "Bring them back" · "N checked by the Reviewer, nothing to do" · "How Review works
for you" · "Cards in one go" / "Up to 5, then you see what you decided." · "Passes by itself" / "No rule. Nothing
passes without you." · "Change rule" · "Practice cards now and then: off" / "A made-up card with a mistake in it, to
see if a quick yes would have caught it."

On a card: "You decide:" · "If you wait:" · "What matters" · "The helper says" · "Where were we?" · "You said on
<day>:" · "open" · "Since then" · "This may be out of date: things changed after you said this." · "Why this is in
<group>: <reason>" · "Needs more time" · "First: <question>" · "What it is:" · "Answer the question above, then the
buttons open." · "<name> must also say yes: <rule>" · "Waits until: tests green" · "Not possible before the tests are
green" · "Passes by itself at 09:00 because of your rule ‘...’" · "What should change?" · one-tap reasons "Not what I
asked", "Explain it shorter", "Show me more first" · "Remind me:" "this afternoon", "tomorrow", "when <ticket> is
done" · ideas: "Keep", "Later", "No", "Save, N left for later", "Ideas you do not sort stay here for later."

Quick look and round end: "Look closer" · "OK all N" · "One at a time" · "Each one can be taken back afterwards." ·
"What you decided" · "Each one can still be taken back." · "Still waiting:" · "Next N in <group>" · "Back to the
start" · "Moved to Take your time" · "Undo all N".

Kit words kept as they are: Review, Suggested, Later, Undo, Send back, Send back with your comment, Looks good,
Accept, Run it, Put it live, Nudge, Start fresh, None of these, the twelve kind names and the five lane names.

## What the kit could not do (all of it is in `draft.css`, tokens only, under `body.mk-review-focus`)
- `UI.swipeDeck` has no place for the context box, the check question (DROPPED 26 Nov), the ideas list or the reminder chips, so the
  card is drawn in `focus.html` with the kit's `.swipe-card`, `.swipe-head`, `.swipe-meta`, `.swipe-kind`,
  `.swipe-need`, `.swipe-actions`, `.swipe-act`, `.swipe-sug`, `.swipe-foot`, `.swipe-top` parts. The deck's card is
  absolutely placed; the draft lets it flow with the page.
- New looks: the tile as a button (`.rf-tile` on `.stat-tile`), the fact box (`.rf-fact`, with the big number, the
  before and after words, drawn stand-in pictures), "Where were we?" (`.rf-ctx`), the check question (DROPPED 26 Nov) (`.rf-check`),
  the second person and waits-until lines (`.rf-second`, `.rf-waits`), idea rows (`.rf-idea`), the Undo line
  (`.rf-undo`, the deck keeps its own inside), the dashed mockup bar (`.rf-mock`).
- Pictures are drawn boxes, not real screenshots.

## Open questions for the owner
1. The three group names, and every word in the list above.
2. Who puts a card in a group: the helper, the Reviewer or fixed rules per kind? The mockup only shows the reason.
3. Should "Needs more time" also exist the other way (a Take your time card that is plainly small)?
4. The check question (DROPPED 26 Nov): on every Take your time card, or only where the fact is a surprise? Here: where one is written.
5. "Lea must also say yes": a line only, as asked. What does the helper do between your yes and hers?
6. "Waits until: tests green": your yes is kept and the release starts by itself. Or should it ask again?
7. Rules that let cards pass by themselves: where are they made (Settings?) and who may make one in a team?
8. Practice cards: keep the setting row or drop the idea.
9. The round size (5) and whether a round may mix projects when one project has only one card.

## Sources
- Codex challenge of draft F: `/Users/lume/orch-dev/share/attention-drafts-2026-11-25/codex-challenge-f-2026-11-25.md`
- The five concept drafts and draft F: `/Users/lume/orch-dev/share/attention-drafts-2026-11-25/` (`f-combined.html`, `shots/`)
- Brief: `BRIEF.md` in this folder. Pictures of every team at 1280, 1920 and 390: `shots/`.

# Round 2 (owner feedback after clicking it, 25 Nov)

His three points: run a Run it card directly in the terminal, as in Focus; open the ticket beside the card (and chat
with the helper or look at its session) while the decision stays open; show how pictures get bigger and where links go.

## What was built
- **A panel beside the card** (about 45% at 1280 and 1920; a full-screen sheet with "Back to the card" at 390). The
  card stays open and can be answered. Tabs: **Ticket** (Done when, Tasks with done marks and their evidence line,
  Pull requests, History, Files), **Chat** (the helper's chat for this ticket, kit composer in row layout), **Terminal**
  (the helper's session in the kit's `.term` box: "Watching only", "Let me type", Copy). It opens from the ticket
  number in the card head, every "open" link and the three quiet buttons in the card's foot. Another card's ticket
  swaps the panel; closing it keeps the place in the round. It stays open while you answer and shows the ticket you
  opened until you open another.
- **Run it** opens the Terminal tab and plays the command with its lines, then the card shows "Ran at 21:14 · see
  terminal", "Next card" and Undo. Copy stays as the small button next to the command. One mock case fails: data,
  "Delete the old claims table" (a report still reads it): the card shows "It did not work", "Ask the helper" (Chat
  with the card's words filled in), "Run it again" and Later. Sales "Merge 214 double contacts" and orch dev "Start
  the merge queue again" run through.
- **Two quiet actions on every card**: "Ask about this" (Chat, filled with "About: <the decision>") and "Open the
  session" (Terminal). On Stuck cards "Open the session" is the first, filled button and the terminal stands at the
  place it stopped, with the 3 failed tries. A third, "Open the ticket", sits beside them.
- **Make bigger** on Pictures, Before and after and Choice-with-pictures cards: the kit's full-screen overlay
  (`ui-fullscreen`, "× Exit full screen", Esc). Arrow keys, the two arrow buttons or a swipe move between pictures. A
  before and after pair has "Side by side" and "Slider" (drag the line, or the arrow keys on it). One click on a spot
  leaves pin 1 with your words (kit `.swipe-pin`); pictures only, never text.
- **Pictures are drawn** now (inline SVG): banners in four shapes, pages with the button high or low, the region
  chart with the legend over or under the bars, Home with the tiles off the edge, three empty Files pages, three
  size-guide drawings.
- **Check question first**: on Take your time cards the question comes before "What matters", and that box shows
  only after the answer.

## Where each kind of link is shown
| Link | Opens | Example |
|---|---|---|
| "You said … · Chat with the helper · open" | Chat tab, that message marked | data: Email column (HEL-41); sales: Discount (TES-90); dev: Windows 10 (ORCH-2166) |
| "… · Team rules · open" / "Your rule · open" | the rules file in the panel, that line marked | dev: Merge queue (ORCH-2185), Backup fix; data: Nightly load (HEL-53); marketing: Subject line (NOR-77); sales: Keller Logistik; support: Ms Frei |
| "… · Comment on <ticket> · open" / "Ticket text · open" | Ticket tab, that entry in History marked | marketing: Campaign page (NOR-71); dev: Release 0.42 |
| Pull request | a row in the Ticket tab (checks, state) with "Open on GitHub ↗", the only link that leaves orch | dev: Merge queue (4 rows), Backup fix (1 row) |
| Document | "Open the document" on the card, or Files in the Ticket tab: the file in the panel | sales: Quote for 50 seats (TES-91); marketing: Blog draft (NOR-74), LinkedIn post |
| Picture | "Make bigger", full screen | marketing: 4 banners, Campaign page; support: Returns page, Size guide; dev: Empty Files page, Home; data: Region chart |

## New words in round 2 (R4.2: each needs the owner's yes)
Panel: "Ticket", "Chat", "Terminal" (tabs) · "Back to the card" · "Close the panel" · "Done when" · "Tasks" · "Shown
with a note" · "Pull requests" · "History" · "Files" · "Waits for you in Review" · "Open on GitHub" · "Back to the
ticket" · "Write to the helper" · "Send" · "The helper's session for <ticket>, live." · "Watching only" / "You can
type now" · "Let me type" · "Stopped here: … 3 tries failed. Waiting for you."

Card: "Ask about this" · "Open the session" · "Open the ticket" · "Open the document" · "Running, see the terminal on
the right." · "Ran at 21:14 · see terminal" · "Next card" · "It did not work:" · "Ask the helper" · "Run it again" ·
"What matters shows after your answer."

Pictures: "Make bigger" (the kit word) · "Side by side" · "Slider" · "Drag the line. Left of it is before, right of it
is after." · "Before first, then after." · "Click a spot to comment." · "What about this spot?" · "Save
comment" · "Remove".

"Terminal" and "the session" are technical words; they follow the Focus page as asked. The owner decides whether
non-technical teams see them or a plainer pair (for example "What the helper does").

## What the kit could not do in round 2 (all in `draft.css`)
- The panel reuses `.review-ticket` and `.review-ticket-h` (the review page's side panel); the draft adds a row for
  the tabs, the two-column split (`.rf-split`) and the full-screen sheet at phone width.
- Terminal: the kit's `.term`, `.term-bar`, `.term-say`, `.term-sw`, `.term-screen` classes with plain lines in a
  `pre`. It is not `UI.term` (xterm): that needs the live terminal bridge. "Let me type" only changes the look.
- File viewer: the kit's file viewer is a wide dialog (`FileViewer.open`). To keep the card visible the panel uses
  its note renderer (`FileViewer.renderMd`) and the `.fv-md` look inside the panel; the marked line is a draft look.
- Bigger pictures: the kit overlay lifecycle and the kit's compare (`.swipe-compare`, `.cmp-pane`, `.cmp-tag`,
  `.cmp-line`, `.cmp-range`) and pin (`.swipe-pin`, `.swipe-pin-pop`, `.swipe-pin-note`) parts. The deck's own viewer
  (`UI.reviewViewer`) wants image files; the drawn pictures are inline SVG, so the dialog is built in `focus.html`.
- Ticket tab: kit `.card`, `.card-row`, `UI.statusIcon`, `.history-event`, `.file-type`. The ticket mockup's
  `.task-row` lives in `mockup.css`, which this page does not link; rows with the kit status icon stand in.
- Chat: kit `.live-chat` / `.live-chat-msg` (the Focus pane's chat) and `UI.composer` (layout row). The words of
  pull request 3203 ("Chat as a messenger") are not in this worktree; the panel is one ticket's chat, not the list.

## Open questions from round 2
10. Should the panel follow the card (next card, next ticket) or stay on the ticket you opened? Here it stays.
11. After "Run it": does the card leave by itself when the run is fine, or wait for "Next card"? Here it waits.
12. Undo after a run: here it only takes back the mark on the card. What can really be undone depends on the command.
13. "Let me type" from a Review card: allowed, or watching only?
14. The pin: one per picture here. Several, as the Review page has them today?
15. Words "Terminal" and "session" for non-technical teams (see above).

# Round 3 (25 Nov): calm card, sticky answers, motion, keys, states

The owner liked round 2 and agreed to one "More" row. This round applies `VISUAL-REVIEW.md` and the end of `PLAN.md`
("After the outside challenge"). Pictures of this round: `shots/r3/` (the older ones in `shots/` show rounds 1 and 2).

## What changed
- **Answers always in view.** The kit's sticky `.swipe-actions` bar is back, under the card and above the tab bar on a
  phone. At most three answers, then one ghost "More". The card no longer has a foot.
- **The card by default**: kind, ticket number and due time in one line; "You decide" and "If you wait"; the one
  framed box "What matters"; one line "You said on 21 Nov: '…' · open" (or "Team rule, 21 Nov: …"). The rest of
  "Where were we?" (what the ticket is for, what happened since) opens with a small "Where were we?" line. The
  stale note stays visible, because it changes the decision.
- **More** (kit `.dropdown` with `.menu-item`; a kit `dialog.sheet` at 390): the reason the card is in this group,
  Send back…, Later…, Ask about this, Open the session, Open the ticket, Needs more time. Send back and Later open a
  kit sheet (comment box and one-tap reasons; "Later, no reminder" and the three reminders).
- **Stuck cards**: "Open the session" is the one filled button, Nudge and Start fresh are outline; the doubled
  "Open the ticket" answer is gone (it is in More).
- **One box look**: the fact is the only framed box. The check question (DROPPED 26 Nov) is a plain heading with buttons, its answer a
  plain line. "Where were we?" is quiet text. Head, body and bar share one left edge. No text separators in the head
  (the stray underlined dot is gone). "Copy" no longer breaks.
- **Start**: heading, project chips, three tiles, the Reviewer line, a link "How Review works" (opens a kit dialog
  with the three rows of round 1). "Next deadline" is a line in the tile that holds it. "Nothing held up" and
  "about N min" are gone (the plan: no minutes until there is real timing data). A group with nothing in it keeps
  its text colour, says "Nothing waits here" and does not react.
- **Quick look**: the whole row opens the card; title first, the kind as an icon with its name as a tip.
- **Round end**: no Undo line above the list; "Next N in <group>" is the filled button also when the next cards wait
  in another group.
- **Panel**: 40% wide (at least 360 px), follows the card when you answer, sections Pull requests, History and Files
  are folded, "Open on GitHub" is an icon button. At 390 the sheet keeps a strip at the bottom with the question and
  the answers, so the decision stays open. Esc closes it and the focus goes back to the card.
- **Run it**: the result takes the place of the answers in the bar ("Ran at 21:14 · see terminal", "Next card");
  the card does not grow. A run that ran cannot be undone: the Undo line and the round-end row say so.
- **Zoom**: bigger title, the hint "Click a spot to comment." sits under the toolbar, the slider knob has a ring
  instead of a shadow.

## Motion (kit keyframes, tokens and helpers only; nothing at idle; all instant with reduced motion)
| Moment | What runs |
|---|---|
| Tile to card, screen to screen | `.page-enter` / `orch.enter` (`orch-page`) |
| Card to card | old card `orch.leave` (fades, drops 8 px, `--dur-exit`), new card `orch-page` after `--dur-exit` |
| Answer to Undo line | the line has its own row over the progress row, so nothing moves; text `orch-fade` in `--dur-base`, out `--dur-exit` |
| Check answer | "What it is" and the fact box keep their place before the answer (the box is veiled by a kit `.skeleton`); content `orch-fade` `--dur-settle` |
| Panel open / close | `orch-sheet` `--dur-slow` / `orch.leave`; tab switch 0 ms |
| More, Send back, Later, How Review works | kit dropdown and dialog motion through `orch.open` / `orch.close` |
| Terminal lines, pin | `.row-new` (`orch-row`) |
| Zoom | `orch.open` (backdrop fade) and `orch.flip` from the small picture |
| Round end | rows with the page stagger (`data-row`); an undone row leaves with `orch.resolve` |
| OK all N | rows `.row-out` together |
| Counters | never tick |

## Keys and focus
1 2 3 answer (on Take your time they answer the check question (DROPPED 26 Nov) first), J or → next card, K or ← the card before,
M opens More, U takes the last answer back while its line shows, Esc closes a picture, a sheet, More, then the panel.
Keys do nothing while you type. The digits show on the buttons and one hint line sits in the bar (desktop only).
After every card change the focus is on the card's question; after the check answer on the first open answer;
after closing the panel back on the question. One live region says "Answered: … · Undo with U. 2 of 4: <question>".

## States (the mockup bar has a "State" switch; `?state=`)
- Loading: kit skeleton tiles (`?state=loading`).
- Nothing waits on you: kit empty state (`?state=empty`, or answer everything).
- Empty group: the tile says "Nothing waits here".
- Save failed (`?state=savefail`): the card stays, the bar says "Not saved. … Nothing is lost." with "Try again".
- Panel failed (`?state=panelfail`): "The ticket did not load", "Not connected to the session" (each with "Try
  again"), and the chat keeps your words with "Not sent. Your words are still here. Try again."
- Undo no longer possible: after a Run it card ran ("This cannot be undone", "Cannot be undone").

## New words in round 3 (R4.2: each needs the owner's yes)
"More" · "Send back…" · "Later…" · "Later, no reminder" · "Or one tap:" · "In <group>: <reason>." · "Team rule, <day>:"
· "Where were we?" as a line you open · "How Review works" · "Nothing waits on you" · "New cards show up here when a
helper needs you." · "Looking what waits on you…" · "Nothing waits here" · "Next deadline: <card> · <time>" (now in
the tile) · "Not saved. “…” did not reach orch. Nothing is lost." · "Try again" · "Cancel" · "The ticket did not
load" / "Your card is still here. You can answer without it." · "Not connected to the session" / "The helper's
computer did not answer." · "Not sent. Your words are still here. Try again." · "This cannot be undone" / "Cannot be
undone" · "Each one can still be taken back, unless it says so." · "Sort at least one idea, then save." · "Answer the
question first, then the buttons open." · "Running, see the terminal." · "Keys: the numbers answer, J next card, K
card before, U undo, Esc close" · read aloud only: "Answered: … · Undo with U.", "Taken back: …".
Gone: "about N min", "Nothing held up", "Why this is in …" as a card line, "What matters shows after your answer.".

## Taken from the plan's "After the outside challenge"
- No "about N min" anywhere. The quote line says who it is from ("You said", "Team rule") and always has its source.
- Not built here (plan slices, not mockup looks): asking again when the result changed after the quote; hiding the
  quote when it has no stable pointer; the fixtures.
- Still open for the owner: the check question (DROPPED 26 Nov) before the fact (both outside challenges doubt it helps).

## What the kit could not do in round 3 (all in `draft.css`)
- `.status-change` (the one pulse for a changed count or a run result) lives in `mockup.css` for the board only; not
  used here, so a changed tile count and "Ran at" do not pulse.
- The delay of the entering card behind the leaving one, the Undo line's fade and the panel's slide are draft classes
  on kit keyframes and tokens (`.rf-enter-late`, `.rf-fade`, `.rf-fade-out`, `.rf-panel-in`, `.rf-reveal-in`).
- The kit dropdown opens downwards; the draft opens it upwards from the bar.
- `UI.sheet` shows two close buttons together with the overlay lifecycle; the draft builds the same `dialog.sheet`
  with one.
- `orch.flip` of the card column when the panel opens does nothing (the column keeps its left edge and only gets
  narrower; `flip` without scale only moves).

## Measured in round 3 (Playwright, first Short decision card of each team, page at the top)
| | Before (visual review) | Round 3 |
|---|---|---|
| First answer at 1280x800 | top 729 to 815 px, card 2 and Take your time below the fold | top 663 to 714 px, bottom 707 to 758 px, always in view (sticky) |
| First answer at 390x844 | top 1003 to 1161 px (1287 to 1509 after the check) | top 536 to 640 px, bottom 580 to 684 px, always in view (sticky, above the tab bar) |
| Controls in a card (with its bar) | 17 to 18 | 7 (8 with "Open the document") |
| Left edges of head, question, fact, quote | 281 / 273 / 281 | 281 / 281 / 281 / 281 (33 at 390) |
| Card height change when the check is answered | +150 to +420 px | 0 px, all teams, all widths |
| `document.getAnimations()` on a card change | empty | `orch-page` and the leave animation (plus `orch-fade` for the Undo line) |
Also checked by the script at 1280 and 1920: J moves on and K comes back, M opens More, Esc closes More and then the
panel, the focus lands on the new card's question, the panel shows the next card's ticket after an answer, a failed
save keeps the card and "Try again" saves it. No page errors, no failed requests, no sideways scroll at 1280, 1920, 390.
