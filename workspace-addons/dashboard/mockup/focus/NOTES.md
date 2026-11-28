## Focus draft D: the agreed Focus mockup (ORCH-251, ORCH-262, 17 Nov)
focus-v4d.html (script focus-v4d.js) is the one Focus mockup the owner picked: the live wall of sessions (Needs you as a big card, working tiles, idle rows, zoom into one) with a bar under every dashboard page that opens into a layer (right, bottom, split or full screen), chat or terminal per session, the result widgets and the Features sheet. Demo data and a simulated terminal; picks stay in this browser. It is the visual source of truth for the new Focus.
The earlier drafts (v2, layer v3, v4 A/B/C) were removed once D was chosen; they live in the git history of PR 1262.

## The new Focus is the only Focus (ORCH-816, 19 Nov)

The owner retired the old Focus page and its Preview switch (ORCH-264, 17 Nov): Focus always shows draft D (the wall,
the bar and the layer). focus-preview.html (the empty shell with the Preview tag) and the Preview row of
../settings/addon-detail-focus.html are gone; the Typing row stays.
The old Focus page mockups (focus.html, focus-help, focus-ticket*, draft-692 and their helper scripts) were removed; they live in git
history. review-preview.html and agents/tools.js stay: draft D loads them.

## The layer, built (ORCH-338, 17 Nov)

focus-v4d.html stays the source of truth for the layer; nothing in the draft changed. The dashboard now has it:
one dock under every page (outside the page content, so it stays open when the page changes) with
a panel at the bottom, on the right or full screen, minimise to the bar, close to the side. Place and size are kept per
browser; the top edge of the bottom panel and the left edge of the right one resize it (drag or arrow keys). Esc goes
one step back: an open menu, full screen, then the panel to the bar. One session for now; the pane says where the chat
and terminal come. Master: `.live-*` in widgets.css (style guide: Live layer), icons dock-bottom, dock-right,
dock-side, full-screen, full-exit.
## The bar is built (ORCH-337, 17 Nov)

- The bar of draft D is in the dashboard (`pages/livebar.js`), with its look in the kit
  (`.lbar` in `widgets.css`, gallery section "Live bar"). Same groups, words and fold steps as `chipsHTML` here.
- Two changes from this draft: an open list scrolls inside its box (here it runs past it), and when even symbols and
  numbers do not fit, needs you stays and the rest becomes one More count (fold 4), so nothing is cut at 320 wide.
- New, Open and Where Focus sits come with the layer; the bar keeps an empty `.lbar-end` slot for them.

## One Helpers menu (ORCH-2198, 26 Nov, owner pick J b: "calmer")

- The bar holds the name, one **Helpers ▾** button and New: no chips, no counts. A ◆ on the button when something needs
  you (no number; the number is on the Review badge). `chipsHTML` draws that button; `?list=helpers` opens the menu.
- The menu groups every session as Needs you, Working and Quiet (in line, idle) with their counts (`.lbar-gh`); each
  row has Open and More and opens its pane. Built the same in `pages/livebar.js`.
- The menu opens inside the window: above the bar at the bottom, below it in full screen where the bar sits at the
  top (before, the list opened above the top edge and could not be seen).

## The split, built (ORCH-339, 17 Nov)

