# Review (15 Nov 2026)

- `review.html` is the Review page of the dashboard (`#review`, product: `web/pages/review.js` + the kit's `review.js`): heading "Review" with
  the count, the deck, and the "All cards" list beside it (hidden below 1440 px since ORCH-172, so the card gets the page width at 1280). Same demo cards as the approved draft
  (`proposals/swipe-review/`, left untouched).
- Reached from Home: "Review all" in the needs-you block (`home/home.html`). It is not in the sidebar.
- The topbar "New ticket" is an outline button here; the answer is the primary action.
- Waiting / Answered switch above the deck as in the product (kit `UI.reviewPage`). 17 Nov (ORCH-172): Answered shows the master's
  `UI.answerRecord`: ticket key and title (a link) on every card, the question as title when the card has none, tiles about
  344x216 (twice the old 172x108), a click or Enter on a tile opens it large (`UI.reviewViewer`: fits the width, tall
  pictures scroll, words in full in short lines, arrows go to the other tiles). No empty "Reviewed" tile. The waiting
  card's question text keeps lines of at most 75 characters.
- No Decisions tab: the ticket page shows card answers under its questions ("Earlier answers"), with "What applies now" on top: `../ticket/ticket-answers.html`.
- No extra chip on a card: an answer is a plain click.
- 16 Nov (ORCH-65): cards carry the whole question text, a marked suggestion ("Suggested: Build it" on the card and under
  the button; "Suggested" on an option), a Today tile beside the options of a choice, the helper's links in the footer
  (Mockup, Issue …), pictures that fit their pane on a dark ground with a zoom button per side, and sets
  ("Home look") in the All cards list with "n of m waiting".
- No swipe (owner 16 Nov): the card does not move with the finger or mouse and does not fly away; answers are the
  buttons and the arrow keys, the answered card fades.
- 16 Nov (ORCH-110): a choice whose options have no pictures (a plain question) shows plain option rows with the whole
  title and its description: no dark frame, no empty picture box, no zoom, and the letter chip only for short ids (A, B).
- 16 Nov (ORCH-77): "Accepted for you" card under "All cards" (the Reviewer's Done-for-you tickets of today): ticket link, the why line, a Send back button that asks for a short note, or "Sent back". Hidden when nothing was accepted. It stays on a phone width (below the deck) while the All cards aside hides. Settings > General has the switch "Accept small finished work for me".
- 17 Nov (ORCH-79): Settings > General has the switch "Put new versions live without my click" under "Accept small finished work for me" (off by default; only the owner turns it on). On: a release Merge card with every check green merges by itself and the card shows as answered by the release keeper.
- 17 Nov (ORCH-183, persona test): Send back on a Check result opens the "What should change?" box (it never goes
  out without words) and the separate Comment button is left out there; an answer waits 6 s before it is saved, so
  Undo takes it back for real (after that Undo is off and the toast says it is already saved); the "What was done"
  box is as tall as its words, with the result's own pictures, pages and PDFs as tiles under it; the card gives up
  height so the answers and Later stay on screen at 1440x900 and 390x844; "Done when is not fully covered" says what
  to do; a Factory proposal shows its title, goal and time like Home.
- 17 Nov (ORCH-183, owner choice B): a Factory start on Review has Home's buttons Not now, Change it, Start (Start last), all
  outlined, in place of the three answers; the arrow keys do not answer it.
- 17 Nov (ORCH-294): picture tiles of a card (Home row, ticket page, Answered) fill the row: Before and After, or A and B, side by side, each at least 320 px wide and 216-360 px tall (kit `.decision-shown` / `.decision-shot`, no page CSS). A card alone on Home shows all its pictures; a set shows the proposal of each card. A long "why" line on the ticket page folds to three lines with Show more / Show less (kit `UI.moreText`). Click or Enter still opens a picture large; every row names its ticket key. UX checklist at 1280, 1920 and 390 run in the PR.
- 18 Nov (ORCH-295, owner choice A): after Send back the ticket says "Changes asked" (in place of Ready) until the task made from the person's words is done or set aside; Undo never leaves it behind. The Comment sheet has a second button, "Add note", between Cancel and Send back: it saves the words on the ticket (queued to its helper), answers nothing, keeps the card on top and the work running; Send back stays the one that asks for changes. Shown only when the page can save notes (`api.note`).
- 18 Nov (ORCH-420, walk with ten example cards at 1280x800, 1920x1080 and 390x844): toasts sit top right while the
  answer buttons are on screen (before: the "Later" and answer toasts covered Looks good / Send it); a toast names the
  card in at most 60 characters with one end mark ("Later: Which restaurant? It stays at the end."); on a screen up
  to 900 px tall the file tiles are 112x64 so the words box keeps its room; a words box with more below ends in a soft
  edge (it scrolls) instead of a half-cut line; "All cards" puts no heading over a set of one card of its own ticket;
  the subtitle counts the cards when the needs-you number is 0 (a card put off on Home), so it never says "Nothing
  waits" above a Waiting tab with cards. `orch check done` keeps every `--file` (before: only the last).
- 18 Nov (ORCH-421, owner review of the ORCH-420 walk): what just happened ("Moved to the end: Spring sale email",
  "Looks good: PIL-8", "Back: …") is one line in the deck's top row next to its Undo for six seconds, never a floating
  box (before: the toast cut the title mid-word, took four lines and sat in the header corner); a title over 48
  characters goes by its ticket key, never cut mid-word; on a narrow deck the line takes the progress bar's place. A
  card with no picture (plain answers, a short question) is as tall as its words, so the answers sit right under two
  short options (before: about 650 px with an empty block at 1920). A result with more than 6 files shows 5 tiles and
  a "+N more files" tile that shows the rest in place (before: the 7th and later were dropped without a word; the card
  now carries up to 24).
- 18 Nov (ORCH-421 round 3, owner review): pictures hug their own shape, with the card's colour beside them, never a
  black band (single picture, Before/After, option pictures). On a narrow deck (phone) the card is as tall as all it
  holds and the page scrolls: the whole title and the whole summary are always readable (no "…", no words box that
  cuts a line); the answers and Later stay pinned at the bottom above the tab bar; files wrap into rows so "+N more"
  is in sight; the summary line is 16 px and clear of the "Make bigger" button.
- 18 Nov (ORCH-477, owner pick B "List and ticks"): the "All cards" list stands on the left at every desk width (before:
  it folded away below 1440, so at 1280 it was gone) with a tick per card and per option of a choice with pictures;
  tick two to see them side by side, each with its own answers (only the suggested answer is filled); Close or Esc goes
  back to one card. A result's files open large inside the page with ← → and "Open in new tab" in the viewer (before:
  a new tab); a PDF tile shows its first page (before: a file icon). Every card is as tall as what it holds at 1280, 1920
  and 390 (before: a fixed frame, half empty at 1920), and the answers are one bar pinned to the bottom of the screen
  with the "If you approve" line in it, so nothing hides under it. A phone opens on the first card with "All cards · 1
  of N" and ← → above it; the list with its ticks is one tap away; Compare shows one side at a time with a switch that
  names both. The draft folder of that round (draft-orch-477) is gone; its pictures are in assets/.
- 18 Nov round 2 (ORCH-477, owner sent back: "a nicer feeling, the bar left looks better, sizes and text lengths fit";
  Codex challenge in the ticket): the "All cards" list is calmer and is the kit's own (deck.drawList): no tick on every
  row (before: a box beside every card and option), a row opens its card, and one "Compare" button in its header turns
  on the ticks (at most two; Compare opens them side by side, Cancel or Close ends it). Group header = the ticket name,
  the count only when more than one waits (before: "1 of 1 waiting" everywhere), no header that repeats a lone card's
  title; rows with icon, two-line title and the deadline under it (amber within a day); the current card tinted with a
  mint left edge (before: a "Now" pill); 260 px at 1280, 300 px at 1920, it scrolls by itself under the header. The deck
  has no green frame (only real keyboard focus shows the ring) and the "All" button is gone where the list shows. A card
  reads in one 760 px column (centred with its tabs at 1920): title first, then type · deadline · ticket key (no time
  stamp), the "What was done" box on the raised surface (before: black), files in equal boxes that never crop (2
  columns, 3 at 1920, 1 on a phone). One answer bar everywhere: "If you approve" over Later (left) and the answers
  (right), only the suggested answer filled (before: Looks good always filled). The menu badge, the tab bar, the heading
  and the Waiting tab read one number. Stress cards (x1-x8): a 2-word title, a 114-character title, an unbroken web
  address, one line and 15 paragraphs, 0/1/2/12 files with a wide banner, a tall phone picture and a tiny icon, a
  choice of 2 and of 6, a question with no detail text.
- 23 Nov (ORCH-865, words by the manager for the owner after a picture challenge): a sign-in card (class login) gets
  Run it now when orch has a login check for it and tmux runs: the click opens the plain terminal in the live layer with
  the sign-in program started there (no shell), titled "Sign-in"; on a phone full screen (Leave full screen goes back).
  The card then says "Finish the sign-in on the right: press Enter and follow the steps. This card closes by itself when
  you are done." with Show sign-in under it; no Changes row, no toast. While the person cannot type there yet:
  "Turn on typing to sign in here" with a switch (only their click turns it on). Otherwise Copy only, as before.
  The review mockup shows it as the second card (r1b).
- 19 Nov (ORCH-848, owner picked draft A): a "Run it now" card (kind run, `UI.runCard` in the master): the question stays the
  title; the command sits in the copy box with Copy and Run it now on its line (filled on Review, outlined on Home and the
  ticket page); what it printed unfolds under it with "I ran it · You ran it at 14:32"; a command that is not orch's own
  asks once more in a strip with one way out (Cancel, the other answer is hidden meanwhile); a sign-in or copy-only
  command has Copy only; the phone runs only orch's own commands. The review mockup shows one run card first (Run it
  now answers after 1.2 s). The draft folder `draft-848/` stays as it was.
