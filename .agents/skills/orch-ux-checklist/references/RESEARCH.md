# UX/UI research for the orch dashboard (16 Nov 2026)

Research behind `CHECKLIST.md`. Every rule lists its source and how strong it is:

- **standard (normative)**: a WCAG 2.2 success criterion. Level A and AA are the target. AAA is noted but not required.
- **widely accepted**: NN/g, web.dev, Apple HIG, Material, GOV.UK, MDN.
- **judgement**: our own reasoning, or a figure we could not trace to a page we read.

Some figures were not read on the primary page during this pass, because the page rendered with script or the fetch was cut short. Those are marked *(not re-read)*. The checklist uses only verified numbers, plus the owner's own numbers from DESIGN.md.

Owner and product rules always win: DESIGN.md (SX-1..20 and the token, motion and copy contracts), `docs/wording.md` and AGENTS.md R1-R9. Where general practice conflicts with them, this file says so in one line marked **Owner rule wins**.

## Sources

| Short name | URL |
|---|---|
| WCAG 2.2 | https://www.w3.org/TR/WCAG22/ |
| WCAG 1.4.3 Understanding | https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html |
| WCAG 1.4.11 Understanding | https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html |
| WCAG 2.5.8 Understanding | https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html |
| WCAG C39 | https://www.w3.org/WAI/WCAG22/Techniques/css/C39 |
| WAI-ARIA APG | https://www.w3.org/WAI/ARIA/apg/ |
| NN/g response times | https://www.nngroup.com/articles/response-times-3-important-limits/ |
| NN/g skeleton screens | https://www.nngroup.com/articles/skeleton-screens/ |
| NN/g 10 heuristics | https://www.nngroup.com/articles/ten-usability-heuristics/ |
| NN/g confirmation dialogs | https://www.nngroup.com/articles/confirmation-dialog/ |
| NN/g empty states | https://www.nngroup.com/articles/empty-state-interface-design/ |
| NN/g error messages | https://www.nngroup.com/articles/error-message-guidelines/ |
| NN/g OK/Cancel order | https://www.nngroup.com/articles/ok-cancel-or-cancel-ok/ |
| web.dev Web Vitals | https://web.dev/articles/vitals |
| web.dev thresholds | https://web.dev/articles/defining-core-web-vitals-thresholds |
| web.dev animations | https://web.dev/articles/animations-guide |
| MDN reduced motion | https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-reduced-motion |
| Material 1 duration | https://m1.material.io/motion/duration-easing.html |
| Material 3 motion tokens | https://github.com/material-components/material-components-android/blob/master/docs/theming/Motion.md |
| Material 2 accessibility | https://m2.material.io/design/usability/accessibility.html |
| Apple HIG accessibility | https://developer.apple.com/design/human-interface-guidelines/accessibility |
| GOV.UK error message | https://design-system.service.gov.uk/components/error-message/ |
| GOV.UK validation | https://design-system.service.gov.uk/patterns/validation/ |
| GOV.UK button | https://design-system.service.gov.uk/components/button/ |
| GOV.UK text input | https://design-system.service.gov.uk/components/text-input/ |
| Baymard line length | https://baymard.com/blog/line-length-readability |
| MS Human-AI guidelines | https://www.microsoft.com/en-us/research/publication/guidelines-for-human-ai-interaction/ |
| Google PAIR guidebook | https://pair.withgoogle.com/guidebook-v2/chapters |

## 1. Information hierarchy and density

- **One obvious next action per screen.** *Judgement*, also owner rule R7.2 and SX-4/SX-5 (one filled primary button per page, the top bar included). It rests on NN/g heuristic 8, "Aesthetic and minimalist design": every extra unit of information competes with the relevant ones (NN/g 10 heuristics). *Widely accepted.*
- **Two levels only.** Level 1 answers "what is happening, why it matters, what I can do". At most 7 facts per card or header and 5 KPIs (DESIGN.md, information density). These caps are an owner/product number, not an external one.
- **Progressive disclosure.** Generally practice hides secondary detail behind a disclosure. *Widely accepted.* We could not re-read NN/g's progressive disclosure article in this pass.
  - **Owner rule wins:** no "Details" / "Technical details" toggles. Detail is shown plainly lower down on the same page.
  - DESIGN.md SX-11 and the old orch-mockup text still mention "Details". The owner rule of 14 Nov overrides them.
