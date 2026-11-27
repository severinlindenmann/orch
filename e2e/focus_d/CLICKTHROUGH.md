# Click-through: the new Focus (draft D)

Generated from `e2e/focus_d/steps.cjs` by `node e2e/focus_d/clickthrough.cjs --write-md`; do not edit by hand.
36 steps: 35 ready (the script clicks them), 1 pending (not built yet).

For every step take one picture at each width: 1280, 1440, 1920, 390. The name is given per step;
the runner saves them as `<name>-<width>.png`, and `--target draft` saves the draft D picture beside it as
`<name>-<width>-draft.png`.

How to run: see `e2e/focus_d/README.md`.

## 1. The dashboard opens

- Part: start
- State: ready, clicked by the script
- Pictures: `fd-01-dashboard-1280.png`, `fd-01-dashboard-1440.png`, `fd-01-dashboard-1920.png`, `fd-01-dashboard-390.png`

Do:

1. Open the dashboard link of the test workspace.

Must be seen:

- Home shows its content, no loading shape stays.
- At 390 wide nothing scrolls sideways.

## 2. Focus opens as the new Focus

- Part: start
- State: ready, clicked by the script
- Pictures: `fd-02-focus-new-1280.png`, `fd-02-focus-new-1440.png`, `fd-02-focus-new-1920.png`, `fd-02-focus-new-390.png`

Do:

1. Open Focus from the side bar (at phone width from its address).

Must be seen:

- Focus opens as the new Focus (the wall of step 4 fills it), with no Preview mark.
- No old Focus page shows.
- At 390 wide nothing scrolls sideways.

## 3. Focus has no Preview switch

- Part: start
- State: ready, clicked by the script
- Pictures: `fd-03-no-switch-1280.png`, `fd-03-no-switch-1440.png`, `fd-03-no-switch-1920.png`, `fd-03-no-switch-390.png`

Do:

1. Open Settings, Add-ons, Focus.

Must be seen:

- The Typing switch is there; there is no Preview switch and no word Preview.

## 4. The live wall in bands

- Part: wall (draft D feature 1)
- State: ready, clicked by the script
- Pictures: `fd-04-wall-1280.png`, `fd-04-wall-1440.png`, `fd-04-wall-1920.png`, `fd-04-wall-390.png`

Do:

1. Open Focus.
2. Watch a working tile for 10 seconds.

Must be seen:

- Bands in this order: Pinned, Needs you and working, In line, Idle and no session.
- One summary line on top, with the number of sessions and of helper places in use.
- Each tile says in one plain sentence what its helper does.
- A working tile adds its newest last line by itself.

## 5. A session that needs you is an orange tile

- Part: wall (draft D feature 2)
- State: ready, clicked by the script
- Pictures: `fd-05-needs-you-1280.png`, `fd-05-needs-you-1440.png`, `fd-05-needs-you-1920.png`, `fd-05-needs-you-390.png`

Do:

1. Find the tile of the helper that waits for an answer.
2. Open it and answer.

Must be seen:

- The tile is orange and first after the pinned ones.
- Its sentence is the question.
- Nothing can be answered on the wall itself; the layer shows the question with its options and a field for an own answer.
- One click on an option answers it; the question leaves the pane and the tile turns back to Working.

## 6. Focus button on a ticket and Open ticket on a session

- Part: wall (draft D feature 3)
- State: ready, clicked by the script
- Pictures: `fd-06-focus-button-1280.png`, `fd-06-focus-button-1440.png`, `fd-06-focus-button-1920.png`, `fd-06-focus-button-390.png`

Do:

1. Open Tickets and press the Focus button of a row.
2. Press Answer on a waiting row and answer with the keyboard, then Esc.
3. Open a ticket page and press its Focus button.
4. In the session press Open ticket, also from full screen.

Must be seen:

- Every ticket row has the button; it says Watch, Answer, Open or Start to fit the ticket. A ticket page with a helper working has Watch in Focus; with no helper, Open in Focus is in its ⋯ menu (one start button, ORCH-1466).
- The session opens in the layer and the page stays.
- After the answer the keyboard stays in the session; Esc steps back to the bar.
- Open ticket goes back to the same ticket page; the session stays open.

## 7. Pin a session and give it your own name

