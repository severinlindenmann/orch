- Aligned shell counts, helper naming, headers and shared preview controls.
- Shared snapshot: 3 need you; Anna and Ben own tickets; Helper is the helper. Newsletter 23 min; survey 12:26; sign 12:32; typo 12:27; question 27 min.
- Motion: retain entry, progress and status transitions; honor reduced motion. Preview stays collapsed until requested.
- Performance target: no new dependencies or external network requests; interactions below 100 ms and animation frames below 16.7 ms. Loading and empty states remain available through the Preview pill.

## Revised after the owner's comment (13 Nov)

- `chat.html`: Kept the simple helper conversation with relay off and added a visible link to preview relay on.
- `chat.html`: Preserved the shared shell, Preview pill, loading and empty states, and message motion.
- `chat-relay.html`: With relay on, conversations are grouped under This workspace, Other workspaces and Groups, with search, coloured workspace initials and unread counts.
- `chat-relay.html`: Added ten conversations about the demo work; opening a conversation shows its workspace or group, participants and each sender's workspace.
- `chat-relay.html`: Search, conversation switching and preview messages work; loading and empty states and reduced-motion support use the shared design.


## Revised after the owner's comment (13 Nov)

### chat-relay.html

- Allowed conversation snippets to wrap so the full sentence can be read without clipping.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### chat.html

- Made the phone filter and workspace link visible without an options disclosure.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.


## Revised after the owner's comment (13 Nov)

Round 2 — working shared components.

### chat-relay.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

### chat.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

Round 2 validation: the shared browser sweep passed all 171 loaded/loading/empty page checks and 144 dialog/viewer checks. Targeted phone, question, keyboard, calendar, full-screen and toolbar checks also passed. See `../system/COMPONENT-QA.md` for the complete inventory and results.
