# UX/UI checklist for every orch UI change

Run this on every UI change (page, component, state, words on screen, motion, mockup, visual fix) and on every review
of one. Answer each line **yes / no / n.a.**; a "no" is fixed or explained in the PR body. `[auto]` = a script or test
can check it cheaply; `[eye]` = a person or agent must look at the screenshots. Sources and strength of each rule:
`RESEARCH.md`. The master design system (`workspace/src/orch_ui/static/DESIGN.md`) and `AGENTS.md` R1-R9 win over
anything here; this list extends them.

## A. Master design system (6)
- A1 [auto] No new `.css` file, `<style>` block, inline colour or hex/rgb literal outside the master (`brand/tests/test_style_lint.py` green).
- A2 [auto] Every colour, space, radius, shadow, duration and easing is a `var(--token)`; spacing only 4/8/12/16/24/32/40/48/64 px; radius 8 controls, 10 cards, 12 dialogs.
- A3 [eye] Every control is a master component (button, select + chevron, pill + status icon, empty/error state, toast, dialog, sheet, table, tabs); a missing one was added to the master with a gallery entry per state and `test_orch_ui_kit.py` is green.
- A4 [eye] Type only on the SX-2 scale (28/36, 20/28, 16/24, 14/20, 13/18, 12/16; mono 13/20 only in previews/terminal, so no mono tab counts, no 20 px question text) and layout on SX-1/SX-4 edges, judged on a shot taken at exactly 1280 px (column x=256-1240, max 1200 centred at 1920, page starts 32 px below the top bar).
- A5 [eye] The PR diff touches the matching mockup page, and the mockup matches the product: same title, nav label, button words, block order.
- A6 [eye] Polish: one left and one right edge per column; every status pill carries its status icon (SX-9); avatars show initial plus name, never a lone initial; truncation uses an ellipsis; nothing touches, overlaps or is clipped.

## B. Hierarchy and density (5)
- B1 [eye] In 5 seconds the view answers: what is happening, why it matters, what can I do (level 1).
- B2 [auto] Exactly one filled (primary) button is visible per view, counting the top bar; top-bar "New ticket" is always outlined (SX-4).
- B3 [eye] Level 1 shows at most 7 facts per card or header and at most 5 KPIs; the rest is shown plainly lower down, with no "Details" / "Technical details" / "Show more" toggle.
- B4 [eye] Long text never fills level 1: a question, goal or helper plan shows at most 3 lines at 1280 (first sentence plus the facts needed to decide), the full text sits lower down or on the ticket; prose lines at most 76ch.
- B5 [eye] No repeats: one status phrase per unit; the same sentence is not shown in both the header and the body; a count shown in several places (sidebar, top bar, headline, group) is the same number.

## C. Navigation and wayfinding (3)
- C1 [eye] "Where am I" is clear: active nav item marked (`aria-current="page"`), top-bar crumb `Area › item`, page title = nav label.
- C2 [auto] Every view, tab, filter and opened item has its own URL; Back restores the previous view with scroll and selection.
- C3 [eye] No dead end: every state (empty, error, done, offline) shows the next step as one button or link.

## D. Actions (5)
- D1 [eye] Button labels are verbs that name the outcome ("Start helper", "Send back", "Download file"); no OK, Submit, Yes/No, Got it.
- D2 [eye] A costly action (starts a helper, spends money, reaches people outside) is never the easiest click: its time/cost is shown right above it; it is not filled, not autofocused, not the Enter default and never alone; a cheaper choice (Not now, Edit) sits beside it at equal or greater weight; no typed word.
- D3 [eye] Destructive actions use the Danger style, sit apart from the safe action, and prefer Undo (toast, 5 s) over a confirm dialog; a confirm only when undo is impossible, and it names the object and the result.
- D4 [eye] Dialog footer order is `[tertiary] … [Cancel] [Primary]` (SX-13); the safe action has autofocus.
- D5 [eye] A disabled control says why and how to enable it, right next to it (SX-8); prefer an enabled control that explains on click.

