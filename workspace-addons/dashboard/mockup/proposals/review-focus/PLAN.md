# Focused review: implementation plan (ORCH-2178)

How the "Focused review" mockup (`focus.html`, this folder) becomes product work that comes AFTER the Review overhaul
now in flight (3201 core, 3204 page, 3181 Home/wording, 3184 ticket page, 3203 chat, 3175 Focus, 3212 bar) and does
not clash with it. Nothing here is built before the owner has picked the draft and the words (drafts rule ORCH-267,
R4.2). Read on 25 Nov against origin/develop and the open diffs.

## 0. Ground rules for every slice
- Build on 3201/3204, never beside them: `card_kind {family, kind, name, lane}`, `LANES`, `lane_rank`, `proposal`,
  `UI.review.LANES/laneRank`, the 3204 `visual()` zoom rule, "Send back with your comment", "Still open".
- Do not touch `cardkinds.py` while 3201 is open; new logic goes in new core modules that import it.
- One implementation, every surface (R4.3): the core computes groups, context and reminders; the dashboard, the
  review server page and later the phone only draw what `orch review list --json` gives.
- Master kit only (R6): the looks in `draft.css` move into `widgets.css` / `components.css` with tokens, each new
  part gets a gallery entry and a test; the mockup moves from `proposals/review-focus/` into `mockup/review/` in the
  same pull request as the page change (R6.3).

## 1. Data each card needs

| On the card | Exists today (develop + 3201/3204) | Missing: where it comes from |
|---|---|---|
| Kind, lane, holds-up order | `card_kind`, `lane_rank` (3201) | nothing |
| "You decide:" | the question text (`orch ask <id> "<text>"`, max 40 words in 3201) and the card title | nothing; the question IS the decision |
| "If you wait:" | `--need` (free text, "before Friday"), `--then` (what happens after a yes) | `orch ask --if-wait "<one line>"`; fallback: `--need` |
| Deadline / "Next deadline" | `--need` is free text only | `orch ask --due <time>` (same parser as `orch wait --until`), stored as `due` (ISO); `review list` sorts by it inside a lane |
| "What matters" (the deciding fact) | preview (`compare`, `table`, `doc` with diff, options), `--because`, result headline (3204) | `orch ask --fact "<one line>"` or `--fact "Label=Value"` (up to 4 rows). Fallback: the result headline, the diff, `--because` |
| "Where were we?": what the ticket is for | ticket `description` (agent field) and `Done when` | nothing; one line, cut at 120 characters |
| "You said on <day>: '...'" + open | history lines (`by: human:*`), chat lines (`chat_message`, stable `id`), ticket text, team rules file | new `orch/cardcontext.py` (see below) |
| "Since then" (max 3) | task `--summary` lines, history after a time | `cardcontext.since()`: helper lines and task summaries after the quote, newest 3 |
| "This may be out of date" | - | `cardcontext.stale()` (see below) |
| Group + "Why this is in ..." | Away mode's reasons `autoreview._away_hits` (money, production, cannot be undone, logins or keys, outside-visible, words or names), `one_tap`, `proposal` | new `orch/attention.py` (see below) |
| "about N min" on tiles | - | fixed minutes per group in `attention.py` (Quick 0.5, Short 2, Take your time 6), no AI call |
| Check question first | - | `orch ask --first "<question>" --first-option A ... --first-right B` (only on Take your time; optional) |
| Later with a reminder | Later is kept in the page only (`deck.later`) | `orch review later <card> --until <time>` / `--when-done <ticket>`; stored on the question as `later_until` / `later_on`; `review list` hides it until then and counts it ("N put off for later") |
| Undo | held answers 6 s (`held`), `orch review undo` for the Reviewer | nothing for v1 |
| Passes by itself (team rule) | Reviewer mode accept + `reviewer_kinds` + `workflow.reviewer` | nothing new: the page shows the existing setting as the visible rule line; with no such setting nothing passes |
| Ideas Keep / Later / No | - | a list card: `orch ask --ideas "<title>" --idea "<text>" ...` stored as `preview.items`; answer per item; unsorted items stay as a smaller card (slice 5) |

**"You said" (cardcontext.said).** Order: (1) the helper names the source: `orch ask --said <ref>` where ref is a chat
message id, `history:<at>` of a person's history line, `ticket` (the ticket text when a person wrote it) or
`rules:<line>`; orch copies the words, day and source label from the record itself and refuses a ref that is not a
person's words. The helper never types the quote, so it cannot be made up. (2) Without `--said`: the newest person
words on this ticket before the question was asked (chat, then history comment, then ticket text). (3) Nothing found:
the line is left out. Quote cut at 160 characters with "...". The "open" link carries the target (chat message id,
history time, rules line) so the side panel can mark it.