- **Scannability.** Lead with the point. Keep prose lines to 50-75 characters (Baymard, *widely accepted*) and never more than 80 (WCAG 1.4.8, AAA). The product cap is `--reading-width: 76ch`.
- **Long free text never fills level 1.** *Judgement.* It follows from heuristic 8 and the trial: a 40-line goal made the Home question card unreadable.

## 2. Navigation and wayfinding

- **Page titled:** each page has a descriptive `<title>`. WCAG 2.4.2 (A). *Standard.*
- **Headings and labels describe their topic or purpose.** WCAG 2.4.6 (AA). *Standard.* Information and relationships (headings, landmarks) are in the markup, WCAG 1.3.1 (A). *Standard (not re-read).*
- **Consistent navigation and identification across pages.** WCAG 3.2.3 and 3.2.4 (AA). *Standard (not re-read).* Help shows up in the same place on every page: 3.2.6 Consistent Help (A, new in 2.2). *Standard.*
- **"Where am I".** Mark the current item (`aria-current="page"`) and show the breadcrumb for nested pages only. This is NN/g heuristic 1, "Visibility of system status", and heuristic 6, "Recognition rather than recall". *Widely accepted.* Product rule: SX-4.
- **User control and freedom.** Give a clear exit and undo (NN/g heuristic 3). Back works, and the view, filter and selection live in the URL with scroll restored. *Widely accepted*, and also DESIGN.md "Loading, errors and performance".
- **Search and keyboard routes.** Cmd/Ctrl+K and similar are product contracts (DESIGN.md). Flexibility and efficiency of use is NN/g heuristic 7. *Widely accepted.*

## 3. Actions

- **Labels name the outcome.** Use "Delete file" / "Keep file", not Yes/No or OK (NN/g confirmation dialogs). GOV.UK button text is sentence case and describes the action. *Widely accepted.*
- **Button order.** There is no universal right order. Windows puts OK first and Apple puts it last; the rule is to be consistent with your platform (NN/g OK/Cancel). *Widely accepted.* The product fixes `[tertiary] … [Cancel] [Primary]` (SX-13), and we keep it.
- **The default or highlighted action is the common one, never the dangerous one.** Dangerous actions need an explicit choice, not the Enter key (NN/g OK/Cancel). *Widely accepted.*
  - Owner extension: a costly action, such as starting a helper, is never the easiest click (R2.4, R7.3).
- **Confirmation vs undo.** Prefer undo. Confirmations get clicked through when overused. When you do confirm, name the item and the consequence (NN/g confirmation dialogs). *Widely accepted.*
  - NN/g allows typed-word friction for rare, severe actions. **Owner rule wins:** never a typed confirm word (R7.3). Show what will happen instead.
- **Disabled buttons.** GOV.UK says to avoid them where possible, because of poor contrast and confusion (GOV.UK button). *Widely accepted.* Product SX-8: a disabled toggle states its reason in the row description.

## 4. States

- **Empty states** (NN/g empty states, *widely accepted*):
  - say what the system status is
  - give a learning cue
  - offer a direct path to the key task

  Product SX-10: at most 240 px tall, one sentence, one secondary button, and shown only after loading has finished (SX-16).
- **Loading** (NN/g skeleton screens, *widely accepted*):
  - Under 1 s, show no indicator.
  - For a single module taking 2-10 s, show a spinner.
  - When a whole screen loads, show a skeleton.
  - Over 10 s, show a progress bar with a time estimate.
  - Don't use skeletons for uploads or downloads, and don't show a skeleton of only the header and footer.

  Product SX-16 and DESIGN.md add: a skeleton shaped like the final layout within 100 ms when a route is expected to take more than 1 s, cached content shown directly, and never text and bars together. The product's 100 ms skeleton rule and NN/g's "nothing under 1 s" rule are reconciled by expected latency in DESIGN.md.
- **Error states** (NN/g error messages, *widely accepted*):
  - Show the error near its source, with redundant indicators.
  - Use human-readable words, a precise cause and constructive advice, and no blame.
  - Keep the person's input.

  Product SX-11 and R8.4: say the next step in one sentence and give one button that does it.
- **Partial, stale or offline.** Keep the old data and refresh in place, quietly updating "Updated … ago" (DESIGN.md step 6). *Judgement and product rule.*
- **Zero, one, many, long, missing permission.** *Judgement.* These are the edge cases most often missed in screenshot reviews, and the trial confirmed long content. Product rules cover parts of this: SX-10 (empty), SX-8 (disabled with reason), and the 6-file toolbar threshold.

