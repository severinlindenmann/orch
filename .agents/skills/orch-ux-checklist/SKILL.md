---
name: orch-ux-checklist
description: Use when doing ANY UI or UX work on orch (dashboard, add-on page, phone width, mockup) - a new page, component or state (empty, loading, error), words on screen, motion, a visual fix, a layout or flow change, a review of a UI pull request, a UX audit or design critique, or deciding whether a screen "looks right" before showing the owner.
---

# orch UX/UI checklist

The checklist every orch UI change passes before it is called done. It extends the master design system and
never overrides it. Order of authority: owner rules > `DESIGN.md` (SX-1..20) + `AGENTS.md` R6/R7 + `docs/wording.md` >
this checklist > general practice.

Full list with thresholds and how to check: `references/CHECKLIST.md`. Sources and strength of every rule
(WCAG 2.2, NN/g, web.dev, GOV.UK, Material): `references/RESEARCH.md`. Worked example: `references/TRIAL.md`.

## Procedure (every UI change)

1. **Open the design system first** (skill `orch-design-system`): `workspace/src/orch_ui/static/DESIGN.md` and
   `gallery.html`. Find the existing component and token before writing anything.
2. **Build from the master.** Missing component or state → add it to the master with a gallery entry per state, in
   the same PR. Never page-local CSS, a hex colour, or a re-made button/select/toast/dialog/empty state.
3. **Update the mockup in the same PR** (skill `orch-mockup`).
4. **Screenshots** at exactly 1280x800, 1920x1080 and 390x844 (plus 320 for reflow), dark and light (light: n.a.
   while `tokens.css` is dark only), one set per state touched (loaded, loading, empty, error, stale, long content),
   one with keyboard focus on the main action, and a before/after pair around the main click.
   Tool: `~/orch-dev/scripts/shot.sh <url> <out.png> <w> <h>` (or any headless Chromium with a temporary profile).
   Pictures go on the ticket as evidence (`orch check done ... --file`), never into git.
5. **Run the checklist** below: [auto] items by test/script, [eye] items by looking at every screenshot.
   Answer each yes / no / n.a.; fix every "no" or write why. Automatic in CI today (run them locally too):
   `node workspace/src/orch_ui/tests/ux_checks.cjs` (master gallery at 1280/390/320: sideways scroll, 24 px
   targets, focus mark, reduced motion, text contrast, console errors), `brand/tests/test_contrast.py` (token
   contrast), `scripts/check_style.py` (no page-local colours), `brand/tests/test_wording.py` and the banned-word
   check. `DESIGN.md` "UX/UI checklist" lists which items stay by eye.
6. **PR body:** `UX checklist: 61 items, N n.a., all others yes` (or the "no" lines with reasons), `Screenshots:`,
   `Mockup: updated <where>`, `Master: <change or none>`, rules touched.
7. **Visual or flow change → owner review card** in orch with before/after pictures. Never assume the owner agrees.

## Owner rules (always win)

- One click, no typed words (no typed confirm, choices before free text).
- Minimal plain words; detail shown plainly lower down - no "Details" / "Technical details" / "Show more" toggles.
- Desktop first (1280 and 1920); phone width must still fit.
- One master design system: extend it, never page-local CSS or a re-made component; mockup in the same PR.
- Words: "Helper" for the agent, "Evidence" (never proof), none of the R4.1 banned words, never a VPN product name
  ("private network"); a new user-facing noun needs the owner's OK.
- Costly actions (starting a helper) are never the easiest click.

## Checklist (compact; thresholds in references/CHECKLIST.md)

**A Design system** A1 [auto] no new CSS/`<style>`/hex outside the master (style lint) · A2 [auto] tokens only,
4-pt spacing, radius 8/10/12 · A3 [eye] master components only; new ones in gallery · A4 [eye] SX-2 type scale,
SX-1/SX-4 edges at 1280 · A5 [eye] mockup changed in the PR and matches · A6 [eye] polish: edges, status icon in
pills, no lone-initial avatars, ellipsis, nothing clipped.

**B Hierarchy** B1 [eye] 5-second test: what, why, what can I do · B2 [auto] exactly one filled button incl. top
bar; New ticket outlined · B3 [eye] ≤7 facts per card, ≤5 KPIs, no Details toggles · B4 [eye] long text ≤3 lines at
level 1, prose ≤76ch · B5 [eye] no repeated sentence; counts match everywhere.