## E. States (6)
- E1 [eye] Loading: a skeleton shaped like the final layout appears within 100 ms where the load may take over 1 s; cached content shows at once; no whole-page spinner; never text plus bars together.
- E2 [eye] Empty: the master empty state (at most 240 px tall, one sentence "what will appear and when", one secondary button), shown only after loading finished, never twice on a page.
- E3 [eye] Error: what happened in plain words, what to do next, one button that does it (Retry, Reconnect); stays next to its source; no codes or stack traces in level 1.
- E4 [eye] Partial, stale, offline: what loaded stays visible, what is missing is said once, "Updated … ago" is shown; a refresh never blanks the page, jumps the scroll or shimmers over existing results.
- E5 [eye] Zero, one, many and long were each looked at: plurals right ("1 ticket", "2 tickets"), 0 / 1 / 50+ items, a 200-character title and an unbroken long word wrap or truncate with an ellipsis and never overlap.
- E6 [eye] Missing permission or add-on (phone not paired, add-on off, not set up): the control is hidden, or disabled with the reason; never a control that fails after the click.

## F. Feedback and system status (4)
- F1 [eye] Every click or key gives a visible response within 0.1 s (pressed state, optimistic change).
- F2 [eye] Work of 1-10 s shows an inline spinner with a label inside the same button width ("Saving…"); over 10 s shows the current step, elapsed time and Leave running / Cancel.
- F3 [eye] Success = one toast bottom right, 5 s, names the object, Undo or Open; error toasts stay until closed; the timer pauses on hover/focus; settings save in place with rollback on failure.
- F4 [auto] Live updates are announced politely (`role="status"` / `aria-live="polite"`, meaningful changes only) and never steal scroll ("N new" instead).

## G. Forms and input (3)
- G1 [auto] Every input has a visible label that stays (placeholder never replaces it), linked by `for`/`aria-labelledby`; `autocomplete` and `type`/`inputmode` set where the field has a known purpose.
- G2 [eye] One click before typing: a sensible default is pre-chosen and options are offered as buttons/choices; free text is only the optional extra.
- G3 [eye] Validation runs when the person tries to continue (not on blur, not while typing); each error sits next to its field, says how to fix it, keeps the input, and with 2+ errors a summary at the top links to them and gets focus.

## H. Accessibility (10)
- H1 [auto] Text contrast at least 4.5:1; large text (at least 24 px, or 18.66 px bold) at least 3:1; checked in every theme the page supports.
- H2 [auto] Non-text contrast at least 3:1 for input borders, focus ring, toggles, selected states and icons that carry meaning.
- H3 [auto] Everything works by keyboard alone in visual order; no keyboard trap; Escape closes overlays and focus returns to the opener; hover-only actions also appear on focus.
- H4 [eye] Focus is visible on every control (master ring: 2 px with offset) and is never hidden under the sticky top bar, a toast or a sheet.
- H5 [auto] Every pointer target is at least 24x24 CSS px (or has 24 px clear spacing); on touch screens at least 44x44 px (master `--touch`).
- H6 [auto] Every control has a role, state and accessible name that contains its visible label (icon buttons get `aria-label`); axe-core reports 0 serious or critical issues.
- H7 [auto] One `h1`, headings in order, landmarks (`header`, `nav`, `main`), skip link, a unique `<title>` per page.
- H8 [eye] Colour is never the only signal: every status has an icon and a word, every error has text, links are recognisable without colour.
- H9 [auto] At 320 CSS px wide (= 1280 at 400% zoom) and at 200% text size nothing is lost and the page has no horizontal scroll (tables and the board track may scroll inside themselves).
- H10 [auto] With `prefers-reduced-motion: reduce` every transition, pulse, shimmer and transform is off and every state change still shows.

## I. Responsive and touch (3)
- I1 [auto] No page-level horizontal scroll and nothing clipped at 1920, 1280, 390 and 320 px; the top bar wraps or folds into a menu.
- I2 [eye] At 1280x800 the main content and the main action are visible without scrolling; at 1920 lines and cards are not stretched (reading width capped).
- I3 [eye] At 390 px: navigation is reachable, the main action is in thumb reach, nothing depends on hover, text is never below 12 px, safe areas are respected.