- 18 Nov (ORCH-425): an "Auto Reviewer" card on top of the rail with two switches that save at once: "Check finished work"
  (workflow.auto_reviewer) and "Away for the night" (workflow.away). Hidden in a read-only copy. "Accepted for you" now lists every
  decision of the Reviewer, the Auto Reviewer and Away mode with who and what ("Auto Reviewer · Accepted", "Away mode · Answered",
  "Auto Reviewer · Sent back to the helper"), the why line, and Undo while it can still be undone (then "Undone").
- 24 Nov (ORCH-1798, owner): the Auto Reviewer card shows only while one of its switches is on; both are off by default
  and are turned on in Settings > General (same rows there). Plain words for any workspace, and a last line: "Each
  verdict shows in the ticket's history, and you can undo it under What the Reviewer did on Review." The list of what always
  waits for the person stays fixed (no editable list, R4.4). The mockup shows it turned on.

- ORCH-1741: no Check card while the merge queue holds the ticket's pull request; one line "N in the merge queue, nothing to do" under All cards. One card per ticket (see home/NOTES.md).
- 24 Nov (ORCH-1835, owner picked "one card, honest name"): the rail card "Accepted for you" is now "What the Reviewer did".
  It lists accepts, send-backs and answers of the Reviewer, the Auto Reviewer and Away mode; each row still says
  Accepted, Sent back to the helper or Answered.