- Part: wall (draft D feature 9)
- State: ready, clicked by the script
- Pictures: `fd-07-pin-name-1280.png`, `fd-07-pin-name-1440.png`, `fd-07-pin-name-1920.png`, `fd-07-pin-name-390.png`

Do:

1. Pin a working session.
2. Click its name, type a new one and press Enter.

Must be seen:

- The pinned session moves to the Pinned band and comes first in its group of the bar's Helpers menu.
- The new name shows on its tile, its pane and its row in the Helpers menu.
- Both stay after a reload; Unpin moves it back.

## 8. Works with 24 and more sessions

- Part: wall (draft D feature 11)
- State: ready, clicked by the script
- Pictures: `fd-08-many-1280.png`, `fd-08-many-1440.png`, `fd-08-many-1920.png`, `fd-08-many-390.png`

Do:

1. Use a workspace with 24 sessions.
2. Type a word in the filter.
3. Collapse the In line band.

Must be seen:

- The wall scrolls; bands collapse and stay collapsed.
- The filter keeps only the matching tiles.
- Counts read right: "1 session", "2 sessions".

## 9. The bar under every page

- Part: bar (draft D feature 7, 11)
- State: ready, clicked by the script
- Pictures: `fd-09-bar-1280.png`, `fd-09-bar-1440.png`, `fd-09-bar-1920.png`, `fd-09-bar-390.png`

Do:

1. Open Home, then Tickets, then Review.
2. Press Helpers in the bar.
3. Type in the menu's search.

Must be seen:

- The bar is under every page, calm, on one line that never wraps.
- One Helpers menu (ORCH-2198) instead of chips and counts; a ◆ on it when something needs you.
- The menu groups the sessions as Needs you, Working and Quiet with their counts, opens inside the window and has a search.

## 10. The layer at the bottom, on the right, full screen, to the bar, to the side

- Part: layer (draft D feature 7)
- State: ready, clicked by the script
- Pictures: `fd-10-layer-1280.png`, `fd-10-layer-1440.png`, `fd-10-layer-1920.png`, `fd-10-layer-390.png`

Do:

1. Open a session from the bar.
2. Change to Tickets, Review and Home.
3. Use Place: bottom, right, full screen; press Esc twice.
4. Open it again, put it on the bar only (More), then put it to the side and open it from the edge.
5. Make it larger, then reload the page.

Must be seen:

- Each place works and the page stays usable behind it; on a phone there is no right.
- The layer stays open while the page changes.
- Esc goes back one step: full screen, then the panel, then the bar.
- In full screen Tab stays in the layer.
- Bar only (in More, Where Focus sits) leaves only the bar; to the side leaves a slim edge.
- After the reload the layer opens where it was last, at the same size.

## 11. Zoom and full screen, Esc goes one step back

- Part: layer (draft D feature 8)
- State: ready, clicked by the script
- Pictures: `fd-11-zoom-1280.png`, `fd-11-zoom-1440.png`, `fd-11-zoom-1920.png`, `fd-11-zoom-390.png`

Do:

1. Click a tile on the wall.
2. Press full screen.
3. Press Esc twice.

Must be seen:

- The tile opens large in the layer, the keyboard in it.
- Full screen keeps only a slim strip of the other sessions.
- Each Esc goes back one step: full screen, then the layer, then the wall.

## 12. Split into up to four sessions with the pane controls

- Part: split (draft D feature 7)
- State: ready, clicked by the script
- Pictures: `fd-12-split-1280.png`, `fd-12-split-1440.png`, `fd-12-split-1920.png`, `fd-12-split-390.png`

Do:

1. In the layer press Split right, pick Chat with... and a session; do it three times.
2. Change to Tickets, Review and Home.
3. On one pane use pin, Where Focus sits (More), Bar only and close.

Must be seen:

- Two, three, then four panes sit next to each other with a thin divider between them; panes keep the order they were opened in.
- Every pane has Full screen, Split right, Split down, Pin, Close and More; under 720 px Split and Pin are in More.
- With four panes Split is not greyed: its menu says four is the most and to close one first.
- The split stays while the page changes.
- Closing a pane gives its room to the others.
- On a phone one session shows at a time and there is no split and no pin in the header.
- A waiting question shows its orange card with answer buttons in every pane; the header is one row of icon buttons beside the title.

