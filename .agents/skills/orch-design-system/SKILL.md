---
name: orch-design-system
description: Use for ANY orch UI work (dashboard page, add-on page, mockup, draft, visual fix, new widget, style, motion, empty/loading/error state). The one master component library and style guide lives in the monorepo at workspace/src/orch_ui/static; build on it and extend it there, never create a new sheet or copy.
---

# orch design system (the one master, AGENTS.md R6)

Owner, 14 Nov: "make sure we have a really big master with all the stuff we need … in the future we build on top of
this, add here also new stuff if we need it instead of always making a new one."

## Where
- `workspace/src/orch_ui/static/`: tokens.css (generated from `brand/tokens.json`), components.css/js,
  motion.css/js, interaction.css, overlay.js, select.js, icons.js, fileviewer, blocks, question-card, date.js, … plus
  `gallery.html` (every component in every state, motion Replay), `DESIGN.md` (rules: tokens, which component when,
  wording, density, motion, how to add, the UX/UI checklist) and `COMPONENT-QA.md`.
- Served by core (orch_ui) to the dashboard and every add-on (`__P__/kit/<file>` in add-on pages, `kit/<file>` in the
  dashboard). No copies in add-ons or the dashboard; mockup pages link the master by relative path.

## Rules for every UI task
1. Open `gallery.html` + `DESIGN.md` first; use existing components and tokens only.
2. Missing widget or state? Add it to the master (component + gallery entry + test) in the same PR, then use it.
3. No page-local colours, spacing, buttons, selects, chevrons, empty states, toasts or dialogs; no new stylesheet,
   `<style>` block or hex colour outside the master (`scripts/check_style.py` fails the PR). Page stylesheets may only
   lose or edit rules, never gain them.
4. Update the mockup page in the same PR (skill orch-mockup); the PR template asks for it.
5. Owner rules: one click, no typed words; minimal plain words; desktop first (1280 + 1920); motion from the master
   tokens; never name the VPN product ("private network").
6. Before calling a UI change done, run skill `orch-ux-checklist` (61-item UX/UI checklist, screenshots at 1280, 1920
   and 390, result in the PR body). A change to the master must keep `node workspace/src/orch_ui/tests/ux_checks.cjs`
   green (the gallery is what it checks).
