# Click-through: the new Focus (draft D)

Generated from `e2e/focus_d/steps.cjs` by `node e2e/focus_d/clickthrough.cjs --write-md`; do not edit by hand.
26 steps: 9 ready (the script clicks them), 17 pending (not built yet).

For every step take one picture at each width: 1280, 1920 and 390. The name is given per step;
the runner saves them as `<name>-<width>.png`, and `--target draft` saves the draft D picture beside it as
`<name>-<width>-draft.png`.

How to run: see `e2e/focus_d/README.md`.

## 1. The dashboard opens

- Part: start
- State: ready, clicked by the script
- Pictures: `fd-01-dashboard-1280.png`, `fd-01-dashboard-1920.png`, `fd-01-dashboard-390.png`

Do:

1. Open the dashboard link of the test workspace.

Must be seen:

- Home shows its content, no loading shape stays.
- At 390 wide nothing scrolls sideways.

## 2. Today's Focus still works with Preview off

- Part: start
- State: ready, clicked by the script
- Pictures: `fd-02-focus-today-1280.png`, `fd-02-focus-today-1920.png`, `fd-02-focus-today-390.png`

Do:

1. Leave the Preview switch off.
2. Open Focus from the side bar.

Must be seen:

- Today's Focus opens with its list of live helpers.
- Nothing of the new Focus shows.

## 3. Turn the new Focus on with the Preview switch

- Part: start
- State: ready, clicked by the script
- Pictures: `fd-03-preview-on-1280.png`, `fd-03-preview-on-1920.png`, `fd-03-preview-on-390.png`

Do:

1. Open Settings and turn on the Preview switch for the new Focus.
2. Open Focus from the side bar.

Must be seen:

- Focus opens as the new Focus, marked Preview (the wall of step 4 fills it).
- The switch is marked Preview.
- Turning it off again brings back today's Focus.

## 4. The live wall in bands

- Part: wall (draft D feature 1)
- State: pending, waits for: The wall (crew task wall)
- Pictures: `fd-04-wall-1280.png`, `fd-04-wall-1920.png`, `fd-04-wall-390.png`

Do:

1. Open Focus.
2. Watch a working tile for 10 seconds.

Must be seen:

- Bands in this order: Pinned, Needs you, Working, In line, Idle, No session.
- One summary line on top.
- Each tile says in one plain sentence what its helper does.
- A working tile adds its newest last line by itself.

## 5. A session that needs you is an orange tile

- Part: wall (draft D feature 2)
- State: pending, waits for: The wall (crew task wall)
- Pictures: `fd-05-needs-you-1280.png`, `fd-05-needs-you-1920.png`, `fd-05-needs-you-390.png`

Do:

1. Find the tile of the helper that waits for an answer.
2. Open it and answer.

Must be seen:

- The tile is orange and first after the pinned ones.
- Its sentence is the question.
- Nothing can be answered on the wall itself; after the answer the tile turns back to Working.

## 6. Focus button on a ticket and Open ticket on a session

- Part: wall (draft D feature 3)
- State: ready, clicked by the script
- Pictures: `fd-06-focus-button-1280.png`, `fd-06-focus-button-1920.png`, `fd-06-focus-button-390.png`

Do:

1. Open Tickets and press the Focus button of a row.
2. Open a ticket page and press its Focus button.
3. In the session press Open ticket, also from full screen.

Must be seen:

- Every ticket row and every ticket page has the button; it says Watch, Answer, Open or Start to fit the ticket.
- The session opens in the layer and the page stays.
- Open ticket goes back to the same ticket page; the session stays open.

## 7. Pin a session and give it your own name

- Part: wall (draft D feature 9)
- State: pending, waits for: The wall (crew task wall)
- Pictures: `fd-07-pin-name-1280.png`, `fd-07-pin-name-1920.png`, `fd-07-pin-name-390.png`

Do:

1. Pin a working session.
2. Click its name, type a new one and press Enter.

Must be seen:

- The pinned session moves to the Pinned band and gets a chip in the bar.
- The new name shows on its tile, its pane and its chip.

## 8. Works with 24 and more sessions

- Part: wall (draft D feature 11)
- State: pending, waits for: The wall (crew task wall)
- Pictures: `fd-08-many-1280.png`, `fd-08-many-1920.png`, `fd-08-many-390.png`

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
- Pictures: `fd-09-bar-1280.png`, `fd-09-bar-1920.png`, `fd-09-bar-390.png`

Do:

1. Open Home, then Tickets, then Review.
2. Press the "in line" count in the bar.
3. Type in the list's search.

Must be seen:

- The bar is under every page, calm, on one line that never wraps.
- Chips only for sessions that need you and pinned ones; the rest are counts such as "9 in line".
- A count opens a list you can search.

## 10. The layer at the bottom, on the right, full screen, to the bar, to the side