## 13. Focus stays open with typed text and split while you change pages

- Part: layer (draft D feature 7)
- State: ready, clicked by the script
- Pictures: `fd-13-stays-open-1280.png`, `fd-13-stays-open-1440.png`, `fd-13-stays-open-1920.png`, `fd-13-stays-open-390.png`

Do:

1. Open two sessions side by side, type a message without sending.
2. Change to Home, Tickets and Review, then press Back.

Must be seen:

- The layer, its split and the typed text stay as they were.
- The page itself does not reload (no flash).
- Back and links work like before.

## 14. Start: continue, fresh start or an earlier session

- Part: sessions (draft D feature 4, 12)
- State: ready, clicked by the script
- Pictures: `fd-14-start-1280.png`, `fd-14-start-1440.png`, `fd-14-start-1920.png`, `fd-14-start-390.png`

Do:

1. Open a ticket that has no session and press Start.
2. Look at the three choices and the earlier sessions list.
3. Pick tool and model and start fresh.

Must be seen:

- One question: continue the last conversation, fresh start, or reopen an earlier session.
- Up to 10 earlier sessions with date and step.
- The usual tool and model are preselected: one click starts it.
- How many helper places are in use; when all are taken, how many wait in line, and a start waits in line.

## 15. Sessions without a ticket

- Part: sessions (draft D feature 6)
- State: ready, clicked by the script
- Pictures: `fd-15-no-ticket-1280.png`, `fd-15-no-ticket-1440.png`, `fd-15-no-ticket-1920.png`, `fd-15-no-ticket-390.png`

Do:

1. Open the New menu in the bar.
2. Start an Empty helper, a Chat helper, a Plain terminal and the Manager.
3. Open Focus and press one of the four buttons at its top.

Must be seen:

- The four choices are at the top of Focus and in the New menu.
- Each new session opens in the layer and is pinned by itself.
- One that is open already says "Already open: go to it" and is not started twice.

## 16. Tool, model and open time on every session

- Part: sessions (draft D feature 12)
- State: ready, clicked by the script
- Pictures: `fd-16-tool-model-1280.png`, `fd-16-tool-model-1440.png`, `fd-16-tool-model-1920.png`, `fd-16-tool-model-390.png`

Do:

1. Open a session that needs you from the bar.
2. Look at the pane: its last lines; open the status pill for model, step and open time.
3. Press Stop in the pane; open an idle session and read its Stop button.
4. Press the status pill of a working session and pick another model there.

Must be seen:

- The open question and the last lines of its screen; no line of tool and model under them.
- Press the status pill in the header: the model (for example "Opus"), the step, how long it is open and how long it stays (warm while it works, or when it closes for being idle), and Open ticket.
- All of it stays current while you look; the keyboard place does not jump.
- Stop in the pane stops its helper; an idle helper's button says Stop idle helper.
- A new model applies when the helper finishes its current step (or at its next start) and says so.

## 17. Chat: messages and ticket events, questions answered inside

- Part: chat (draft D feature 5)
- State: ready, clicked by the script
- Pictures: `fd-17-chat-1280.png`, `fd-17-chat-1440.png`, `fd-17-chat-1920.png`, `fd-17-chat-390.png`

Do:

1. Open a session: it opens in Chat.
2. Answer its waiting question in the orange card and send a message.
3. Switch to Terminal, reload, switch back to Chat.

Must be seen:

- Plain messages with time; done steps and other events as lines between them; the pull request inside the message.
- The waiting question is an orange card above the chat, not a message; once answered it moves into the chat as yours.
- A sent message shows at once; Terminal shows the helper’s screen and the choice stays after a reload.
- Tab never stops on the page under the layer, and a long chat scrolls with the keyboard.

## 18. Files and screenshots in the message box, with a preview before sending

- Part: message box (draft D feature 13)
- State: ready, clicked by the script
- Pictures: `fd-18-message-box-1280.png`, `fd-18-message-box-1440.png`, `fd-18-message-box-1920.png`, `fd-18-message-box-390.png`

Do:

1. Attach a file, paste a screenshot, drop a second file.
2. Remove one, then send.
3. Reload the page.

Must be seen:

