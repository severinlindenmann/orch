# Trial: [eye] items on three existing screenshots (16 Nov 2026)

Shots (from `~/orch-dev/state/dogfood/dash-loop/ux-review/before/`):
- **H** = `d-home.png` (desktop, 1400x1000, Home with one question)
- **T** = `d-ticket-question.png` (desktop, 1400x1000, ticket waiting on a question, Overview tab)
- **P** = `p-home.png` (phone, 390 wide, Home)

Only the loaded state, dark theme, no focus and no interaction are visible, so most of groups E and F are n.a. here.
Item numbers as in the first draft of CHECKLIST.md; changes made after the trial are listed at the end.

| Item | H | T | P | Why (one line) |
|---|---|---|---|---|
| A3 master components | no | yes | no | H/P: "Needs you · 1" pill has no status icon, Working-now avatars are lone "C" initials; T pill has its icon. |
| A4 type and layout | no | no | n.a. | H/T shot at 1400 px, so SX-1 edges cannot be judged; T question text is ~20 px (banned by SX-2) and tab counts are mono with mixed widths ("2" vs "10"). |
| A5 mockup | n.a. | n.a. | n.a. | Cannot be answered from a screenshot; needs the PR diff. |
| B1 5-second test | no | yes | no | H/P: headline is clear but what to decide is buried in a 25-line paragraph; T header strip (pill, title, one sentence, Answer) answers it. |
| B3 facts / no toggles | no | yes | no | H/P card shows 10+ facts (goal, done-means, steps, crew, cap, ship, won't do); no Details toggle anywhere (yes on that half). |
| B4 long text | no | no | no | The helper's whole plan is level 1 on all three; on T at ~20 px it fills the first screen. |
| B5 no repeats | yes | no | yes | Count "1" matches in sidebar, top bar, headline and pill; T repeats the question sentence in header and body. |
| C1 where am I | yes | yes | no | H/T active nav and crumb correct; P shows no nav or crumb at all, only a workspace icon. |
| C3 no dead end | yes | yes | yes | Each view offers the next step (Start/Edit/Not now, Answer). |
| D1 verb labels | no | yes | n.a. | H "Start" does not name the outcome (start what? "Start helper"); T "Answer" is clear. |
| D2 costly action | yes | n.a. | n.a. | H: ~10 h / ~15 min shown, Start is outlined and sits beside Edit and Not now at equal weight; no typed word. |
| D3-D5 | n.a. | n.a. | n.a. | No destructive action, dialog or disabled control in view. |
| E1-E3 | n.a. | n.a. | n.a. | Loaded state only. |
| E4 stale | yes | yes | n.a. | "Updated just now" in the top bar; P top bar is clipped so it is not visible. |
| E5 long content | yes | yes | yes | Long text wraps without overlap; T header sentence truncates with an ellipsis. (The real problem is B4, not wrapping.) |
| E6 missing permission | yes | n.a. | n.a. | Phone toggle shown off in the sidebar, no broken control. |
| F1-F3 feedback | n.a. | n.a. | n.a. | Static shots cannot show response to a click. |
| G2 choices first | yes | n.a. | n.a. | H offers three choices; "Write your own…" is the optional extra. |
| G3 validation | n.a. | n.a. | n.a. | No form. |
| H4 focus | n.a. | n.a. | n.a. | No focus visible in any shot. |
| H8 colour not alone | yes | yes | yes | Status always has a word; amber is never the only signal. |
| I2 above the fold | no | yes | n.a. | H at 1280x800 the Start/Edit/Not now row (y≈825 at 1000 tall) would be below the fold; T Answer is in the header. |
| I3 phone | n.a. | n.a. | no | P: top bar clipped at the right edge ("M…"), no visible navigation, main decision buttons many screens down. |
| J2, K2 | n.a. | n.a. | n.a. | No motion or refresh visible. |
| L2 helper / evidence words | yes | no | yes | T shows "References" / "Add reference" (SX-18 bans "Reference" on level 1; the wording test does not catch it). |
| L3 plain words | no | no | no | Level 1 shows "develop line", "green checks", "user units", "launch agents"; T shows the raw value "Factory stage: proposed". |
| L4 error/empty text | n.a. | n.a. | n.a. | None in view. |
| L6 same words | yes | yes | yes | Needs you, Helper, Answer used consistently. |
| M1 before start | no | no | no | Time and person-time are there, but inside the wall of text, not in 3 lines. |
| M2 evidence before Looks good | n.a. | n.a. | n.a. | Not a Check state. |
| M3 what the helper did | n.a. | n.a. | n.a. | Activity tab not shown. |
| M4 stop/undo | yes | n.a. | n.a. | "Not now" beside Start; first draft said "next to every helper action", which H's Working-now list would fail unfairly. |

Also seen (auto items, noted while looking): H/T/P top-bar "New ticket" is filled (SX-4 wants outlined); on T it is a
second filled button next to "Answer" (B2 no). P has page-level horizontal clipping (I1 no).

## Top findings for the product (not fixed here: no product code changed)
1. The helper's full plan is level-1 text on Home, the ticket and the phone (B4, M1, L3). This is the biggest issue.
2. Two filled buttons on the ticket; top-bar New ticket filled everywhere (B2, SX-4).
3. Phone: clipped top bar, no reachable navigation (I1, I3, C1).
4. Missing status icon in the Home pill, lone-initial avatars, mono tab counts, 20 px question text (A3, A4).
5. "References" and "Factory stage: proposed" on the ticket (L2, L3).

## What the trial changed in the checklist
- **A4**: must be judged on a shot at exactly 1280 px; named the two known SX-2 slips (mono tab counts, 20 px question text). How-to-check now demands exact sizes.
- **A5**: rephrased as "the PR diff touches the mockup", since a screenshot cannot answer it.
- **A6 (new)**: polish line (status icon in pills, no lone initials, edges, ellipsis, no clipping); the first draft had no place for these.
- **B2**: "top-bar New ticket is always outlined" (the draft only said so when the page had its own action, which let Home pass wrongly).
- **B4 / M1**: one threshold, "at most 3 lines at 1280", and plan / won't-do go lower down; the draft's "level 1" was too vague to fail anything.
- **B5**: "each fact appears once" was ambiguous (a matching count in four places is intended by SX-20); now "no repeated sentence, counts match".
- **D2**: "easiest click" made concrete: not filled, not autofocus, not Enter default, never alone, a cheaper choice at equal or greater weight.
- **L2 / L3**: added the SX-18 bans the wording test does not catch ("Reference" etc.) and "raw stored values / dev jargon".
- **M4**: scoped to the point of decision and the helper's ticket.
- **How to check**: a focused shot and a before/after pair around the main click, because groups E-F and H4 were all n.a. on static shots.
