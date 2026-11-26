- Kept A review; added the summary, compact file actions, bounded preview, expanded requirement, and next-step explanation. Carried headers and file actions through the other states.
- Shared snapshot: 3 need you; Anna and Ben own tickets; Helper is the helper. Newsletter 23 min; survey 12:26; sign 12:32; typo 12:27; question 27 min.
- Motion: retain entry, progress and status transitions; honor reduced motion. Preview stays collapsed until requested.
- Performance target: no new dependencies or external network requests; interactions below 100 ms and animation frames below 16.7 ms. Loading and empty states remain available through the Preview pill.


## Revised after the owner's comment (13 Nov)

The tabs are directly below the ticket header; open Tasks to see each task’s evidence, Files to see its attached files, and Activity to see what happened.

### ticket-review.html

- Expand and every file preview now open the same file viewer with the survey title, details, Open in new tab, Download and Copy link.
- × Close, Esc and clicking outside close the viewer and return focus to the opening control.
- ORCH-1874: when the file in the project differs from the copy a step saved, the result row says "Changed since this step." with "See the current file" (the file as it is now). Shown here on the survey row as that state.
- Added counted Tasks, Files and Activity tabs; the survey note belongs to reading the answers and the summary file belongs to writing the summary.

### ticket-working.html

- Kept the compact Progress overview and added working Overview, Tasks, Files and Activity tabs below the header.
- Each task opens its own notes, files and links; the skipped photos and unfinished test mail explain why there is no evidence yet.
- The newsletter plan identifies its two related tasks and opens in the closable viewer; Files also links to the full grid.

### ticket-change.html

- Added tabs with task and activity counts while keeping the Overview.
- The price list is linked to comparing prices and updating the sheet; the shipping-cost request clearly has no result yet.
- Price-list previews use the same closable viewer and file actions.

### ticket-question.html

- Added Overview, Tasks, Files and Activity tabs below the header.
- Tasks and Files show honest zero counts and explain where future evidence will appear; Activity shows the supplier question.

### ticket-copy.html

- Added working tabs and retained the current Overview.
- The printing task opens its completion note; Files explains that no file is attached and links to the full grid.

### ticket-done.html

- Added working tabs and retained the result and compact Progress overview.
- The opening-time task opens its completion note; Files shows zero attached files rather than counting the note as a file.

### opus-ticket-review.html

- Added the same counted tabs with task evidence and file ownership labels.
- Replaced placeholder preview and download links with the actual survey file; the preview has × Close, Esc, outside-click closing and focus return.
- Kept the shared shell and Preview pill, and repaired the embedded survey preview.

Validation: browser checks passed for all seven pages in loaded, empty and loading states, with no page errors. Checked task disclosures, tabs, file opening, Close, Esc, outside-click closing and focus return. Existing motion and reduced-motion settings remain; the new viewer and evidence use brief transitions.


## Revised after the owner's comment (13 Nov)

### opus-ticket-review.html

- Made review checks, history and actions visible, renamed the Properties heading, and gave the title a full row so the actions cannot squeeze it.
- Tasks use separate title and note lines and Done, Skipped or Working labels; task evidence can still be opened.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### ticket-change.html

- Made the short notes, ticket actions and property fields visible without Details or More disclosures; separated the owner control from its label.
- Tasks use separate title and note lines and Done, Skipped or Working labels; task evidence can still be opened.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### ticket-copy.html

- Made the short notes, ticket actions and property fields visible without Details or More disclosures; separated the owner control from its label.
- Tasks use separate title and note lines and Done, Skipped or Working labels; task evidence can still be opened.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### ticket-done.html

- Made the short notes, ticket actions and property fields visible without Details or More disclosures; separated the owner control from its label.
- Tasks use separate title and note lines and Done, Skipped or Working labels; task evidence can still be opened.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### ticket-question.html

- Made the short notes, ticket actions and property fields visible without Details or More disclosures; separated the owner control from its label.
- Tasks use separate title and note lines and Done, Skipped or Working labels; task evidence can still be opened.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### ticket-review.html