- Each one shows as a small preview before sending.
- Removing one takes it out; the sent message carries the rest.
- The box says its limits in plain words; a file over 25 MB is refused.
- The sent message and its files stay after a reload.

## 19. Voice into the message box

- Part: voice (draft D feature 13)
- State: ready, clicked by the script
- Pictures: `fd-19-voice-1280.png`, `fd-19-voice-1440.png`, `fd-19-voice-1920.png`, `fd-19-voice-390.png`

Do:

1. With the relay on, press the microphone and speak.
2. Stop, read the words in the box, edit them.
3. Turn the relay off.

Must be seen:

- While listening the button says so and Esc cancels.
- The words land in the box and are never sent by themselves.
- With the relay off there is no microphone.
- A blocked microphone or nothing heard is one plain sentence.

## 20. All 16 result widgets, small and big

- Part: 16 widgets (draft D feature 10)
- State: ready, clicked by the script
- Pictures: `fd-20-widgets-1280.png`, `fd-20-widgets-1440.png`, `fd-20-widgets-1920.png`, `fd-20-widgets-390.png`

Do:

1. Open the style guide, section Results.
2. Open each widget big, use the arrows to go to the next one, close with Esc.

Must be seen:

- One small widget for each of the 16 kinds: Markdown, Text and logs, Code, JSON and YAML, Table, Web page, PDF, Picture, Video and recording, Audio, Chart, Change, Pull request or issue link, Archive, Plain link, Unknown file.
- Each opens big in an overlay; arrows step through, Esc closes and gives the focus back.
- Empty, loading and error look like the style guide states.

## 21. The same widgets on a tile, in the chat and on a ticket page

- Part: 16 widgets (draft D feature 10)
- State: ready, clicked by the script
- Pictures: `fd-21-widgets-ticket-1280.png`, `fd-21-widgets-ticket-1440.png`, `fd-21-widgets-ticket-1920.png`, `fd-21-widgets-ticket-390.png`

Do:

1. Open Focus and look at the tile of a ticket with results; open its result big.
2. Open the session: each finished step carries its results inside its message; open one big.
3. Open the ticket page and open one result big.

Must be seen:

- The tile shows the newest result small and how many more there are.
- The chat shows the files, check runs and pull request of a step inside that step's message.
- The ticket page shows every result of the ticket as the same widgets as Focus, all 16 kinds from its real files, evidence and links.
- The big overlay is the same one everywhere: arrows step through, Esc closes and gives the focus back.

## 22. A real terminal: type, select, copy and paste

- Part: terminal (draft D feature 5)
- State: ready, clicked by the script
- Pictures: `fd-22-terminal-1280.png`, `fd-22-terminal-1440.png`, `fd-22-terminal-1920.png`, `fd-22-terminal-390.png`

Do:

1. Switch a session to Terminal.
2. Press a key: nothing is sent (watching only).
3. Click into the screen, type a command and press Enter.
4. Paste two lines.
5. Select text and copy it.

Must be seen:

- The helper's real screen with its colours; it starts watching only.
- Keys go to the helper only after a click into the screen (a small keyboard icon shows while typing).
- A paste goes in at once as one block, without its last line end and without a question.
- Selecting and copying works like on any page; Copy copies the selection or the screen.
- While typing the screen follows the size of its pane.
- It can only be reached from this computer (the bridge, ORCH-743).

## 23. Opening, zooming, pinning and splitting animate

- Part: motion (draft D feature 7, 8, 9)
- State: ready, clicked by the script
- Pictures: `fd-23-motion-1280.png`, `fd-23-motion-1440.png`, `fd-23-motion-1920.png`, `fd-23-motion-390.png`

Do:

1. Open a result big and close it.
2. Zoom a tile into the layer, go full screen and back.
3. Add two panes beside and close one (a phone: open another session from the wall).
4. Put the layer back in the bar, pin a session, zoom a tile again.

Must be seen:

- Each change moves smoothly and quickly, nothing jumps: the pane grows out of its tile, the panes slide to their new place, the panel fades out when it closes, a pinned tile slides to the Pinned band.
- Only transform and opacity move, each move at most 240 ms, layout shift at most 0.1.
- The picture is taken after the move ends.

## 24. With reduced motion everything stays still

