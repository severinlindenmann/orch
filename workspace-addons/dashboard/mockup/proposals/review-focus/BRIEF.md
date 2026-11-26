Rules: R4.2 (new words need owner approval: list every new word in NOTES.md), R6 (one design system: master kit only,
new looks only in this folder's draft.css), AGENTS.md section 4 (plain words, non-technical users, one click, no typed
confirm words; headless browser only with launch()+newContext() and args --use-mock-keychain --password-store=basic).

# Task: "Focused review" as a real, clickable orch mockup with several teams' data (ORCH-2178)

## Where
Worktree /Users/lume/orch-wt/orch-2178-review-focus (origin/develop). Build ONLY in
`workspace-addons/dashboard/mockup/proposals/review-focus/`:
- `index.html`: short intro + links: one per team (persona) + "What changed after the challenge" (bullets).
- `focus.html`: the page. Takes `?team=data|marketing|sales|support|dev` and has a visible team switch (kit `.segmented`)
  at the top marked "Mockup: pick a team" (clearly a mockup control, not product UI).
- `data-<team>.js` (5 files) with realistic cards, `draft.css` for anything the kit does not have, `NOTES.md`
  (what it is, new words, open questions, link to the Codex challenge).
Copy the shell from `workspace-addons/dashboard/mockup/review/review.html` (head with the 8 kit stylesheets by relative
path, sidebar, topbar, `<main id="content" class="page">`, phone `.tabbar`) — fix the relative path depth for this
folder. Reuse kit widgets: `UI.swipeDeck` (one card at a time, progress, Later, 6 s Undo line), `.swipe-card` parts,
`UI.stat`/`.stat-tile`/`.stat-row`, `.chip-btn`, `.segmented`, `.banner`, `UI.toast`, `.btn primary/outline/ghost`,
`.suggested` + "Suggested" (the kit word; do NOT write "Recommended"). Read `workspace/src/orch_ui/static/DESIGN.md`,
`gallery.html`, `widgets.js` (swipeDeck options) and `review/demo-data.js` (card shape) first. If swipeDeck cannot
host the context box, render the card yourself with the same `.swipe-*` classes. Do not edit anything outside the folder.

## The owner's path so far
Five concept drafts (static, outside the repo, at /Users/lume/orch-dev/share/attention-drafts-2026-11-25/, look at
f-combined.html and its shots/). The owner's notes: A one-at-a-time lacked context ("I come back after days or 3 other
topics and don't know what I decide or why"); B's three groups liked but felt like overload; C daily game doesn't fit
projects; D compacting + easy sort liked; E later. Draft F merged these. Now he wants it challenged, aligned with what
other helpers build right now, with examples per team, as a real mockup "to test and feel".

## Align with work in flight (PRs 3201/3204, not merged yet; build on them, not next to them)
- Twelve card kinds in four families, exact names: Decide: Question, Choice. Look at the result: Before and after,
  Pictures, Document, Changed words, Numbers, Check result. Only you can press it: Put it live, Run it. Needs you in
  person: Try it yourself, Stuck. Each card shows its kind name as `.swipe-kind` (with the icon names from review.js
  CARD_ICON where possible).
- Five lanes: "Holds up work now", "Only you can press it", "Needs you in person", "Look at the result", "Checked by the
  Reviewer". Reviewer mode "propose": a line "The Reviewer proposes to accept: <why>" with that button filled.
- Result card: helper's first summary sentence as title, pictures first, "Still open" banner, Send back becomes "Send
  back with your comment" once words are typed.
- The step is called "Review" everywhere; Home tiles "Needs you / In progress / Not started / Finished today".
- DO NOT reuse "Decide" as a group name (it is a family). Attention groups (new words, mark them in NOTES.md):
  **"Quick look"**, **"Short decision"**, **"Take your time"** — these are the start tiles; the five lanes still order
  the cards INSIDE each group (Holds up work now first). Each tile: count, time estimate, a "holds up work" count.

## The design (draft F, changed by the Codex challenge — file codex-challenge-f-2026-11-25.md in the share folder)
1. Start screen: calm. Three tiles + project chips (for the team) + a one-line "Next deadline: <card> today 16:00".
   No lists. Pick a tile → a run of max 5 cards (bounded session), cards of the same project kept together.