## J. Motion (4)
- J1 [auto] Durations and easings come from tokens only (100 hover, 150 open, 200 dialog/page, 240 panel, 120 exit); UI transitions at most 240 ms.
- J2 [eye] Every animation has a job (shows where something came from or went); enter eases out, exit eases in and is shorter; one focal animation at a time; no motion at idle.
- J3 [auto] Only `transform` and `opacity` animate; nothing shifts layout (CLS at most 0.1); images and previews reserve their size.
- J4 [auto] Nothing flashes more than 3 times per second; nothing moves for more than 5 s without a way to pause it.

## K. Performance as UX (2)
- K1 [auto] At the 75th percentile LCP at most 2.5 s, INP at most 200 ms, CLS at most 0.1; dashboard first paint under 1 s (R8.3).
- K2 [eye] Perceived speed: warm routes keep showing old content while new data loads; prefetch or skeleton instead of a spinner over 1 s.

## L. Words on screen (6)
- L1 [auto] `brand/tests/test_wording.py` and `test_banned_words.py` are green (the never-use words of `docs/wording.md`: Proof, Bot, Recommended, the VPN product name, Schedule, Request, Issue alone …).
- L2 [eye] The AI is "Helper" (or its tool label, e.g. Claude), proof is "Evidence"; none of the SX-18 level-1 bans the test does not catch ("agent", "autopilot", "relay", "copy", "Exact text", "Reference"); any new noun the person must learn has the owner's OK (R4.2).
- L3 [eye] Plain and short: sentence case, sentences at most 25 words; on level 1 no IDs, branch names, codes, raw stored values (a lowercase state like "proposed") or dev jargon (merge, CI, user units); no tooltip needed to understand a label.
- L4 [eye] Error and empty texts say what happened and what to do in one sentence, never blame the person, never just "invalid" or "failed".
- L5 [auto] Dates and times only through `UI.stamp` / `UI.clock` (24 h, "today 10:32", "14 Nov 2026, 10:32"); no `toLocaleString`.
- L6 [eye] One word per thing across page, toast, phone and CLI (Ticket, Task, Needs you, Check / Looks good · Send back, Pause automation).

## M. Helper trust and safety (4)
- M1 [eye] Before a helper starts, the decision shows in at most 3 short lines: what it will do (one sentence), estimated helper time and the person's time, any cost; the plan and "won't do" list sit lower down.
- M2 [eye] Before "Looks good" the evidence for each task is on the same screen, not one click away.
- M3 [eye] What the helper did and why reads as a plain timeline (who, what, when; newest first), with the helper's own words kept as written.
- M4 [eye] At the point of decision and on the helper's ticket, the way to stop or undo is visible (Not now, Stop, Undo, Pause automation).

Total: 61 items.

## How to check

1. Screenshots (`~/orch-dev/scripts/shot.sh <url> <out.png> <width> <height>` or any headless Chromium with a temporary profile), at exactly 1280x800, 1920x1080 and
   390x844, plus 320 for reflow (a 1400 px shot cannot answer A4, B4 or I2). Dark, and light where the page supports
   it (today the master tokens are dark only, so light is n.a. until light tokens exist). One set per state the
   change touches: loaded, loading, empty, error, partial or stale, long content (seed a 200-character title and a
   long helper plan). Add one shot with keyboard focus on the main action (H4) and a before/after pair around the
   main click (F1-F3, D3); static shots alone cannot answer groups E-F. Save before and after side by side under the
   lane's `shots/<topic>/`.
2. [auto] items: `node workspace/src/orch_ui/tests/ux_checks.cjs` and `brand/tests/test_contrast.py` (both in CI, see
   `DESIGN.md` "UX/UI checklist" for exactly what they cover), style lint, wording tests, `test_orch_ui_kit.py`,
   axe-core (as in `e2e/full/web/stepper.mjs`),
   Lighthouse or a DevTools trace for K1/J3, a keyboard Tab run, an emulated `prefers-reduced-motion` run, and a
   `scrollWidth <= innerWidth` check at each width.
3. [eye] items: look at every screenshot against groups A-M; write the "no" lines.
4. PR body: `UX checklist: 61 items, N n.a., all others yes` or the list of "no" items with the reason; `Screenshots:`
   paths or links (before/after, three widths, themes, states); `Mockup: updated <where>`; `Master: <component or
   token change, or none>`; rules touched (R6, R7). A visual or flow change also goes to the owner as a review card with
   before/after pictures.