- Part: reduced motion (draft D feature 7, 8, 9)
- State: ready, clicked by the script
- Reduced motion on for this step.
- Pictures: `fd-24-reduced-motion-1280.png`, `fd-24-reduced-motion-1440.png`, `fd-24-reduced-motion-1920.png`, `fd-24-reduced-motion-390.png`

Do:

1. Turn on reduced motion in the system settings.
2. Repeat step 23.

Must be seen:

- Every change happens at once, without movement.
- The live last lines still update.

## 25. Phone width: one session at a time

- Part: phone width (draft D feature 7)
- State: ready, clicked by the script
- Pictures: `fd-25-phone-1280.png`, `fd-25-phone-1440.png`, `fd-25-phone-1920.png`, `fd-25-phone-390.png`

Do:

1. At 390 wide open Focus, open a session, then try to put the layer on the right.

Must be seen:

- The wall is one column.
- The layer opens at the bottom and shows one session; right falls back to bottom.
- Nothing scrolls sideways; every button can be reached.
- The layer is a sheet over most of the screen with the question card and its buttons; the Focus bar under it stays one row.

## 26. Earlier sessions in the History tab, reopened with one click

- Part: sessions (draft D feature 4)
- State: ready, clicked by the script
- Pictures: `fd-26-history-1280.png`, `fd-26-history-1440.png`, `fd-26-history-1920.png`, `fd-26-history-390.png`

Do:

1. Open a session in the layer, press More and then History.
2. Press Reopen on an earlier session.

Must be seen:

- Up to 10 sessions of the ticket, newest first, each with its time, first message and number of messages.
- The session in use says In use; one that is not on this computer has no Reopen.
- Reopen starts the helper on that conversation and the list closes.

## 27. Change the model of a running session

- Part: sessions (draft D feature 12)
- State: pending, waits for: Start choice, earlier sessions and sessions without a ticket (crew tasks of the Wall and sessions stage)
- Pictures: `fd-27-model-choice-1280.png`, `fd-27-model-choice-1440.png`, `fd-27-model-choice-1920.png`, `fd-27-model-choice-390.png`

Do:

1. Open the model choice of a running session.

Must be seen:

- A new model applies from the next fresh start and says so.

## 28. An epic and its helpers in one place

- Part: layer
- State: ready, clicked by the script
- Pictures: `fd-28-groups-1280.png`, `fd-28-groups-1440.png`, `fd-28-groups-1920.png`, `fd-28-groups-390.png`

Do:

1. Open Focus while an epic has a main helper and helpers on its tickets.
2. Click the epic's tile.
3. Click another helper in the list beside the session, then write it a message.

Must be seen:

- The epic is one tile with its helpers counted ("3 helpers · 2 small helpers"), orange while one of them needs you.
- The click opens the helper that needs you, with the main helper, every helper, the small helpers (watch only) and Earlier sessions beside it.
- A click on a helper shows it in the same pane; the message box says who gets the message.
- On a phone the list is one line that scrolls inside itself.

## 29. The address of a ticket opens its session

- Part: layer (draft D feature 3)
- State: ready, clicked by the script
- Pictures: `fd-29-address-1280.png`, `fd-29-address-1440.png`, `fd-29-address-1920.png`, `fd-29-address-390.png`

Do:

1. Open the address of a ticket's session (#addon/focus/t/<ticket>) in a new tab.
2. Open the address of a ticket that does not exist.

Must be seen:

- The wall shows with that session open in the layer, the keyboard in its pane.
- An unknown ticket shows the wall, opens nothing and says "There is no ticket with this address. Find it on the Tickets page." with an Open Tickets button

## 30. Keyboard only: wall, layer and back to the bar

- Part: wall (draft D feature 8)
- State: ready, clicked by the script
- Pictures: `fd-30-keyboard-1280.png`, `fd-30-keyboard-1440.png`, `fd-30-keyboard-1920.png`, `fd-30-keyboard-390.png`

Do:

1. Without a mouse, press Tab until a tile is marked, then Enter.
2. Press Esc until the layer is back in the bar.

Must be seen:

- Enter opens the session in the layer with the keyboard in it.
- Each Esc goes back one step; at the end the keyboard is on the bar.

## 31. Two tabs: a pin and a name show in both

