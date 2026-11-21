# Click-through: the new Focus (draft D)

The tester's script for the new Focus (ORCH-261). Every feature of draft D is one numbered step with what to do, what
must be seen and the picture to take at 1280, 1440, 1920 and 390 wide. The readable list is
[CLICKTHROUGH.md](CLICKTHROUGH.md); the source is [steps.cjs](steps.cjs).

## Run it

From the repo root (Playwright is found in `PW_DIR`, `~/orch-dev/e2e/dashboard/node_modules`, or the global install):

    node e2e/focus_d/clickthrough.cjs --out ~/.orch-test/focus-d-shots

- Starts the real dashboard on fake data, in a throw-away home under `~/.orch-test`
  (`env -i`, own `HOME`, `USERPROFILE` and `ORCH_HOME`, `ORCH_HOME_STRICT=1`). The orch of the computer is never used.
- Chromium gets a fresh context (launch() + newContext(), no profile folder) and `--use-mock-keychain --password-store=basic` (through `e2e/headless.cjs`).
- Ready steps are clicked at each width; a page error, a console error, sideways scroll or a failed check fails the run.
  Pending steps are listed with the crew task they wait for and never fail the run.
- Pictures land as `<step name>-<width>.png` next to `report.md` in the `--out` folder.

Reference pictures of the same steps in the draft D mockup, to put beside the built screens:

    node e2e/focus_d/clickthrough.cjs --target draft --out ~/.orch-test/focus-d-draft

(`--repo <checkout>` when the mockup is not in this checkout yet.) `--only 1,9,12` runs some steps,
`--list` prints the script without a browser, `--video <folder>` keeps a recording of every page it opened (a short
recording of the flow for the ticket).

The CI job `page-smoke` runs the dashboard target (from `e2e/focus_insights_smoke.cjs`) on every change to the
workspace or its add-ons.

## When you build a feature

1. In `steps.cjs` give its step a `run({ page, dash, focus, width })` that clicks it in the real dashboard (`dash` is
   the dashboard address; open pages by their link) and throws when something that must be seen is missing.
2. Delete its `waits` line.
3. `node e2e/focus_d/clickthrough.cjs --write-md`, then commit `steps.cjs` and `CLICKTHROUGH.md` together
   (`workspace-addons/dashboard/tests/focus_d_clickthrough.test.js` fails when they differ).
4. Run it, copy the pictures of your step into your ticket, and name the result in the PR body.

A new feature in draft D gets a new step with its own picture name; the test checks every part the owner listed
(wall, bar, layer, split, sessions, chat, message box, voice, 16 widgets, terminal, motion, reduced motion, phone
width) keeps at least one step.
