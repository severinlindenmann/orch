# Review overhaul drafts (ORCH-2163, 25 Nov 2026)

Visual drafts for the owner's point: "the whole review needs to be challenged … filled with 100 of stuff, overwhelming,
some stuff should not even show me … some things we can zoom some we cannot, then we can zoom text and pin and comment
it, what makes no sense … a full new draft and proposal including widgets, previews, and how agents know to use which
widget". Nothing here is built. The owner answers each one on the decision page (lane `review-overhaul`); only accepted
drafts get a build ticket, and the build moves the accepted screen into `review/review.html` and deletes its draft here.

Every page is drawn with the master's classes only (`workspace/src/orch_ui/static`), no page-local style. `data.js`
holds the 43 cards that waited on the Review page of the orch workspace on 25 Nov (`orch review list --json`), each
with the lane the drafted rule gives it. Open a page from a static server rooted at the repo, or
`orch shot <file> --width 1440,390`. The pictures in the result cards are the review mockup's sample pictures.

## What the walk found (develop, the real cards)

43 cards in one list, "most urgent first" with no visible reason:

- 35 are Check cards of finished work. Each is a step list with file names and pull request numbers. 20 of them still
  had a part of "Done when" open; 3 are test walks of one release that has its own card.
- 2 are a to-do for the person dressed up as a choice (one has a 78-word title with the steps hidden in it).
- 1 is "the helper could not start: automation is paused", which the person paused.
- "Make bigger" on a text card opens a viewer with zoom − / + and "Mark a spot" on plain text (`r4-now`). A choice
  without pictures has no "Make bigger". Comment is a button on some cards and hides behind Send back on others.
- The skill gives a helper nine flags and a JSON format, and nothing says when not to make a card (`r5-now`).

## The drafts

| Problem | Now | Recommended | Other drafts |
|---|---|---|---|
| R1 What reaches the person | product picture | `r1-a` the Reviewer sorts first: 10 need you, the rest is under What the Reviewer did | `r1-b` nothing closes by itself: the Reviewer's 28 wait in a second tab for one click |
| R2 Order of the list | product picture | `r2-a` Holds up work now, then by what you do | `r2-b` Holds up work now, then oldest first · `r2-c` by piece of work |
| R3 The cards | product pictures | `r3-a` five cards named by what you do; attachments are layouts inside Look at the result | `r3-b` twelve cards in four families |
| R4 Open large, point, comment | `r4-now` | `r4-b` one Comment button, then click what you mean; only pictures open large | `r4-a` a tool per kind of content · `r4-c` one comment box, no pointing |
| R5 How a helper picks a card | `r5-now` | `r5-a` one `orch ask`: the attachments decide the card; three refusals | `r5-b` keep the flags, one table, warnings |
| R6 The result card | product picture | `r6-a` (finished) and `r6-a2` (one part open): outcome as the title, pictures first | `r6-b` a You asked for / You got table |

## The rule behind R1 (what never reaches the person)

1. Finished work goes to the Reviewer first (`orch review tend`, as today). A card is made only for what it leaves.
2. A part of "Done when" without evidence, or screen work without a picture: back to the helper once. Never Done, never
   a card. Only when the helper cannot close it does the person get the card, with the open part on top (`r6-a2`).
3. Every part has evidence and there is nothing to see or read: accepted, listed under What the Reviewer did with its
   own Undo. What the Reviewer always leaves to the person stays as it is (drafts, wording that goes out, money,
   deleting, logins, the rules files).
4. Several results of one piece of work that has its own card (a release and its walks): one card.
5. A state of the workspace (automation paused, a helper offline) is one line on Home and Review, never a card.
6. A report with nothing to decide is the ticket summary, never a card.

On the 43 cards of 25 Nov that gives: 10 things that need the person (11 cards), 11 accepted, 17 back to the helper,
3 on the release card, 1 status line. The badge in the menu and on the phone counts the 10.

## Proposed text for the orch skill and the card contract (R5, not applied)

**When to put a card on Review.** Ask yourself what you need from the person, then use one command:

| You need | You attach | Card |
|---|---|---|
| an answer | 2 to 4 `--option`, one `--suggest` | Decide |
| a pick between ways | `--option "A=name:file"` per way, `--suggest` | Decide, with pictures |
| a look at finished work | `--file` (pictures, PDF, text, an address), `--before` | Look at the result |
| a release only the person may make | `--merge <address>` | Put it live |
| the person to do something | `--steps <file, one step per line>` or `--run "<command>"` | Try it yourself |
| nothing, you only report | nothing | no card: `orch ticket summary` |

- You never name a card or a layout. orch reads what you attached: two pictures given as before and after lie side by
  side, a text file reads in full, old and new wording shows as changed lines, numbers as bars.
- The question is one sentence. Steps go in `--steps`, long text in a file.
- Finished work is never asked about: set the ticket done. The Reviewer checks it; a card is made only if it leaves
  the work to the person. Screen work needs a picture, or it comes back to you.
- orch refuses, with the next step: a card that reports a state; a question longer than one sentence; a question
  without answers or without a suggested one.
- Stuck cards are made by orch alone.

**Contract (additive, R9.4).** The card keeps `kind` and `preview`; new optional fields: `ask` (`decide`, `result`,
`live`, `try`, `stuck`) that every surface groups by, `steps` (list of strings) for Try it yourself, and `open_parts`
(list of `{asked, got}`) on a result. Old cards without `ask` map from `kind` (`choice` → decide, `check`/`draft` →
result, `link` with merge → live, `run` → try). `--draft`, `--plan`, `--link`, `--choose` and `--file card.json` keep
working and print the new form as the next step.

**Tools (R4).** One Comment on every card, in the answer bar. With Comment on, pictures take a numbered spot and
paragraphs or lines take a comment; "Whole card" is always offered. Only pictures open large. A comment that is not
sent yet makes "Send back with N comments" the filled button and Looks good an outline: a comment never goes out with
Looks good.

## What the challenge changed

Opus (as IT engineer, business manager, marketing person) and Codex (gpt-6-astra, on the pictures):

- R1: the filter is the Reviewer that exists, not a new "Handled without you" box, and not "tests passed and no
  picture" (a forgotten picture would have closed work unseen). Open parts go back to the helper. "Automation is
  paused" moved out of the handled list into a status line (it still waits for the person). One Undo per line.
- R2: every time estimate is gone (orch has no such data). "Holds up work now" is on top, Stuck with it. The counts
  add up. "Your click" became "Put it live". The phone list is drawn; result rows carry a small picture.
- R3: twelve kinds became the alternative; the recommendation is five, named as in the list. Stuck is back as the
  card orch makes itself. "Merge" is "Put it live" on the card.
- R4: the tools table left the page. One pointing mode (B) instead of three; its targets are visible. A waiting
  comment turns Send back into the filled button, so "Looks good" cannot send the 20% email with a comment on it.
- R5: no new `orch show`; everything is `orch ask`. Three hard refusals only. "No picture, so no card" is gone:
  finished work goes to the Reviewer.
- R6: the outcome is the title; the mixed green and amber chips became one line; the open part sits above the
  pictures and makes closing without it an explicit button.

## Not covered by these drafts (for the build tickets)

The native phone app's cards; an add-on's own card through `ext`; 0 and 200 cards; how the helper's reply to a
comment comes back; working through several results with the keyboard.