2. Every card, in this order:
   a. The decision first: "You decide: <one line>" + "If you wait: <consequence / deadline>".
   b. The deciding fact visible, never hidden (e.g. "140 people would get access, not 12"; the exact changed words
      before → after for marketing; amount, discount, deadline, approval limit for sales; "a refund of CHF 89 was
      already sent by another helper 2 h ago" for support).
   c. "Where were we?" box, short: what the ticket is for (1 line); "You said on 19 Nov: ‘…’" with the date and a
      link-looking "open" to the source; "Since then" (max 3 lines). If the source is older than the last change, a
      small "This may be out of date" note.
   d. "Why this is in Short decision: costs money" (one line) + a small "Needs more time" link that moves it to Take
      your time.
   e. Answers: kit answer buttons, the suggestion with "Suggested"; on Take-your-time cards nothing is filled and one
      small check question comes first ("What do you expect it changed?" 3 options → reveal), as in draft B.
   f. Send back with a typed comment (kit composer or a textarea) + one-tap reasons; Later with "Remind me: this
      afternoon / tomorrow / when <ticket> is done"; Undo line for 6 s after every answer.
3. Quick look: NOT auto-pass by default. "OK all 12" only after the list is shown (one line each). Auto-pass exists
   only as a visible team rule: "Passes by itself at 09:00 because of your rule ‘tested small fixes in orch’ · Change
   rule". Show this on the orch dev team only; other teams have no rule.
4. Ideas / long helper text (from D): 3-point brief, then ideas with Keep / Later / No; partial sorting allowed
   ("Save, 2 left for later").
5. Spot-check (planted mistake): OFF by default. In the mockup show it only as a setting row in a small "How Review
   works for you" panel ("Practice cards now and then: off") — the owner decides later. No planted card in the runs.
6. Group done: what you decided (max 5 lines, each with Undo), what still waits, back to the tiles.
7. One card per team needs a second person ("Lea must also say yes: discounts over 15%") — show it as a line, not a
   workflow.

## Teams (realistic data, fictional companies/people; 10–14 cards per team spread over the 3 groups, mixed kinds)
- data: enterprise data-platform customer project (Swiss insurer "Helvia" fictional). E.g. analysts access to an email
  column (140 vs 12), warehouse spend +38% (CHF 90/week), dbt model grain change orders_daily, 2-year backfill, row
  count check passed (should NOT be a card → show as "Checked by the Reviewer"), data catalog: 6 ideas, pipeline Stuck.
- marketing: campaign launch tomorrow where "may reduce costs" became "guarantees 40% savings" (Changed words),
  newsletter subject lines Choice, 4 banner Pictures, LinkedIn post Put it live, blog draft Document, budget split
  Numbers, agent's 8 content ideas.
- sales: 22% discount before 16:00 on condition of annual prepayment (needs Lea), quote for 50 seats Document, CRM
  cleanup Run it, follow-up email drafts, pipeline forecast Numbers, lost-deal reasons ideas.
- support: refund CHF 89 + apology where another helper may already have refunded (conflict shown), macro text change,
  3 tickets escalated Stuck, FAQ page Before and after, weekly summary.
- dev: orch itself: Release 0.42 to everyone only after Friday's phone sign-in tests (show the condition as a visible
  "waits until: tests green" state), merge queue retry, empty Files page look Choice, 108 small tested fixes (auto-pass
  rule), Windows install Try it yourself.

## Check before reporting
- Click through every team at 1280, 1920 and 390 with Playwright (flags above, launch()+newContext()), screenshots
  into `review-focus/shots/` (`<team>-<width>-<step>.png`), no page errors, no sideways scroll, nothing cut off. Look
  at the pictures yourself and fix what is wrong. Serve the REPO ROOT with a throwaway local server on 127.0.0.1 port
  in 8795-8799 for your screenshots only, kill it by its PID when done.
- Report: file list, one line per team, the new words, what you could not do with the kit (what went into draft.css).

Out of scope: no product code (no changes to workspace/src or review.html/demo-data.js), no commit, no push, no PR, no
orch commands, nothing in ~/workspace-orch.