- Part: layer (draft D feature 7)
- State: ready, clicked by the script
- Pictures: `fd-10-layer-1280.png`, `fd-10-layer-1920.png`, `fd-10-layer-390.png`

Do:

1. Open a session from the bar.
2. Change to Tickets, Review and Home.
3. Use Place: bottom, right, full screen; press Esc twice.
4. Open it again, minimise it to the bar, then put it to the side and open it from the edge.
5. Make it larger, then reload the page.

Must be seen:

- Each place works and the page stays usable behind it; on a phone there is no right.
- The layer stays open while the page changes.
- Esc goes back one step: full screen, then the panel, then the bar.
- In full screen Tab stays in the layer.
- Minimise leaves only the bar; to the side leaves a slim edge.
- After the reload the layer opens where it was last, at the same size.

## 11. Zoom and full screen, Esc goes one step back

- Part: layer (draft D feature 8)
- State: pending, waits for: The layer: bottom, right, full screen (crew task layer)
- Pictures: `fd-11-zoom-1280.png`, `fd-11-zoom-1920.png`, `fd-11-zoom-390.png`

Do:

1. Click a tile on the wall.
2. Press full screen.
3. Press Esc twice.

Must be seen:

- The tile grows into a large view.
- Full screen keeps only a slim strip of the other sessions.
- Each Esc goes back one step: full screen, then zoom, then the wall.

## 12. Split into two and three sessions with the pane controls

- Part: split (draft D feature 7)
- State: ready, clicked by the script
- Pictures: `fd-12-split-1280.png`, `fd-12-split-1920.png`, `fd-12-split-390.png`

Do:

1. In the layer press Add beside twice.
2. Change to Tickets, Review and Home.
3. On one pane use pin, Place, minimise and close.

Must be seen:

- Two, then three panes sit next to each other; on the right they are stacked.
- Every pane has pin, add beside, place, minimise and close.
- The split stays while the page changes.
- Closing a pane gives its room to the others.
- On a phone one session shows at a time and there is no add beside.

## 13. Focus stays open with typed text and split while you change pages

- Part: layer (draft D feature 7)
- State: ready, clicked by the script
- Pictures: `fd-13-stays-open-1280.png`, `fd-13-stays-open-1920.png`, `fd-13-stays-open-390.png`

Do:

1. Open two sessions side by side, type a message without sending.
2. Change to Home, Tickets and Review, then press Back.

Must be seen:

- The layer, its split and the typed text stay as they were.
- The page itself does not reload (no flash).
- Back and links work like before.

## 14. Start: continue, fresh start or an earlier session

- Part: sessions (draft D feature 4, 12)
- State: pending, waits for: Start choice, earlier sessions and sessions without a ticket (crew tasks of the Wall and sessions stage)
- Pictures: `fd-14-start-1280.png`, `fd-14-start-1920.png`, `fd-14-start-390.png`

Do:

1. Open a ticket that has no session and press Start.
2. Look at the three choices and the earlier sessions list.
3. Pick tool and model and start fresh.

Must be seen:

- One question: continue the last conversation, fresh start, or reopen an earlier session.
- Up to 10 earlier sessions with date and step.
- The usual tool and model are preselected: one click starts it.

## 15. Sessions without a ticket

- Part: sessions (draft D feature 6)
- State: pending, waits for: Start choice, earlier sessions and sessions without a ticket (crew tasks of the Wall and sessions stage)
- Pictures: `fd-15-no-ticket-1280.png`, `fd-15-no-ticket-1920.png`, `fd-15-no-ticket-390.png`

Do:

1. Open the New menu in the bar.
2. Start an Empty helper, a Chat helper, a Plain terminal and the Manager.

Must be seen:

- The four choices are at the top of Focus and in the New menu.
- Each new session is pinned by itself.

## 16. Tool, model and open time on every session

- Part: sessions (draft D feature 12)
- State: pending, waits for: Live data for every session (crew task live-data)
- Pictures: `fd-16-tool-model-1280.png`, `fd-16-tool-model-1920.png`, `fd-16-tool-model-390.png`

Do:

1. Look at a tile and at a pane header.
2. Open the model choice of a running session.

Must be seen:

- Tool and model are shown (for example "Claude CLI · Opus").
- How long it is open and when it closes for being idle.
- A new model applies from the next fresh start and says so.

## 17. Chat: messages with the results inside

- Part: chat (draft D feature 5)
- State: pending, waits for: Chat (crew tasks of the Chat stage)
- Pictures: `fd-17-chat-1280.png`, `fd-17-chat-1920.png`, `fd-17-chat-390.png`

Do:

1. Open a session in Chat view.
2. Read the messages and press a result inside one.

Must be seen:

- Plain messages with time; step events between them.
- Results show as small widgets and open big.

## 18. Files and screenshots in the message box, with a preview before sending