- Made the short notes, ticket actions and property fields visible without Details or More disclosures; separated the owner control from its label.
- Tasks use separate title and note lines and Done, Skipped or Working labels; task evidence can still be opened.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### ticket-working.html

- Separated task titles from notes, showed the skipped-photo reason on its own line, and included the current test-mail task in the Tasks tab.
- Tasks use separate title and note lines and Done, Skipped or Working labels; task evidence can still be opened.
- Checked at 1280 × 800 in loaded, loading and empty states; kept the shared navigation, Preview pill, demo data and motion.

### assets/survey-results.html

- Checked the standalone survey result at 1280 × 800; its title, findings and answer count remain readable.
- Kept the real 112-answer survey content and the file used by ticket previews.

Validation: all 39 main pages passed loaded, loading and empty checks at 1280 × 800. Task status words, title and note spacing, owner changes and Undo, file upload and keyboard focus, and Focus headers and earlier-task lists passed browser checks.


## Revised after the owner's comment (13 Nov)

Round 2 — working shared components.

### ticket-change.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

### ticket-copy.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

### ticket-done.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

### ticket-question.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.
- Questions now share recommended choices, a checked written answer, an answered state and Undo; phone and desktop show the same reply.

### ticket-review.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

### ticket-working.html
- Connected this page to the shared dialog, menu, dropdown, switch, toast, keyboard and motion behaviour.
- Kept the shared shell, real demo content and Preview states; dialogs now close with a visible button, Escape or a backdrop click and return focus.

Round 2 validation: the shared browser sweep passed all 171 loaded/loading/empty page checks and 144 dialog/viewer checks. Targeted phone, question, keyboard, calendar, full-screen and toolbar checks also passed. See `../system/COMPONENT-QA.md` for the complete inventory and results.

## Owner feedback 14 Nov (lane owner-fb-v2)
The current ticket header is the strip in `../sweep/d-ticket-states.html` (all five states) and `../proposals/f-ticket-check.html` (Check: Looks good / Send back, Result, What the helper did). The product matches them; the older pages here keep their 13 Nov look until they are replaced.

## Working ticket header (ORCH-70, 17 Nov 2026)
Owner accepted on 16 Nov (ORCH-64 card): while a helper works the header has no box, one line above the title (ticket
number, state, helper, minutes), one Watch live, and Stop plus the two terminal commands in the ⋯ menu. No helper bar,
no Live session card, no empty Owner row; the top bar shows only "Tickets › ORCH-n". Pages: `ticket-working.html`,
the Working strip in `../sweep/d-ticket-states.html`; master: `.strip-plain`, `.strip-kicker` in widgets.css.

## Review stack (15 Nov 2026)

### ticket-answers.html

- A question the helper took back (`orch ask T --take-back q4 "why"`) stays in this list greyed: "Taken back: <reason>", no card, gone from Needs you and Review (16 Nov).
- No Decisions tab (owner 15 Nov): the card answers sit under the ticket's questions ("Earlier answers"): "What applies now" first, then one record per answer, newest first (kit `UI.appliesNow` / `UI.answerRecord`).

## Report a problem (diagnostics D3, 15 Nov)
`ticket-report.html` (`?s=page|form|busy|done|copied`): the "Report a problem" button in the top bar and its dialog (what happened, what you expected, a picture of the page, ticket text and helper conversation, Create report, Report ready with the checks, a line to paste, Ask a helper to investigate, Open folder). The button is in the top bar of every page; on a ticket page and in an add-on frame the dialog names that ticket or add-on. The form also takes "Anything else?", added pictures and files (pick, drop or paste, up to 10) and, only when the workspace is connected to a relay, the tick box "Send this report to the admin of <relay>"; Report ready then says "Sent to the admin of <relay>" (or "Not sent: <why>" with Try again; the report stays on this computer). The relay admin page that lists them (also called Report a problem) has no mockup: the relay admin portal is not part of this mockup set. The product's picture of the page is a snapshot of the page text with every typed value masked (no screenshot library).