**C Navigation** C1 [eye] active nav + crumb + title = nav label · C2 [auto] every view/tab/filter has a URL; Back
keeps scroll · C3 [eye] no dead ends; every state has a next step.

**D Actions** D1 [eye] verb labels naming the outcome, no OK/Submit · D2 [eye] costly action: cost/time above it,
not filled/autofocus/default, cheaper choice beside it · D3 [eye] destructive: Danger, apart, Undo over confirm ·
D4 [eye] dialog footer `[tertiary] … [Cancel] [Primary]` · D5 [eye] disabled says why, next to it.

**E States** E1 [eye] skeleton shaped like the result within 100 ms if load may pass 1 s; no page spinner ·
E2 [eye] master empty state ≤240 px, one sentence, one button, after loading · E3 [eye] error: what happened, what to
do, one button, by its source · E4 [eye] stale/partial/offline keeps data, "Updated … ago" · E5 [eye] 0/1/many,
plurals, 200-char title, long word · E6 [eye] missing permission/add-on: hidden or disabled with reason.

**F Feedback** F1 [eye] response ≤0.1 s · F2 [eye] 1-10 s inline spinner + label; >10 s step + elapsed + Cancel ·
F3 [eye] toast 5 s, names object, Undo; errors persist · F4 [auto] live updates `role=status`, never steal scroll.

**G Forms** G1 [auto] visible labels, `autocomplete`/`inputmode` · G2 [eye] default chosen, choices before typing ·
G3 [eye] validate on continue (not blur), error next to field + summary.

**H Accessibility (WCAG 2.2 AA)** H1 [auto] text 4.5:1, large (≥24 px / 18.66 px bold) 3:1 · H2 [auto] UI parts
and focus 3:1 · H3 [auto] all by keyboard, visual order, no trap, Escape returns focus · H4 [eye] focus visible,
not under sticky bars (2.4.11) · H5 [auto] targets ≥24x24 CSS px; touch 44x44 · H6 [auto] name/role/state, label
in name; axe 0 serious · H7 [auto] one h1, ordered headings, landmarks, skip link, unique title · H8 [eye] colour
never alone · H9 [auto] 320 px and 200% text, no page sideways scroll · H10 [auto] reduced motion = no motion.

**I Responsive** I1 [auto] no page sideways scroll/clipping at 1920/1280/390/320 · I2 [eye] main action above the
fold at 1280x800; 1920 not stretched · I3 [eye] phone: nav reachable, thumb reach, no hover, text ≥12 px.

**J Motion** J1 [auto] token durations (100/150/200/240, exit 120), ≤240 ms · J2 [eye] purposeful, ease-out in,
shorter ease-in out, no idle motion · J3 [auto] transform/opacity only, CLS ≤0.1 · J4 [auto] ≤3 flashes/s, pause
for motion >5 s.

**K Performance** K1 [auto] p75 LCP ≤2.5 s, INP ≤200 ms, CLS ≤0.1; first paint <1 s · K2 [eye] old content stays
while loading; no spinner over 1 s.

**L Words** L1 [auto] wording + banned-word tests green · L2 [eye] Helper, Evidence; SX-18 bans the test misses
("agent", "Reference", …); new nouns owner-approved · L3 [eye] sentence case, ≤25 words, no IDs/jargon/raw values
· L4 [eye] errors say what and what to do, no blame, no "invalid" · L5 [auto] dates via `UI.stamp`/`UI.clock` only ·
L6 [eye] one word per thing everywhere.

**M Helper trust** M1 [eye] before start: what, helper time, your time, cost in ≤3 lines · M2 [eye] evidence on the
same screen as "Looks good" · M3 [eye] plain timeline of what the helper did · M4 [eye] stop/undo visible at the
decision and on the ticket.

## Non-negotiable (never ship with a "no")
A1, A3, B2, D2, E3, H1, H3, H5, I1, L1.

## Common mistakes
- Shooting at 1400 px or one theme only: A4, B4 and I2 cannot be judged. Use the exact sizes.
- Only the loaded state: groups E and F need state shots and a before/after click pair.
- Trusting `test_wording.py` alone: it misses SX-18 level-1 bans such as "Reference" and "agent".
- Pasting the helper's whole plan into a card: level 1 shows ≤3 lines; the rest goes lower down.
- Filled top-bar "New ticket" next to the page's own primary action: two primaries.
- Old "Details" disclosures in DESIGN.md (SX-11, legacy reference text) or older notes: legacy, do not copy.