- Part: sessions (draft D feature 11)
- State: ready, clicked by the script
- Pictures: `fd-31-two-tabs-1280.png`, `fd-31-two-tabs-1440.png`, `fd-31-two-tabs-1920.png`, `fd-31-two-tabs-390.png`

Do:

1. Open Focus in two tabs.
2. In one, pin a session and give it a name.

Must be seen:

- The other tab shows the pin and the name within a few seconds, without a reload.

## 32. A session that ends while it is open

- Part: sessions (draft D feature 4)
- State: ready, clicked by the script
- Pictures: `fd-32-ended-1280.png`, `fd-32-ended-1440.png`, `fd-32-ended-1920.png`, `fd-32-ended-390.png`

Do:

1. Open a working session in the layer.
2. Let its helper stop.

Must be seen:

- Its tile leaves Working and says No session.
- Its pane header no longer says Working.
- Its pane offers the Start choice.

## 33. Start the Manager in a chosen permission mode

- Part: sessions (draft D feature 6)
- State: ready, clicked by the script
- Pictures: `fd-33-permissions-1280.png`, `fd-33-permissions-1440.png`, `fd-33-permissions-1920.png`, `fd-33-permissions-390.png`

Do:

1. Open the New menu in the bar and pick Bypass permissions in its Permissions row.
2. Start the Manager.
3. In its pane press the status pill and pick Auto under Permissions.
4. In a workspace that allows at most Auto, open the New menu.

Must be seen:

- The row shows the tool's modes: Default, Accept edits, Auto, Bypass permissions.
- Bypass permissions shows one plain warning the first time; the Manager starts in it and the status popover of its pane marks Bypass permissions (it says a change restarts the helper).
- Auto ends the session and goes on with the same conversation; the popover marks Auto.
- Bypass permissions is off when the workspace does not allow it and says why.

## 34. Results shelf beside or above the chat

- Part: chat (draft D feature 10)
- State: ready, clicked by the script
- Pictures: `fd-34-shelf-1280.png`, `fd-34-shelf-1440.png`, `fd-34-shelf-1920.png`, `fd-34-shelf-390.png`

Do:

1. Open a session whose ticket has no results, then one with a pull request.
2. Place Focus at the bottom, on the right, in full screen; then on a phone.

Must be seen:

- Without results the column beside the chat says "Nothing yet. Pictures, pages and tables show up here."; the strip above the chat (on the right, on a phone) takes no row (ORCH-2314).
- The results sit on a shelf called Results, the same widgets as on the ticket page; a click opens them big.
- At the bottom (from 900 px wide) a 360 px column beside the chat; in full screen a 320 px column; on the right and on a phone a one-row strip above the chat.

## 35. More room for the terminal: fold the sides away

- Part: terminal
- State: ready, clicked by the script
- Pictures: `fd-35-fold-1280.png`, `fd-35-fold-1440.png`, `fd-35-fold-1920.png`, `fd-35-fold-390.png`

Do:

1. Open a helper of an epic that waits for an answer, in full screen, and pick Terminal.
2. Press the arrow beside the helper list and the one beside Results; reload the page; press them again.

Must be seen:

- In the Terminal view the waiting question sits at the top of the Results column, not above the terminal; "Nothing yet" hides under it.
- The pane title shows whole; on a phone there is no split and no pin in the header. The terminal line says "Watch only" beside Turn typing on.
- Each side folds to a narrow strip with its arrow (both arrows look the same) and the terminal takes the room; the question goes back above the terminal while Results is folded.
- After a reload the sides stay folded; the arrows open them again. On a phone there is nothing to fold.

## 36. Focus at the bottom over Review keeps the cards in reach

- Part: layer
- State: ready, clicked by the script
- Pictures: `fd-36-review-reach-1280.png`, `fd-36-review-reach-1440.png`, `fd-36-review-reach-1920.png`, `fd-36-review-reach-390.png`

Do:

1. Open Review while cards wait on you.
2. Open a session that waits on you and split one with nothing in it yet beside it; place Focus at the bottom.

Must be seen:

- The panel keeps the page heading and a card above it; the card's answer buttons sit above the panel, never under it.
- The pane with nothing in it yet waits as a chip on the bar; the session that waits on you fills the panel.