focus-v4d.html stays the source of truth; nothing in the draft changed. In the new Focus the layer now holds
1, 2 or 3 sessions side by side (stacked in the right panel), in the order of the bar's chips. One pane is selected
(brand line on top); the title of another selects it. Every pane has pin, add beside (the next live session; off at
three), place, full screen, minimise and close; closing a pane gives its room to the others and selects its neighbour.
Narrow panes (three at 1280, more than one on the right, a phone) fold pin and place into More, as in the draft. A
phone shows only the selected session and has no add beside. The split and the selection are kept per browser and
stay while the page changes. Pins are kept in this browser (the bar's key) until the wall stores them in orch.
Master: `.live-*` in widgets.css (style guide: Live layer); click-through step 12.

## Pane buttons with words, a choice for Add beside (ORCH-463, 18 Nov)

The owner's persona round 4: the pane showed icons only, the split cut the titles to 'Plan…' and the state to 'Wor…',
and Add beside took a session without asking. The owner chose: words on the buttons and a choice for Add beside. Now
every pane button carries its word (Pin, Add beside, Place, Full screen, Minimise, Close, More). A compact pane (every
split, a single pane under 1200 px, the right panel, a phone) gives the title a row of its own and puts the buttons on
a second row; pin, history, place and full screen fold into More there, and minimise too when the pane is narrow
(three at 1280). Add beside opens a list of the live sessions not shown yet (key, title, state) and shows the one
picked. A helper that says nothing now shows the step it works on as its live line ('Working on: ...').
Master: `.live-pbtn`, `.live-ph[data-compact]`, `.live-pop-scroll` in widgets.css (style guide: Live layer).

## The Focus button and Open ticket, built (ORCH-365, 17 Nov)

focus-v4d.html stays the source of truth; nothing in the draft changed. In the new Focus every ticket page and
every ticket row (table and phone) has one button with the draft's words: Watch, Answer, Open, In line or Start, from
the same session states as the bar. It opens the ticket's session in the layer and moves the keyboard into it; on the
ticket page it says "… in Focus" and sits in the header with the other actions (the draft has it under the steps),
where it takes the place of Watch live while a helper runs. A row's own Answer gives way to it, so no row shows two.
Every pane has Open ticket (also in More when the pane is narrow, as in the draft); from full screen it steps back so
the ticket page shows. Finished tickets without a helper get no button. Wall tiles come with the wall task. No new
master rules (kit buttons only); click-through step 6.

## Live data for every session, built (ORCH-359, 17 Nov)

focus-v4d.html stays the source of truth; nothing in the draft changed. The bar and the panes read one list of
sessions (GET /api/sessions, pages/livesessions.js) instead of the tickets and runs: status (needs you, working, in
line, idle, closed), what it waits on, the open question, the last lines of its screen, tool and model, open time and
when it closes for being idle. A pane shows what the session does now, its last lines and draft D's meta line
("Helper · Opus · open 38 min · stays open while it works"), updated in place every 3 s. The wall builds on the same
list and the same words (liveNow, liveMeta). Master: `.live-now`, `.live-lines`, `.live-meta` in widgets.css (style
guide: Live layer); click-through step 16.

## Earlier sessions, built (ORCH-363, 17 Nov)

orch keeps the last 10 sessions per ticket on this computer (the ones in use included; only the ids are forgotten,
never the tool's own files). In the new Focus each pane has a History button (in More when the pane is
narrow) that shows the draft's "Earlier sessions" list instead of the session: time, first message, number of
messages and the tool, newest first; the one in use says In use, one whose conversation is not on this computer has no
Reopen. Reopen starts the helper on that conversation (`orch run start <ticket> --session <id>`); while a helper works
the buttons are off with one line why. The draft's Start choice above the list (continue, fresh start, tool and model)
is the Start task; this draft lost only its "To build" chip and note. Master: `.live-hist*` in widgets.css (style guide:
Live layer); click-through step 26.

## Start choice and tool and model, built (ORCH-362, 18 Nov)

In the new Focus the pane of a ticket with no helper shows the draft's Start choice: Continue where it stopped
(with the time of the last conversation; only when there is one), Fresh start with "Runs on" tool and model (the
workspace's tool and the ticket's model preselected, so one click starts it), and the earlier sessions with Reopen
(the History list). Above it one line says how many helper places are in use; when every place is taken it says how
many tickets wait in line, a start then waits in line (a plain message, no error), and a ticket in line shows where it
stands. Only tools found on this computer are offered; a tool orch passes no model to says it uses its own model. It
uses the existing start: `orch run start` (`--fresh`, `--agent`), `orch ticket model`, `orch run start --session`.

A working session's pane has one line at its top: tool · model, how long it is open and when it closes for being idle
(the draft's words). Tool · model opens the model choice. One change from the draft: orch already switches a working
helper's model when it finishes its current step (ORCH-49), so the menu says "applies when the helper finishes its
current step (or at its next start)" instead of "takes effect with a fresh start". Wall tiles get the same line with
the wall task; with the live data of every session (ORCH-359) the line reads tool, model and times from it. Master:
`.live-start`, `.live-choice*`, `.live-pick*`, `.live-places`, `.live-prow`, `.live-pop[data-down]` in widgets.css
(style guide: Live layer); click-through steps 14 and 16.

## The wall, built (ORCH-360, 18 Nov)

focus-v4d.html stays the source of truth; nothing in the draft changed. In the new Focus the Focus page is the
wall (`pages/livewall.js`) on the live sessions list: the summary line ("3 need you · 4 working · 9 in line · 8 idle",
then "24 sessions"), the filter, then the draft's bands: Pinned, Needs you and working, In line, Idle and no session.
Needs-you tiles are orange and first, their sentence is the question and they have no peek; a working tile shows its
last three lines and adds the newest by itself (every 3 s). In line and idle are one line each. A band folds and stays
folded (per workspace, in this browser); from 12 sessions a long band scrolls inside itself; at 1100 px and wider the
bands sit side by side as in the draft. One change from the draft: clicking a tile zooms into it in the layer (the
draft has a separate zoom view on the page), so full screen, split and Esc are the layer's; Esc goes full screen, then
the layer, then the wall. Not in this task: the pin button on a tile and renaming (pin and rename task), the New
session buttons and Runs on (start tasks). Master: `.wall-*` in widgets.css (style guide: Live wall); click-through
steps 4, 5, 8 and 11.

## A search reaches a folded band (ORCH-2063, 25 Nov)

The draft and the wall now agree on a search with folded bands: a folded band that holds a match opens by itself while
the search runs (its chevron and `aria-expanded` follow what is on screen), so the match is visible and the next Tab
stops on it. A fold click during the search counts for that search only; clearing the search brings back the folds the
person saved, and their saved choice never changes. A long one-line title ends in an ellipsis instead of running over
the line. No new control, no second search field.

## Pin and rename, built (ORCH-361, 18 Nov)

focus-v4d.html stays the source of truth; nothing in the draft changed. In the new Focus every wall tile and
line has the draft's pin button, and the panes keep theirs (in More when narrow). The selected pane's title is the
draft's rename button: click, type, Enter (Esc leaves it); the own name shows on the tile, the pane and the chip, and
the filter finds it. Pins and names are kept by orch for the workspace (`.orch/run/dashboard/sessions.json`, through
the dashboard), not per browser (issue 1351); the layer's place and panes are kept per workspace too. A session
without a ticket is pinned until it is unpinned. One change in the bar: at its last fold (needs you and More) More
holds the pinned sessions too, so a pinned one is never hidden. Master: `.live-ren` in widgets.css (style guide: Live
layer); click-through step 7.

## Groups: an epic or a run order, built (ORCH-345, 18 Nov)

The owner picked draft A of ORCH-344 and the word "small helper" (17 Nov) and OK'd it on the new Focus. The mockup is
`groups/a-on-d.html` (written by `groups/build_d.py` from `focus-v4d.js`, which stays untouched; edit the script, run
`python3 build_d.py`). Fixed on the way in: the bar chip counts helpers, the same number as the tile ("5 helpers · 2
small helpers"), not sessions; the message box says "Message to: Write the texts. Only this helper gets it." (the main
helper is not sent a copy, so the draft's "The main helper sees it too" is gone); in a narrow pane the switcher is the
one-line strip on top, so the message box keeps the pane's full width.

Built in the new Focus: the live sessions API sends `groups` (the top ticket of a parent chain and its open
sub-tickets in tree order, the small helpers each helper started inside its session). Wall: one tile per group with
its counts and a small tree, orange while one helper needs you, found by the filter by any helper. Bar: one chip with
the helper count. Pane: the switcher beside the session (main helper, its tickets, small helpers watch only, Earlier
sessions); a click swaps the session in that pane. Not built yet from the draft: Pause all, the question strip across
the top, the Stopped card. Master: `.gtree*`, `.live-gwrap`, `.live-msg`, `.live-to`, `.lbar-n` in widgets.css (style
guide: Live groups); click-through step 28.

## Windows: the helper's log instead of the live screen (ORCH-1797, 24 Nov)

Owner (24 Nov, via copilot): no second terminal backend (ConPTY) for now. On Windows helpers run in one step, so the
Terminal view of a pane shows the helper's log (its last lines, the master `.live-lines` block) under one plain line:
"On Windows helpers run in one step; the live screen is not there yet. This is the helper's log." Mockup state:
`focus-v4d.html?page=focus&view=zoom&term=1&win=1`. Built: `orch run screen` and the live sessions API give a one-step
run's log lines (redacted); `pages/liveterm.js` shows them instead of an empty terminal. No new component.

## Wall polish: states, keyboard order, needs-you mark (ORCH-2106, 25 Nov)

A pass over the built wall against this mockup and the master. The wall's states are the master empty state (kit
`UI.state`) under the filter, each with one next step: loading is three tile-shaped skeletons (no "Reading the
sessions…" line, and no "0 sessions" total while it loads); a sessions API that does not answer before the first list
says "The sessions did not load" with Try again (before, the wall loaded for ever); no sessions says "No sessions yet";
a filter that finds nothing has Clear filter, which puts the keyboard back in the filter. The summary, the filter and
the bands now sit in that order in the page too, so Tab reaches the filter before the tiles (it came after every tile).
An idle or no-session entry that asks carries the ◆ needs-you mark, as the summary counts it. At phone width the start
buttons keep 8 px from the total line. Mockup states: `focus-v4d.html?wall=loading`, `?wall=error`, `?wall=empty`, and
a filter with no match. Master: none new (`.wall-sum`/`.wall-tools` lose their `order`, the gallery wall shows the
same order); click-through steps 4, 5, 8, 30.

## Focus after ship: Open chips, words on the phone bar, plain words (ORCH-1684, 25 Nov)

The product bar now has the Open group of this draft: every session open in the layer that has no chip of its own
(not needs you, not pinned) gets a chip, also a pane with no room in the panel (Add beside at 1280, or a quiet pane
folded while the page has cards to answer; its tooltip "Not in sight in the panel: click to show it"). The "Room for 2
sessions here, so … waits on the bar" line is said to a screen reader only, no toast over the page's cards. On a phone
and beside the right dock each count keeps a short word ("2 need you", "3 working", "1 in line"); only the narrowest
fold is the numbers alone (`BL` 4 here, `data-fold` 5 in the product, each still named). Words: "stays open while it
works", "closed, you can continue it later" (no "stays warm", no "the conversation is kept").
Since ORCH-2198 (owner pick J b on ORCH-2188, 26 Nov) the bar has one Helpers menu instead of these chips and
counts; the plain words stay.

## Header-only panes, free splits, ticket beside Focus (ORCH-2199, ORCH-2200, ORCH-2202, 26 Nov)

Owner picks of ORCH-2188 (A a, B a, F a, G a, H a, I a, M a; drawings in the ticket). focus-v4d.html now draws a pane
as its header only above the screen: status pill (its popover: model, step, open time, how long it stays, Open ticket),
key, title, Chat | Terminal, Copy, full screen, split right, split down, pin, close, More (Stop, End session, History,
Where Focus sits with Bar only). No meta row, no Watching bar, no Let me type switch: a click into the screen types
(brand edge), Esc twice or a click outside stops. Split right / down asks Chat with… / Terminal / Plain terminal. The
mockup keeps its panes side by side; the built layer also nests them (helper left, terminal and Manager stacked right)
with 1 px dividers to drag, and folds the side menu to its rail beside a ticket at 1280.

## Chat shows the real talk or says it is a summary (ORCH-2204, 26 Nov)

The Chat view shows the helper's real conversation (the newest turns of the session in use, read from the tool's own
saved conversation) with the ticket's steps, questions and your messages around it. Where orch cannot read the
conversation (a tool that keeps none, or the file is not on this computer), the chat is the ticket's summary and one
small line at its top says so: "Summary from the ticket" with Open terminal (`.live-chat-src`). Here ORCH-232 shows it.
The terminal opens without WebGL too: xterm's normal renderer draws it.

## The OK card: a helper waits for your OK on its screen (ORCH-2197, 26 Nov)

Owner pick C a on ORCH-2188, with the owner's comment "should show the command by default". ORCH-240 in the demo waits
at a hook confirm: its pane shows the OK card (Helper asks to run a command, the reason, the command shown, Allow once /
Don't allow / Open terminal) in Chat and in Terminal view (there beside the terminal, no Open terminal). The product
draws the two answers only for a prompt it recognised on the screen and answers exactly that prompt; any other wait
shows the card with Open terminal only. Master: `.live-ok-t`, `.live-ok-cmd` (with `.code-block`) in widgets.css.

## UI foundation, the owner's decisions of 28 Nov (W-049, W-047, W-002, W-001, W-004, W-005)

- **Helpers menu (W-049, option A).** focus-v4d.html: the menu has two labelled groups with counts, **Working
  helpers** (every session that does not wait on you, with its state: Working, In line, Idle) and **Needs you**. With
  no helper at work the first group stays and says "No helper is working. New starts one." Nothing was removed.
- **Starting a session (W-047).** The New menu's row says "Starting…" with a spinner, every row is off until it
  started, the pane opens with the session, and a start that did not work stays under its row with **Try again**.
  The two states are in the master gallery (Live bar: "Starting", "It did not start"); the mockup starts at once.
- **Terminal text (W-002, option A).** The helper's screen keeps its size: text is never under 11 px and a wider line
  scrolls sideways, following the cursor. Your own plain terminal uses the pane's width at 13 px. The mockup's screen
  is drawn at 12 px (13 px in a large pane), inside these limits.
- **Beside the panel (W-001 A, W-004 A, W-005).** A page lays out for its page area: under 900 px it takes its narrow
  layout (New ticket in one column, Chat as list or conversation, Home with Finished below Needs you), the top bar
  stays one row ("Updated" goes first, then the page name ends with "…"), and the bar, the panel and its divider keep
  the scrollbar room on framed add-on pages too. Rule and check: the master DESIGN.md, "The room a page really has".
