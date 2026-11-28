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

### ORCH-2095 polish
- The helper row shows "H" (Helper), the same letter as on its messages in the product.
- Product now matches the mockup here: one page heading, thread title at 20 px, times for today as a plain clock (11:56).


## Caught up with the messenger (ORCH-2176, 28 Nov)

- `chat.html`: now the Chat page as the product draws it since ORCH-2171 (messenger, option A of lane chat-messenger):
  the list beside the conversation, rows grouped by writer under a day line, the ticket card with its facts shown, the
  message box with Attach and Send. It is the page's own markup with the master and the dashboard sheets and no
  scripts, taken from the running dashboard on sample data, so it cannot drift from the product's look. The old
  simple helper chat with the Preview pill is gone (the product no longer has it).
- The top bar has no Chat button on this page (ORCH-2176, the draft's own point). The phone bar keeps More lit on
  Chat, as the accepted draft shows it (`proposals/chat-messenger/shots-build/after-chat-390.png`).
- `chat-no-helper.html`: the empty chat when no helper tool is set up (ORCH-2149): "No helper is set up yet" with
  Set up a helper, and "Not set up yet" under the name, instead of three starters for a helper that is not there.
- `chat-relay.html` is unchanged (the earlier draft of the list with other workspaces).


## 28 Nov owner decisions (walk, batch chat-browser: O-17, O-18, O-19, O-26, W-045, W-055)

- `chat.html`: the ticket row with this workspace's own open question has no unread number any more (O-18: only
  what another workspace wrote counts; the question waits in Review). New section "Workspaces" in the list with one
  conversation and its number (2). Two helper messages show as short entries (O-19): one with the helper's own short
  line (`orch chat reply --summary`), one with the word "Excerpt" and the start of the text; both with "Open
  message". A person's message is always as written.
- `chat-workspace.html` (new, O-26): the conversation with another workspace, in Chat: their long text and this
  workspace's helper's long text as short entries, a file, a handed-over task with "Waiting for Sales", what orch
  knows about delivery ("Passed on to SAL-12", "Not picked up yet"), and the message box. The open conversation
  shows no number.
- `chat-new.html` (new, O-17): "New chat" asks who with: Your helper, "A ticket" (the six newest open tickets, the
  rest by search), "A workspace" (only when one is connected). Nothing is made by picking.
- `chat-message.html` (new, O-19 and W-055): "Open message": the whole original drawn from its Markdown, when it
  was written, where orch passed it on, Close. The same dialog opens from a row of the Relay page's log.
- W-045: in an empty chat "Show earlier messages" is the last line of the welcome block (under the starters), not a
  button alone above the day line. `chat-no-helper.html` is unchanged (no starters there).
- `chat-relay.html` stays as the earlier draft of the grouped list (13 Nov); the product is `chat.html` and
  `chat-workspace.html`.
- Components: only master classes (`.thread-line`, `.eyebrow`, `.stack-sm`, `.btn outline sm`, `.banner`,
  `.badge needs`, `.msg-state`, `dialog.dialog.dialog-fit` with `.dialog-body`, `.fv-md`). The reading dialog is
  480 px wide (the master dialog); a wider reading size is asked of the master's owner (b301), see the pull request.