## Factory draft ready (18 Nov 2026, ORCH-479)

- A Factory draft that is ready for Plan the run is a card in the stack (group "Factory", kind Draft): its title, "Read
  the draft, then plan the run or ask for changes.", the link Read draft, and the buttons Ask for changes (opens the
  comment sheet; the words go to the helper as "Change the draft: …") and Plan the run. A Factory proposal card has
  the link Read proposal. Drawn on Home (`home.html?draft=1`); the product draws the card with the kit deck as is.

## Ticket beside the deck (24 Nov 2026, ORCH-1804, draft for the owner's pick)

- Every card has "Open ticket" (outline, in the card's footer; in place of a stuck card's plain "Open"). It shows the card's
  ticket in a panel on the left, in place of All cards, while the card and its answers stay on the right (`?ticket=1` in
  the mockup, `#review?ticket=<id>` in the product). The panel is the ticket page itself in one column, scrolls by itself,
  has "Open full page" and Close, and follows the card on screen. Its filled buttons read as outline: the card's answer
  stays the one filled button. A phone shows the panel in the card's place; Close or Back brings the card back.

## One plain question in one tap (24 Nov 2026, ORCH-1847)

- `review.html?one=1`: one plain, reversible question (orch's `one_tap`: two to four short answers, no card, no add-on
  kind, no spending, sending outside, starting, merging, deleting or keys) shows the question, its ticket and the named
  answers first. A tap on Thursday records the ticket answer once ("Answered Thursday: DT-70", Undo while it is held);
  no Pick one, no count, bar, "1 of 1" or All cards list for one card. Comment, None of these and Later stay; Enter on a
  focused answer answers it. Many cards keep the count, bar, "1 of N" and All cards.


## Visual polish (25 Nov 2026, ORCH-2094)

- The mockup draws the page as the product does: the rail first (`stack review-rail`: Auto Reviewer, All cards, What the
  Reviewer did), then `review-main` (tabs, deck, answered); All cards is the kit's own list (`deck.drawList`).
- The card lines up with the heading and the tabs, and has 24 px inside every edge. A rail with nothing to show (one card,
  no Auto Reviewer, nothing the Reviewer did) is hidden and the card column starts at the page edge.
- One card says "1 thing waits on you." (no "most urgent first").
- `review.html?empty=1`: nothing waits. The master empty state "You're up to date" sits in the card column with one next
  step, See answers; the heading line keeps "Nothing waits for you." so no sentence shows twice.

## Nothing to review (25 Nov 2026, ORCH-2024)

`review.html?empty=1` is the product's empty Review page: subtitle "Nothing waits for you.", the Waiting / Answered
switch with no count, and the master empty state ("Nothing waits for you" / "New cards appear here when a helper needs
you."). With nothing in the rail (no cards, no Auto Reviewer, nothing the Reviewer did) the page is one column: the
switch lines up with the heading and the empty state sits in the card's 760 px column under it (before: an empty left
column pushed both to the right). Master rule in `widgets.css`, no page CSS.
