- Merged the B monitoring layout using real tickets, gift-box answers, survey preview, times and pending changes. Removed fabricated live events; rows open the watcher. Kept the alternative.
- Shared snapshot: 3 need you; Anna and Ben own tickets; Helper is the helper. Newsletter 23 min; survey 12:26; sign 12:32; typo 12:27; question 27 min.
- Motion: retain entry, progress and status transitions; honor reduced motion. Preview stays collapsed until requested.
- Performance target: no new dependencies or external network requests; interactions below 100 ms and animation frames below 16.7 ms. Loading and empty states remain available through the Preview pill.

## Revised after the owner's comment (13 Nov)

focus.html
- Every Copy link copies the result address and shows a small “Link copied” message without leaving the page.
- Copy clicks stop before any surrounding row can open another page; a blocked clipboard shows the address without navigating.

focus-help.html
- The result’s Copy link uses the same clipboard action and small confirmation.
- The help sheet and shared Preview pill remain available.

opus-focus.html
- Copy link now copies the real survey result address instead of only changing its label.
- The shared copy action prevents navigation and shows the same confirmation.

focus-ticket.html
- Focus supports technical and non-technical people: plain updates come first, with the live terminal one click away.
- Added the live Now card for “Plan the autumn newsletter”, Task 4 of 4: “Send a test mail to the team”, plus a dimmed five-line terminal peek.
- Added inline recipient answers, messages, a Newsletter draft page preview and a “Pull request: Update opening hours page” review card; both previews open in place.
- The labelled demo advances through link, text and phone checks; pausing stops updates, and no real mail is sent.
- Kept shared navigation, Preview, loading and empty states, entry motion and reduced-motion support.

focus-ticket-terminal.html
- Opens with the live terminal on the left and plain updates, questions, links and messages on the right.
- Terminal commands build and check the autumn draft and prepare a team test; the cursor stays steady.
- The Terminal toggle remembers the chosen mode; answers, messages and review choices survive page changes in this session.
- The layout stacks on narrow screens and includes loading and empty states.

focus-ticket-fullscreen.html
- Opens the terminal view with the sidebar and topbar hidden so the ticket uses the workspace.
- A visible “Exit full screen” button and Escape restore navigation; the ticket header and Preview pill stay available.
- Questions, previews and messages remain beside the terminal during deep work.

Validation: checked all three ticket pages in loaded, loading and empty states at 390, 1280 and 1920 pixels; checked clipboard text and no navigation on all four page types, remembered mode, full screen and Escape, messages after reload and preview opening. JavaScript syntax checks passed.