- Part: message box (draft D feature 13)
- State: pending, waits for: Chat (crew tasks of the Chat stage)
- Pictures: `fd-18-message-box-1280.png`, `fd-18-message-box-1920.png`, `fd-18-message-box-390.png`

Do:

1. Attach a file, paste a screenshot, drop a second file.
2. Remove one, then send.

Must be seen:

- Each one shows as a small preview before sending.
- Removing one takes it out; the sent message carries the rest.

## 19. Voice into the message box

- Part: voice (draft D feature 13)
- State: pending, waits for: Chat (crew tasks of the Chat stage)
- Pictures: `fd-19-voice-1280.png`, `fd-19-voice-1920.png`, `fd-19-voice-390.png`

Do:

1. With the relay on, press the microphone and speak.
2. Stop, read the words in the box, edit them.
3. Turn the relay off.

Must be seen:

- While listening the button says so and Esc cancels.
- The words land in the box and are never sent by themselves.
- With the relay off there is no microphone.

## 20. All 16 result widgets, small and big

- Part: 16 widgets (draft D feature 10)
- State: pending, waits for: Result widgets and big overlay in the style guide (ORCH-263)
- Pictures: `fd-20-widgets-1280.png`, `fd-20-widgets-1920.png`, `fd-20-widgets-390.png`

Do:

1. Open the style guide, section Results.
2. Open each widget big, use the arrows to go to the next one, close with Esc.

Must be seen:

- One small widget for each of the 16 kinds: Markdown, Text and logs, Code, JSON and YAML, Table, Web page, PDF, Picture, Video and recording, Audio, Chart, Change, Pull request or issue link, Archive, Plain link, Unknown file.
- Each opens big in an overlay; arrows step through, Esc closes and gives the focus back.
- Empty, loading and error look like the style guide states.

## 21. The same widgets on a ticket page

- Part: 16 widgets (draft D feature 10)
- State: pending, waits for: Result widgets and big overlay in the style guide (ORCH-263)
- Pictures: `fd-21-widgets-ticket-1280.png`, `fd-21-widgets-ticket-1920.png`, `fd-21-widgets-ticket-390.png`

Do:

1. Open a ticket with results.
2. Open one result big.

Must be seen:

- The ticket shows the same widgets as Focus.
- The big overlay is the same one.

## 22. A real terminal: type, select, copy and paste

- Part: terminal (draft D feature 5)
- State: pending, waits for: Terminal in the browser, after the security review and the owner's choice (Terminal stage)
- Pictures: `fd-22-terminal-1280.png`, `fd-22-terminal-1920.png`, `fd-22-terminal-390.png`

Do:

1. Switch a session to Terminal.
2. Click in it and type a command, select text, copy it, paste it back.

Must be seen:

- It behaves like the Terminal app: typing, selection, copy and paste.
- Copy all copies the screen text.
- It can only be reached from this computer.

## 23. Opening, zooming, pinning and splitting animate

- Part: motion (draft D feature 7, 8, 9)
- State: pending, waits for: Look and motion (Look and motion stage)
- Pictures: `fd-23-motion-1280.png`, `fd-23-motion-1920.png`, `fd-23-motion-390.png`

Do:

1. Open the layer, zoom a tile, pin a session, add a pane beside, each once.

Must be seen:

- Each change moves smoothly and quickly, nothing jumps.
- The picture is taken after the move ends.

## 24. With reduced motion everything stays still

- Part: reduced motion (draft D feature 7, 8, 9)
- State: pending, waits for: Look and motion (Look and motion stage)
- Reduced motion on for this step.
- Pictures: `fd-24-reduced-motion-1280.png`, `fd-24-reduced-motion-1920.png`, `fd-24-reduced-motion-390.png`

Do:

1. Turn on reduced motion in the system settings.
2. Repeat step 23.

Must be seen:

- Every change happens at once, without movement.
- The live last lines still update.

## 25. Phone width: one session at a time

- Part: phone width (draft D feature 7)
- State: pending, waits for: The layer: bottom, right, full screen (crew task layer)
- Pictures: `fd-25-phone-1280.png`, `fd-25-phone-1920.png`, `fd-25-phone-390.png`

Do:

1. At 390 wide open Focus, open a session, then try to put the layer on the right.

Must be seen:

- The wall is one column.
- The layer opens at the bottom and shows one session; right falls back to bottom.
- Nothing scrolls sideways; every button can be reached.

## 26. Earlier sessions in the History tab, reopened with one click

- Part: sessions (draft D feature 4)
- State: ready, clicked by the script
- Pictures: `fd-26-history-1280.png`, `fd-26-history-1920.png`, `fd-26-history-390.png`

Do:

1. Open a session in the layer and press History (in More when the pane is narrow).
2. Press Reopen on an earlier session.

Must be seen:

- Up to 10 sessions of the ticket, newest first, each with its time, first message and number of messages.
- The session in use says In use; one that is not on this computer has no Reopen.
- Reopen starts the helper on that conversation and the list closes.