A feature wish (ORCH-81, owner pick A, 16 Nov; `&about=feature`): the button keeps "Report a problem"; the dialog starts with a switch "A problem" / "A feature wish". For a wish the words become "What do you want?" / "Why would it help?", the page picture and ticket text rows are hidden (off), and Report ready says "Your feature wish is saved on this computer." with only Close: a wish is sorted first, never handed to a helper from here. The relay admin page marks a shared wish with a "Feature wish" chip.

- Properties: **Model** (ORCH-49). orch picks Sonnet or Opus before each start (shown as "Let orch decide (Opus)", the reason in the tooltip); a person picks Haiku, Sonnet, Opus or Fable, or hands it back. A running helper switches when its turn ends, else it applies from the next start. Haiku (fastest) and Fable (drafts) are only ever a person's choice (owner 17 Nov, ORCH-257); a ticket on Fable ends with one card of three or more drafts side by side. Shown in `ticket-working.html`.
- A question with a card (16 Nov, ORCH-65; `ticket-question.html#card-question`): the question text and the card's pictures together (Today first on a choice, the suggested option marked), "Look and answer" opens Review at that card; the top line names the agent that asked ("Manager asks: …", the agent's own name), "Helper" only when none is known.

## Released or only merged (ORCH-87, 17 Nov)

### ticket-done.html

- A finished ticket with a merged pull request shows one line at the top: "In release 30 (installed here)" (green ✓),
  "In release 31, not installed here yet" (amber !) or "Merged, not released yet" (grey –). orch works it out from the
  merge commit and the installed release; no line when it cannot tell.

## ORCH-185: what you asked, due day, activity (17 Nov)

- What you asked: pictures and files the person attached when making the ticket are listed there (with a thumbnail), not under Result. A one-sentence wish stays in the note.
- Due shows the day ("Fri 20 Nov", the year only when it is not this year), never a bare "Fri".
- Activity: a note edit keeps its own row with "Was: … → Now: …" (at most 200 characters each).
- Picture viewer (kit): a picture gets the tall window and a smaller header at 700 px and wider, so a 640 × 480 picture is shown whole.
- `ticket-working.html` shows the attached picture (thumbnail, "attached by you") under What you asked and an Activity row with Was/Now. The picture viewer says "Attached by you" for such a file.

## Add to this ticket (ORCH-238, 17 Nov)
`ticket-working.html` shows the card at the top of the story: the helper's live screen (kit `.session-dock.in-card`,
read only) above the shared composer (`kit/composer.js`). A person writes what is new, pastes screenshots or adds
files; one click puts the files on the ticket and tells the helper (starts one when none runs; Send back in Review).
It is the ticket page's own box, separate from Focus (owner answer on ORCH-238).
## ORCH-240 (17 Nov, owner's words)

- The tab and card are "Tasks"; sub-tickets of a plain ticket are headed "Sub-tickets"; epic sub-tickets show
  their ticket number.
- Overview lists files by their real name with extension, newest first like the Files tab.
- Activity names the task (never "c1") and shows "Was: … → Now: …" for title, owner, due and task renames.
- Owner box suggests the workspace's people and warns on a new name; a past due day shows a hint;
  "Due Mon 16 Nov, 18:30" within a week.

## ORCH-235 (17 Nov): one word per ticket state

### ticket-waiting.html

- A ticket that waits for a date or the outside says Waiting (never Needs you), with its date and what it waits for:
  "Waits until Mon 09:00 · The price list from the supplier". Needs you stays for a helper's open question.
- The product's ⋯ menu offers every board lane except Needs you (Backlog, To do, Working, Waiting, Check, Done,
  Won't do, Superseded); Waiting asks for the date and, optionally, what it waits for.
- Check after a move by a person reads "Moved to Check by Anna 14:23", never "Helper finished".
- An epic whose sub-tickets are all done says so and offers Mark Done; Done with open sub-tickets asks first
  ("Mark Done anyway" or Cancel).

