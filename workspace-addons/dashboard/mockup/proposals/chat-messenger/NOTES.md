# Chat page as a messenger (draft, lane chat-messenger, ORCH-2161)

Owner: "the chat page itself can take a overhaul, feel more like a solid chat messenger, like slack, discord or
something but right now feels like a badly designed online chat window".

Drafts only: nothing here is built. One static page on the master design system, `messenger.html` + `messenger.js`;
the options are picked in the address (`?frame=full|card&msg=rows|bubbles&list=a|b|c&composer=a|b&presence=a|b|c&
history=scroll|button&view=helper|ticket&state=working|ready|stopped|error&demo=day|empty|sent|failed&screen=list|thread
&relay&staged`). Open it from a static server rooted at the repo. Pictures at 390 and 1440 (one at 1920): `shots/`.
The "Now" pictures are the real dashboard on current develop (fresh home, sample tickets and chat lines).

## What is wrong today (walked on develop, 25 Nov)

1. Two looks on one page: the helper chat is a loose list and a short box under a big "Chat" title; a ticket chat is a
   bordered three-column panel with other message rows and another Send button ("Send and start helper").
2. The conversation does not fill the window; at 1440 x 800 a third of the height is empty below the message box.
3. Every message is its own bubble with its own time line under it; nothing is grouped; the ticket card sits in a
   bubble (box in a box) and hides its facts behind a "Details" toggle.
4. The list: a wide "New chat" button on top, "#" tiles, capital section labels, the helper at the bottom.
5. The message box is one line with a grey Send that looks switched off, and a sentence about 04:00 under it. No way
   to add a file.
6. Nothing says what the helper is doing. You learn that it is not running a minute after you wrote.
7. Phone: "Chat" title, then a second header with "‹ Chats"; the box floats in the middle of the screen.

## The options

| Part | A (recommended) | B | C |
|---|---|---|---|
| Frame | full height, list beside conversation, no page title; the same frame for helper, ticket, workspace and group chats | the same inside a bordered card under the "Chat" title | |
| Messages | rows: picture, name and time once per group, messages sent close together stay together, day line, ticket card with its facts shown | bubbles left and right | |
| List | "Chats" + New chat, search, helper pinned on top with its status dot, then Tickets, Workspaces, Groups; title and two preview lines | one list by time with All / Unread / Needs you | one-line rows with counts |
| Message box | one box: words, files inside it, Attach, Send (filled only when there is something to send) | one slim row | |
| Helper status | one line under the helper's name: working on …, ready, not running (Start helper), stopped (See what to fix) | a "Helper now" panel on the right | a line above the message box |
| Earlier days | scroll up in the same conversation; the day line says the helper starts without yesterday's conversation | an "Earlier" button as today | |

States drawn: empty chat (three starters), answer on its way ("Your helper is writing…"), not sent (Try again), saved
while the helper is not running.

## What the challenge changed

Opus (as IT engineer, business manager, marketing person) and Codex (gpt-6-astra, on the pictures) both picked A for
every part. Changed after them: previews in the list are two full lines and the list is wider (the cut-off previews
were the main risk); one name, "Your helper", in list, header and messages; the second search, the second way to open
the ticket and the top bar's "Chat" button on the Chat page are gone; the open chat no longer shows an unread count;
the status has one dot (on the picture), not two; "is writing…" shows only while an answer is on its way, not next to
"Working on …"; Send is dimmed while the box is empty; the key hint is two words; the day line says what "new day"
means; the phone's ticket chat got a "Ticket" button; added the states not sent, saved while not running, stopped
with a reason, empty chat. Not taken: a "Needs you" group on top of list A (the row already says "Needs you").

## For the build (when accepted)

- The layout here is inline from tokens; the build adds the parts to the master (`widgets.css`: chat frame, list row,
  message row, day line, status line) with gallery entries, and replaces `pages/chat.css` rules (R6.2).
- The message box is the master's `UI.composer`; attaching in Chat needs the chat line to carry files (new).
- "Watch live" only when the Live add-on is on (R1.1/R1.2: through the add-on, never named in the core).
- Earlier days by scrolling needs `/api/chat/day/<day>` loaded on scroll; the helper's daily fresh start stays.
- `chat.html` and `chat-relay.html` in `mockup/chat/` are replaced by the accepted screen in the same PR as the build.