**Staleness (cardcontext.stale).** True when, after the quote: the ticket's `Done when` or description changed, or
the person said something newer on this ticket, or more than 5 helper changes landed. One plain line, never a block.

**Groups (attention.group_of).** Plain rules on what orch already knows, no AI call:
- Take your time: kind `put_live`, `try_yourself`, any `_away_hits` reason (money, production, cannot be undone,
  logins or keys, outside-visible, words or names), a `document` over ~300 words, an ideas card, or the helper
  asked for it (`orch ask --take-time "<why>"`).
- Quick look: a result the Reviewer proposes to accept (`proposal.verdict == accept`), `check_result`, a `one_tap`
  question; nothing from the Take-your-time list.
- Short decision: everything else (questions, choices, run_it, stuck).
- `why` = the first rule that fired, in plain words ("costs money", "goes to everyone", "small and tested").
- Who may move a card: the helper only toward Take your time (`--take-time`); the person both ways ("Needs more
  time", and, if the owner says yes to question 3, "This is small"), stored as `attention_by: human:<name>` on the
  question and kept until the question changes; the Reviewer never moves a card. Stuck stays in Holds up work now.
- `review list --json` items gain `attention {group, why, minutes, by}`, `context {goal, said, since, stale}`,
  `if_wait`, `due`, `fact`, `first`, `later`; all additive, old readers ignore them. `orch review list --group
  quick|short|time` filters the CLI list (R4.3: the CLI shows the same groups).

## 2. UI

**Review page layout (recommendation).** No new mode and no switch: the three tiles sit at the top of the Review page,
above the five lanes that 3204 draws as "All cards". A tile starts a round of up to 5 cards of that group (lane order
inside, one project's cards together); the round ends on "What you decided" and goes back to the tiles. The lane list
stays where it is for people who like the list. With 5 cards or fewer the tiles are hidden and the deck starts as
today. Phone: tiles, then the lane list folded.

**Kit (workspace/src/orch_ui/static), extend, do not fork.** The mockup drew its own card only because the deck had no
slots. The deck already owns Undo, Later, pins, the comment sheet, the run box, the viewer and the one-tap rules, so a
second card renderer would be a second implementation (R4.3). Plan:
- `UI.swipeDeck` (widgets.js) gets optional item fields drawn by small builders in fixed order: `decide`/`ifWait`
  head, `fact` box (`.swipe-fact`), `context` (`.swipe-ctx`, with the stale line), `groupWhy` with "Needs more time",
  `first` (answers stay closed until it is answered; the fact box shows after), reminder chips in Later
  (`.swipe-later-when`), and one "More" menu row in the foot (Ask about this, Open the ticket, the helper's live view,
  Needs more time). Items without these fields draw exactly as today. Option `round: 5` + `onRoundEnd(summary)`.
- New widget `UI.attentionTiles(host, groups, o)`: three `.stat-tile` buttons (count, about N min, N hold up work),
  project chips (`.chip-btn`), one "Next deadline" line, "N put off for later / Bring them back", the visible rule line.
  Gallery entry `#w-attention`, test `attention-tiles.test.mjs`.
- `UI.review.mapCard` (review.js) maps the new list fields; `UI.reviewPage` gets `group` / `round` options.
- Pictures: keep `UI.reviewViewer` and 3204's `visual()`; add the "Slider" mode to the existing compare
  (`.swipe-compare`, `.cmp-range`) and several pins as today. Nothing new for text.
- Side panel: kit `UI.tabs`-style row on the existing `.review-ticket` aside (no new panel component). At phone width
  it is a full sheet with "Back to the card" using the overlay lifecycle (overlay.js).

**Dashboard (workspace-addons/dashboard).**
- `pages/review.js`: tiles on top, rounds, round summary, ops for Later-with-reminder and Needs more time.
- Side panel tabs: Ticket = the current `reviewTicket` body; Chat = `ticketchat.js` thread with the composer in the
  3203 `layout:'box'` (prefilled "About: <decision>" for Ask about this); Terminal = `LiveTerm` / `liveTermFor` (the
  Focus page's `UI.term` and stream, watching only; opened only while the tab shows, closed with the panel, because
  the bridge serves few pages). Files open with `FileViewer.renderMd` inside the panel.
- Run it: `runCardTerminal` opens the panel's Terminal tab when the panel exists; the Focus layer stays the fallback
  (Home, phone without panel). Failure line + "Ask the helper" reuse the run box's existing error state.
- `actions.py`: `review.later {card, until|when_done}`, `review.move {card, group}` → the two new CLI commands.

## 3. Slices (5 pull requests, in order)

1. **Core: groups, card context, Later with a reminder** (new branch). Depends on: 3201 merged. Files:
   `workspace/src/orch/attention.py` (new), `cardcontext.py` (new), `review.py` (stack fields), `cli.py` (ask flags
   `--if-wait --due --fact --said --first* --take-time`), `cli_review.py` (`later`, `move`, `--group`),
   `skills/orch/SKILL.md` (how a helper writes a good card), `docs/decisions.md`, `contracts/` note if the list JSON
   is a contract. Tests: `workspace/tests/test_attention.py`, `test_cardcontext.py`, `test_review_later.py`, extend
   `test_cli_review.py`, `test_ask_because.py`. Size L (~600 lines). Codex review of the diff (rule: >80 lines).
   Conflicts: touches `review.py`/`cli_review.py` that 3181 and 3184 also touch (a few lines each); start after 3181
   and 3184 are in, merge origin/develop before `queue add`.
2. **Review page: tiles, rounds, the new card parts** (kit + dashboard + mockup in ONE PR, the Review-page area).
   Depends on: 1, 3204 and 3181 merged (both edit `widgets.js`, `review.js`, `pages/review.js`). Files:
   `orch_ui/static/widgets.js`, `widgets.css`, `review.js`, `gallery.html/js`, `DESIGN.md`; dashboard
   `pages/review.js`, `actions.py`; `mockup/review/` (screens from this folder), `docs/wording.md` (approved words).
   Tests: `orch_ui/tests/swipe-deck.test.mjs` (slots, check-question gate, round end, More row),
   `attention-tiles.test.mjs` (new), `review.test.mjs` (mapCard fields), `review-card-long-text.test.mjs`;
   dashboard `tests/review_page.test.js`, `tests/test_act.py` (two ops); click-through `e2e/dash_review_focus.cjs`
   (new: tile → round of 5 → Needs more time → Later tomorrow → Undo → summary). Size L. Full dashboard click-through
   suite before `queue add`. If a follow-up of 3204 is still open then, add these commits there instead.
3. **Side panel: Ticket / Chat / Terminal beside the card, Run it in the panel.** Depends on: 2, 3203 and 3175 merged
   (`ticketchat.js`, `composer.js`, `liveterm.js`, `livebar.js`). Files: dashboard `pages/review.js`,
   `pages/liveterm.js` (export an open/close per host, no behaviour change in Focus), `pages/ticketchat.js` (thread
   into a host), `mockup/review/`. Tests: `tests/review_page.test.js` (tabs, phone sheet), `tests/live_sessions.test.js`
   (one stream per session, closed with the panel), `tests/chat.test.js` (prefill), click-through
   `e2e/dash_review_focus.cjs` step "Run it opens the Terminal tab". Size M. Append to slice 2's PR if it is still a
   draft (one Review-page PR); otherwise its own PR.
4. **Ideas card: Keep / Later / No, save part of it.** Depends on: 2. Files: `cli.py` (`--ideas/--idea`),
   `review.py` (answer per item, the rest stays as a smaller card), `cardkinds.py` mapping to `document` (one line,
   3201 merged by then), kit builder + test in `swipe-deck.test.mjs`, `test_review_ideas.py` (new). Size M.
5. **Phone and review server page catch up.** Depends on: 1-2. The review server page uses the same kit and gets it
   free; check `review-boot.js`. The phone app (`mobile/OrchMobile`) shows `if_wait`, fact and "You said" on its card;
   own ticket under the mobile lane, not part of the dashboard PRs. Size M.

Slice 1 and 4's core part may go together if 4 is approved at the same time; never split slice 2 into kit-only and
page-only pull requests (fewer, larger PRs).

## 4. Words to settle with the owner first (one card, `orch ask`)
1. Group names: Quick look / Short decision / Take your time (mockup), against keeping only the five lanes.
2. "Check result": 3201 names a kind "Check result", while 3181 adds it to the never-use list in `docs/wording.md`
   ("Check (for this step), Check result"). The two open PRs contradict each other; settle before 3201/3181 merge
   (proposal: the kind becomes "Test results" or "Checks").
3. "Suggested" stays (wording.md bans "Recommended"); the mockup already uses it. No change.
4. "Terminal" / "the session": wording.md bans "Session" for sign-ins; Focus uses "Terminal". For non-technical
   teams propose "What the helper does" as the tab and "Watch the helper" as the More item; "Terminal" only where
   the plain terminal setting is on.
5. "You decide:", "If you wait:", "What matters", "Where were we?", "You said on <day>:", "Since then", "This may be
   out of date", "Needs more time", "Remind me:", "Bring them back", "Next deadline:", "More".
6. "Later" (kit) vs "Remind me" (new): one word for the button (Later), the chips under it are times only.
7. "Team rules" as a source label (it is a file in the workspace): ok, or "Your rules"?
8. Round words: "What you decided", "Still waiting:", "Next N in <group>", "Back to the start".

## 5. Risks and what to cut for a first version
Risks:
- Helpers will not fill the new fields. Mitigation: every field has a fallback from what exists (`--need`,
  `--because`, headline, newest person words), the `orch ask` next-step line names the missing ones (R2.7); no refusal.
- A wrong or misleading "You said". Mitigation: orch copies the words from the record by reference, never the
  helper's paraphrase; day and source always shown; stale line.
- Wrong group. Mitigation: plain rules, the reason is always shown, the person moves it in one click; groups only order
  the work, nothing is answered by itself.
- Clashes: 3201/3204/3181 all touch `review.js`, `widgets.js`, `review.py`. Mitigation: start each slice only after
  the named PRs merged, new code in new modules, merge origin/develop before `queue add`.
- Terminal bridge serves few pages; a Review panel stream next to a Focus pane. Mitigation: one stream per session
  shared with Focus, opened only while the tab shows, watching only.
- Speed (R8.3): context per card reads the ticket history; cap at the last 200 lines and the shown cards.
- Undo after Run it cannot undo the command; the card says only the mark is taken back.

Cut from v1 (later tickets, or drop): practice (planted) cards; the second-person line ("Lea must also say yes");
"Waits until: tests green" with a kept yes (show the existing `blocked` line instead); making or editing rules from
Review (show the rule line and link to Settings); "Let me type" in the Review panel (watching only); "This is
small" (the other direction of Needs more time); mixing projects in a round; minutes from real timings (fixed table);
the ideas card (slice 4) if slices 1-3 run long.

## After the outside challenge (OpenAI credit, 25 Nov; full text in PLAN-CHALLENGE-openai-2026-11-25.md)

Taken:
- First pull request is small and goes INTO 3204 (coordinated with 3201): the card puts "You decide" + "If you wait" + the
  deciding fact first, behind a switch; old cards without the new fields stay as today; empty fields are left out, never
  filled with a guess.
- "You said on" only with an explicit, stable reference (message id or history id, kept with its version). Show who it
  is: "You wrote", "<name> wrote", "Team rule". No pointer = no quote (no "newest words" fallback).
- "Out of date" follows the version of what the decision is about (the change, the file, the target), not a count of
  helper edits. A changed result after the quote asks again instead of only warning.
- Attention groups never change what passes by itself; auto-pass stays the Reviewer setting, unchanged. Unknown risk
  goes to Short decision, never to Quick look. No "about N min" until there is real timing data.
- Measure before widening: per week, cards sent back later after an accept, undo count, missed deadlines, time to answer.
  Faster accepts alone is not success.
- Fixtures for: wrong author, withdrawn instruction, changed source, missing pointer, wrong group, snoozed deadline,
  stale answer.

Not taken (owner asked for these explicitly): the three groups and the side panel with Chat/Terminal stay in the plan,
but as later slices after the card change has run for a while.

Open for the owner: the check question before the fact (Codex and OpenAI both doubt it helps; keep it as a test on
Take-your-time cards only, or drop it).

## Owner decisions, 26 Nov
- The check question before the fact is DROPPED (all groups). The fact box is always visible.
- The card kind "Check result" is renamed "Test results" (fits the docs/wording.md ban from 3181). Goes into 3201.
- Direction approved; coordinate the first slice with the Review overhaul (ORCH-2173, PR 3204).

## Final order (replaces section 3's order after the challenge)
A. Decision-first card, appended to PR 3204 (ORCH-2173), behind a switch: "You decide" / "If you wait" / one "What
   matters" fact box / sticky answers + one "More" row; `orch ask --if-wait --fact` (optional, empty = left out).
B. "You said on" with stable references only ("You wrote" / "<name> wrote" / "Team rule"), staleness by version.
C. Attention groups and rounds of 5 (tiles over the five lanes), keys 1/2/3 J/K M U Esc, motion from the kit. Groups
   never change auto-pass. Weekly measure: undos, later send-backs, missed deadlines.
D. Side panel beside the card: Ticket / Chat / Terminal (Focus live session), Run it in the panel. After 3203 + 3175.
E. Ideas card: Keep / Later / No with partial save.
F. Phone app and review server page catch up.