## 5. Feedback and system status

- **Response-time limits** (NN/g response times, *widely accepted*):
  - 0.1 s feels instant.
  - 1 s keeps the flow of thought. Beyond it, show that the system is working.
  - 10 s is the limit of attention. Beyond it, show percent-done progress, or absolute progress if the total is unknown. A spinner is the last resort.
- **Status messages are announced** without moving focus (WCAG 4.1.3, AA). *Standard (not re-read).* Use `role="status"` or `aria-live="polite"`, and announce meaningful stage changes, not every tick (DESIGN.md progress).
- **Moving or auto-updating content** that starts automatically and lasts more than 5 s must be pausable, stoppable or hideable (WCAG 2.2.2, A). *Standard.*
- **Toasts vs inline.** *Product contract (SX-12), judgement-based.*
  - Toasts are for confirmations and system events: 5 s, one at a time, Undo or Open, with the timer paused on hover or focus.
  - Errors persist and also stay by their source.
  - Blocking states get one page notice.
  - We found no NN/g toast article in this pass.
- **Optimistic updates.** Small writes apply immediately and roll back on failure (DESIGN.md). *Judgement and product rule.*

## 6. Forms and input

- **Labels or instructions** for every input (WCAG 3.3.2, A, *standard (not re-read)*). Labels sit above the input, short and in sentence case. A placeholder is never the label (GOV.UK text input, *widely accepted*).
- **Identify input purpose** with `autocomplete` (WCAG 1.3.5, AA). *Standard.*
- **Validation timing.** Don't validate on blur; wait until the person tries to continue. Show an error summary at the top, move focus to it, and put "Error:" before the page title. Use the same message in the summary and next to the field (GOV.UK validation). *Widely accepted.*
- **Error identification and suggestion:** WCAG 3.3.1 (A) and 3.3.3 (AA). *Standard (not re-read).*
- **Error wording** (GOV.UK error message, *widely accepted*):
  - say what happened and how to fix it
  - no "please", "sorry", "valid" or "invalid"
  - no "you forgot"
  - don't clear the input
- **Redundant entry:** don't ask again for information already given in the same process (WCAG 3.3.7, A, new in 2.2). *Standard.*
- **Accessible authentication:** no cognitive test to sign in, so paste and password managers must work (WCAG 3.3.8, AA, new). *Standard.*
- **Owner rule wins:** one click, no typed words. Offer choices with a pre-chosen default (the "Suggested" option). Free text is only ever the optional extra.

## 7. Accessibility (WCAG 2.2 AA unless noted)

| Rule | Threshold | SC, level | Strength |
|---|---|---|---|
| Text contrast | 4.5:1; large text 3:1. Large = 18 pt (24 px) or 14 pt bold (18.66 px) | 1.4.3 AA | standard |
| Non-text contrast | 3:1 against adjacent colours for UI parts, states, meaningful graphics and focus indicators. Not rounded: 2.999:1 fails | 1.4.11 AA | standard |
| Use of colour | colour is never the only means of conveying information | 1.4.1 A | standard |
| Keyboard | everything works by keyboard; no keyboard trap | 2.1.1 A, 2.1.2 A | standard |
| Focus order | order preserves meaning | 2.4.3 A | standard (not re-read) |
| Focus visible | the indicator is visible | 2.4.7 AA | standard |
| Focus not obscured | a focused item is not entirely hidden by author content, such as a sticky bar or toast | 2.4.11 AA, new | standard |
| Focus appearance | at least a 2 px perimeter, with a 3:1 change | 2.4.13 AAA | standard, not required |
| Target size | 24x24 CSS px, or 24 px spacing. Exceptions: spacing, equivalent, inline, user agent, essential | 2.5.8 AA, new | standard |
| Target size (enhanced) | 44x44 CSS px | 2.5.5 AAA | standard, not required |
| Touch targets | 44x44 pt (Apple), about 48x48 dp with about 8 dp spacing (Material) | platform guidance | widely accepted (not re-read) |
| Dragging | every drag has a single-pointer alternative | 2.5.7 AA, new | standard |
| Name, role, value | controls expose their name, role and state | 4.1.2 A | standard (not re-read) |
| Label in name | the accessible name contains the visible label | 2.5.3 A | standard |
| Reflow | 320 CSS px wide (= 1280 at 400%) with no 2-D scrolling; 256 px tall for horizontal content | 1.4.10 AA | standard |
| Resize text | 200% with nothing lost | 1.4.4 AA | standard (not re-read) |
| Text spacing | survives line height 1.5, paragraph spacing 2x, letter spacing 0.12, word spacing 0.16 (times the font size) | 1.4.12 AA | standard |
| Flashes | no more than 3 per second | 2.3.1 A | standard |
| Animation from interactions | motion can be turned off; `prefers-reduced-motion` is technique C39 | 2.3.3 AAA | standard, not required |