## Prepare on a saved ticket (ORCH-742, look B picked by the owner 19 Nov)

Saved from the real ticket page (draft ORCH-730 section 6, draft folder draft-742 removed):

- `ticket-preparing.html`: the sentence under the title says "Preparing: reading the links and filling in the ticket."
  with a small spinner; Start stays, no live Working header.
- `ticket-prepared.html`: "☰ Prepared today 09:41. Press Start to begin." (hover: described by the helper, not checked).
  Under What was asked, What I found is one line ("2 sources read", "! 1 could not be opened"); a click opens the key
  facts and the sources with Open ↗. The sources it could not open stay in sight in the same box, each with Attach it
  (moves to Add to this ticket).
- `ticket-not-prepared.html`: "Not prepared yet. Start still works." In line: "In line to be prepared. Start still works."
- Phone (no static mockup; Simulator `-relayMode mock -seedPaired YES -mockPrepare YES -openChat ws_pilatus001
  -openTicket t_prepspring` or `t_prepsurvey`): Preparing / ☰ Prepared under the title, a What I found row above the
  steps row that opens a sheet with the facts, the sources and Could not open.

## Role page (ORCH-827)
`ticket-role.html`: a ticket that runs by itself, as the owner picked draft A2 on ORCH-812. Header chip "Runs by
itself", Run now and Pause (Turn on while paused); tabs Overview · Runs · Schedule · Chat · Files. States by the
preview controls (`?state=running|question|paused`), tabs by `?tab=role-runs|role-schedule|role-chat|role-files`.
About this role shows the same totals as the Automation page block "What the roles found": runs, findings, their
tickets fixed / open / dropped, files nobody opened (unknown where nothing was measured). The look is in the master
(`widgets.css`, "Role page"). Demo data is invented.

## ORCH-415: one status, one ask heading, starts never filled (18 Nov)

- `ticket-idle.html` (new): a ticket In progress with no helper. The pill says **In progress** (Working is said only
  while a helper runs), the line under the title says "No helper is working on it right now.", as the Add to this
  ticket box below does.
- ORCH-1850: right under the header, the handover row answers "where did it stop": **Last marked step · <task>**, then
  who marked it and when, and what the run record says ("Claude last worked 1 h ago", "The last run ended without
  finishing", or "No helper run on record"; the helper is named only from a real run or session). One click, See in
  Activity, opens the event. The marked task reads **In progress** (◐), never Working: Working is said only while a
  helper runs. The task done last keeps its evidence line, and Progress comes before Results while the ticket is open.
- The start is outlined, never filled (UX D2): its cost in one line above it ("On Opus · estimate about $1.20, $0.40
  used so far") and, on a strong model, the same start on Sonnet beside it (kit `.cost-pick`). Every page's
  Start helper is outlined too.
- `ticket-working.html`: one **What was asked** section holds the description, the person's note and the files they
  added (it was "What was asked" plus "What you asked").
- Changes to add, empty copy (ORCH-1809): a copy that brings 0 commits and 0 files shows one quiet `.meta` line
  ("The copy has no changes to add. Nothing to apply.") instead of the card, with no Apply changes; Home says "No
  changes to apply" and links to the ticket.
- Header in every state (ORCH-2089): the product now draws the unboxed strip of `ticket-idle.html` /
  `ticket-working.html` when no helper runs too: one line "KEY · kind · status pill" above the 28 px title (24 px on a
  phone), the sentence and facts below. A Done ticket whose only result is its completion note shows "Results · 1 note"
  without the "Nothing yet" line, as `ticket-done.html` draws it. No mockup change was needed.

## ORCH-2051: Replaced by, type a key to jump (25 Nov)

- `ticket-idle.html`: More ticket actions › Move to Superseded opens the product's "Which ticket replaces it?" dialog
  (Replaced by, Cancel, Move to Superseded). The dialog opens with focus on the choice. Typing a whole key (ORCH-97)
  jumps to that ticket; typing never chooses, Enter or a click does. The long title and the long word wrap in full.
