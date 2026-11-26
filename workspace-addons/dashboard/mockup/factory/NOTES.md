# Factory design mockup

Built screens: home, proposal, order, stop, autopilot, draft (phase 2a).

Open `factory.html` directly. Shared assets resolve through `../system/` and `../chat/`, which already exist in this monorepo. No other mockup folders were changed.

`chat-idea.html`, `edit.html`, and `defaults.html` show phase 2b+ (in-page Start via the dashboard question card, chat integration, defaults) and carry a visible **Preview** tag.

These owner-reviewed mockups preserve their local, simulated interactions and sample content. They are a design reference, not the live read-only page. The phase 2a page uses API data, renders draft markdown as plain text, and sends all answers to the dashboard ticket with `target="_top"`. No mockup interaction grants authority or changes real workspace data. Autopilot's live per-day active-time limit is a warning only (owner 15 Nov): when it is reached the page and the needs view show a plain heads-up, "It keeps going. Stop it if you want it to rest.", and nothing is blocked. The money-per-day figure stays a target until cost reporting exists.

Preview controls offer loading and empty states; Reset Factory demo clears only `orch-factory-demo` local storage. The comparison slider and pins here are simulated; live-page pins are view-only.

Built page vs mockup, on purpose (phase 2a polish): times are shown in the viewer's local time ("today 18:30", "16 Nov 19:18"); open questions are titled from the structured stop data ("Ship it?", "Check at Build"); the order page lists the answers you can give plainly under it ("You can answer: Continue or Send back"), with no Details toggle; the live page has no Talk to Helper panel, no pause/cancel/renew buttons and no per-day money figures beyond the proposal's own targets; autopilot orders show a short card instead of a run card; every decision button is a compact link to the dashboard ticket.

## Phase 2b (built)
Decision buttons on the Factory page are one "Answer" button: inside the dashboard it opens the dashboard's own native
question card in a dialog (same card and person-proof path as the ticket page; options come from the dashboard's ticket
data, never from the page). Outside the dashboard it stays a link to the order's ticket. The mockup's in-card Start / Edit /
Not now buttons stand for that dialog.

## Fix wave b5 (Factory page)
The Factory page draws its frame and the idea box at once and reads the order list after (skeleton). The draft page opens the newest version by itself, and the draft's open questions are question cards (options, suggestion, one Answer button that opens the dashboard's question card), not a list inside the draft text.

## Fix wave owner decisions (16 Nov)
The order page's Results to check card has `Looks good, all` (two or more results; one toast with Undo, the same Looks good as on each ticket). A stop item may carry an optional preview address and then shows `Open the preview` (opens the running app in a new tab).

## No empty walls (17 Nov, ORCH-72, owner card on ORCH-64)
Factory home shows what waits for you first, in one block marked `Waits for you` (drafts, proposals, stops, results). A kind with nothing in it gets no section of its own; the missing kinds are named once in a quiet line at the end: "Nothing else in Factory right now: no drafts, stops, results or running orders. They show here when they come." Running, Shipped and Saved ideas appear only when they hold something. `factory.html` home and `../sweep/d-factory-empty.html` show this.

## One review per stage (17 Nov, ORCH-335)
The per-task `Look at ...` buttons and `Looks good, all` are gone. A stage whose results wait for the owner shows ONE
card: "<Stage>: what your crew built", a Short demo row (Play the demo opens it big), one row per built task (a picture
that opens big, the task, "Tests passed" / "1 test failed" with the failed step in plain words, "Merged" / "Not merged
yet"), a Together line, and ONE `Looks good` (all of the stage's results) and `Change` (a text box, Send: the words go to
the helper on the order as "Change at <stage>: ..."). Nothing to show: one quiet line. No Details toggle. `order.html`
and `factory.html` home (booking idea) show it.

## Factory not running (24 Nov, ORCH-1857)
`factory.html?state=stopped` and `order.html?state=stopped`: the workspace's Factory process is not running. Each
started run says the one reason, "The workspace’s Factory process is not running, so the run cannot advance.", on the
list and on the order. A notice above the page says where and by whom it is started again: "Factory is not running in
the workspace “Demo”." and "Whoever runs orch for that workspace can start it again there with `orch factory start`.
Factory then starts helpers again on its started runs." There is no button: the dashboard's Start starts every add-on
of the workspace, not only Factory, and starting Factory can start helpers, so it stays a deliberate step.

## Next pause time and look options (#956, #949)
Next pause time: a started run that is working says when its next pause needs the owner, measured with no AI call.
On the order, the Stages card says "Next pause: <stage> check · around today 18:30 · you’re needed ~3 min". On Factory
home, the Running card says "Next pause around today 18:30". There is no time while the run waits on something else,
while a question is open, or when no pause is ahead.

Look options: a taste item at a pause may carry 2 or 3 looks. `gate.html`, item 2 (email header), shows a "Pick a look"
card. It holds the looks side by side as master decision tiles (`.decision-shown` / `.decision-shot`), and a tile opens
large. One outline "Choose a look" button opens the order's plain question, with the look titles as answers. The
pause's own answer stays the one filled button.

## Polish (25 Nov, ORCH-2103)
No Details toggles on the Factory page: the proposal's "Details · all stages, who works on it, plan & tasks" is a plain
"The whole plan" card lower down (tasks, skipped stages, hand-overs; stages and team stay in the cards above). Budget
health reads "68 % used" and "N of M min of helper time used · time waiting for you does not count". Words for a
non-developer: "your helper" (never "your agent"), "about 3 min of your time", tag words as in the question text
("your call", "can't be undone"), and a "Checked" line only when the helper checked something. Loading says
"Loading…"; the error card says what happened and offers Try again and Back to Factory.