Patterns for tabs, dialogs, menus and comboboxes follow WAI-ARIA APG (*widely accepted*). The master already ships native `dialog`, roving tabs and keyboard support for selects; reuse those, never re-make them.

The master's 2 px ring with offset (`--focus-ring`), `--touch: 44px` on touch screens, its contrast table (7.42:1 focus, 3.46:1 input border) and the forced-colours rules already meet these.

**Reduced motion goes further than WCAG AA:** the product turns off all motion under `prefers-reduced-motion` (motion.css), not only interaction-triggered animation. Keep that.

## 8. Responsive and touch

- **No page-level horizontal scroll** at 320 px (WCAG 1.4.10). Local scrolling is allowed for tables and the board track, the 2-D content exception. *Standard.* Product: DESIGN.md layout table.
- **Desktop first:** 1280x800 and 1920x1080 are the design sizes (owner rule). Phone width (390) must still fit. *Owner rule.*
- **Thumb reach, bottom navigation, safe areas** (`env(safe-area-inset-*)`). *Widely accepted* platform practice (Apple HIG, Material). We did not re-read the pages this pass, so the checklist keeps this as a look-check, not a number.
- **Text never shrinks below 12 px** to make something fit (DESIGN.md, "never squash text to 11 px"). *Product rule.*

## 9. Motion and animation

- **Purpose.** Motion explains a change: where something came from or went. There is no ambient motion and one focal animation at a time (DESIGN.md motion contract). *Judgement and product rule.*
- **Durations.**
  - Material 1: desktop transitions 150-200 ms; mobile about 300 ms; large full-screen about 375 ms; over 400 ms feels slow; enter 225 ms is longer than exit 195 ms.
  - Material 3 tokens: short 50-200 ms, medium 250-400 ms, long 450-600 ms, extra long 700-1000 ms.

  *Widely accepted.* Product tokens are 100 hover, 150 open, 200 dialog/page, 240 panel and 120 exit, which fits the desktop band.
- **Easing.** Enter decelerates (ease-out) and exit accelerates (ease-in) and is shorter (Material 1/3). *Widely accepted.* The product has `--ease-enter`, `--ease-exit` and `--ease-move`.
- **60 fps.** Animate only `transform` and `opacity`, and use `will-change` sparingly. web.dev's example dropped 50% of frames animating `top`/`left` against 1% with `transform`. *Widely accepted.* The 16.7 ms frame budget is arithmetic (1000/60), not from that page.
- **No layout shift:** CLS ≤ 0.1 (web.dev). Reserve space for media with `width`/`height` or `aspect-ratio`.
- **Reduced motion:** `prefers-reduced-motion: reduce` (MDN, C39). The product makes it instant everywhere.

## 10. Performance as UX

- **Core Web Vitals "good" at the 75th percentile:** LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1. "Poor" is LCP > 4 s, INP > 500 ms, CLS > 0.25 (web.dev Web Vitals and thresholds). *Widely accepted.*
- **Product targets:**
  - dashboard first paint < 1 s (R8.3)
  - FCP ≤ 1.8 s
  - warm route < 300 ms
  - API p50 < 150 ms and p95 < 500 ms (DESIGN.md)
- **Perceived speed.** Use skeletons for full-screen loads and keep old data during refresh. Prefetch on hover or focus (DESIGN.md) and lazy-load below-the-fold previews. *Widely accepted / product rule.*
- **Payload budgets:** no external figure was verified this pass. *Judgement:* hold the 30% regression rule of R8.3 instead of an absolute size.

## 11. Wording and microcopy

- **Match the real world:** use the person's words, not system words (NN/g heuristic 2). *Widely accepted.* Product: `docs/wording.md`, enforced by `test_wording.py`.
- **Sentence case; buttons describe the action** (GOV.UK button). *Widely accepted.*
- **Errors:** what happened plus how to fix it, with no blame, no "invalid" and no "please/sorry" (GOV.UK error message; NN/g error messages). *Widely accepted.* R8.4: one sentence.
- **Sentence length about 25 words or fewer; reading age about 9.** These figures are commonly attributed to GOV.UK content guidance, but the guidance pages redirected or 404'd during this pass. *Judgement (unverified figure).* The checklist uses "at most 25 words" as a house rule.
- **Numbers, plurals, dates:** always pluralise correctly ("1 ticket", "2 tickets"). *Judgement.* Dates and times only via `UI.stamp` / `UI.clock` (SX-19). *Product rule.*
- **Owner vocabulary:** "Helper" for the agent, "Evidence" (never proof), none of the R4.1 banned words, no VPN product names (R7.1). A new user-facing noun needs the owner's OK (R4.2).

## 12. Consistency and design tokens

- **Consistency and standards** (NN/g heuristic 4). *Widely accepted.*
- **Product rules R6.1-R6.3 and DESIGN.md:**
  - tokens only
  - spacing on the 4-pt scale (4..64)
  - type scale from SX-2
  - radius 8 / 10 / 12
  - elevation (`--shadow`, `--lift-shadow`) only on menus, toast, dialog and sheet
  - status colours bounded to neutral, teal, blue, green, amber and rose

  `brand/tests/test_style_lint.py` fails on hex colours and `<style>` outside the master.

## 13. Visual polish

All *judgement and product rules*:

- **Alignment:** content shares one left and one right edge (SX-1, SX-4).
- **Truncation:**
  - Titles in rows truncate to one line with an ellipsis, and the full title shows on the item's own page.
  - Prose wraps. An unbroken long word must not overflow (`overflow-wrap: anywhere`).
- **Icons:** icons carry a visible label, or an accessible name if icon-only. Status always shows icon plus word (SX-9, WCAG 1.4.1).
- **Dark/light parity:** every token has a value in each theme, and contrast is checked in each.
  - Finding: today `tokens.css` is dark only (`color-scheme: dark`). Light exists only for workspace badges (`look-colors.css`) and mobile mode. The light-theme screenshots are therefore n.a. until the master ships light tokens.

## 14. Trust and safety in UI for AI helpers

- **Make clear what the system can do, how well, and why it did what it did; support efficient correction.** These come from Microsoft's Guidelines for Human-AI Interaction (Amershi et al., CHI 2019, 18 guidelines). *Widely accepted.* We confirmed the paper and its 18 guidelines. We did not re-read individual guideline numbers, so don't quote numbers.
- **Mental models, explainability + trust, feedback + control, errors + graceful failure** (Google PAIR People + AI Guidebook chapters). *Widely accepted (chapter list from search snippets).*
- **Our own judgement, built from the above and R2.4 / R3.3 / R7.3:**
  - **Cost and time before start.** Show the helper time, the person's time, any money cost and the "won't do" list before Start.
  - **Evidence before the OK.** "Looks good" sits next to the evidence for each task (R2.2).
  - **Show what the helper did and why** as a plain timeline. Keep the helper's own words unrewritten (wording.md).
  - **Reversible by default.** Show Undo, Not now, Stop and Pause automation near the action (R8.6).
  - **Sharing previews what leaves the machine** (R3.3).
- We found no verified NN/g article on agent transparency. A widely repeated "40% retention" claim attributed to NN/g could not be traced, so it is not used.

## Conflicts between general practice and owner rules (owner rule kept)

1. **Progressive disclosure toggles:** the owner rule wins. No Details toggles; detail goes plainly lower down.
2. **Typed confirmation for severe actions** (NN/g allows it): the owner rule wins. One click after a plain "what will happen".
3. **Free-text input as the primary path:** the owner rule wins. Offer choices with a default; typing is optional.
4. **Mobile-first responsive design** (common advice): the owner rule wins. Design desktop first (1280, 1920), and the phone must still fit.
5. **Button order:** the platform conventions differ. The product order from SX-13 is kept.
6. **No indicator under 1 s** (NN/g) vs a skeleton within 100 ms (product): kept as DESIGN.md reconciles it. A skeleton appears only where the load is expected to exceed 1 s.

## What this pass did not verify

Items marked *(not re-read)* above:

- the Apple HIG and Material target pages, which render with script
- the text of SC 1.3.1, 2.4.3, 3.2.3, 3.2.4, 3.3.1-3.3.3, 4.1.2 and 4.1.3; their levels are from the W3C quick reference and from memory
- NN/g's progressive disclosure and notification articles
- the GOV.UK 25-word and reading-age figures
- Microsoft guideline numbering
