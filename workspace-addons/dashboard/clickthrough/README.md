# Dashboard click-throughs

Every dashboard feature has a click-through: a short browser test that does the thing like a person in the real
page, reloads, checks the result is still there, and fails on any console error. They run on a seeded demo workspace
with the real dashboard server and this checkout's orch (`server.py`), so a click writes real ticket files and a
reload shows what really happened.

**Rule: a new dashboard feature brings its click-through in the same pull request.** The `dashboard` CI job
(`tests/clickthrough_catalogue.test.js`) fails and names the feature when nothing claims it; the `dashboard-clickthroughs` job
runs every click-through and fails when one breaks, or claims a feature it never really did.

## What counts as a feature

Read from the code by `catalogue.cjs`, never typed by hand:

- every action the page can send (an op of the server's action table that the page code names), and
- every page of the router, and each Settings tab (`page:home`, `page:settings/agent`, ...).

`node clickthrough/catalogue.cjs` prints the list and what has no click-through yet.

Every feature has a click-through; there is no list to park one on. An op the page only compares
(`x.action.op === 'message.send'`: it recognises an add-on view's button and does something else) is not counted,
because the page never sends it.

## Stand-ins for what lives outside this computer

`server.py` starts these in the throw-away home; nothing reaches the internet or the computer's own orch:

- a relay and a publish server on 127.0.0.1 (the fakes of `workspace/tests/fakes.py`: one paired phone, one
  workspace "Kitchen"). They stay unused until a click-through turns the relay or publish on and connects it
  (`orch addon add relay --yes`, `orch relay connect <url> --workspace <id> --token <token>`, addresses in
  `standins`), and it turns them off again at its end;
- a `gh` program that answers only for pull requests of the made-up repository `standin/lunch` (open, green,
  one head commit `standins.head`) and "merges" by writing a line;
- the built-in agent programs (from orch's adapter list): their login check says signed out until their sign-in
  got a code;
- the add-ons Focus, Lessons and Pull requests of this checkout (`run.cjs` layers them into every orch of the
  run): installed and allowed but off; a click-through turns one on with `orch addon add <name> --project-only`;
- `ORCH_REPO` is this checkout, so "the newest orch" is read from here. An update or an uninstall then stops with
  a plain reason (this demo runs orch from its source folder, not from an installed tool folder).

## Run them

    node workspace-addons/dashboard/clickthrough/run.cjs                     all of them (as in CI)
    node workspace-addons/dashboard/clickthrough/run.cjs --only new-ticket   one file
    node workspace-addons/dashboard/clickthrough/run.cjs --out /tmp/ct       plus a picture of each end state
    node workspace-addons/dashboard/clickthrough/run.cjs --list              who covers what, no browser

Needs Node, uv and Playwright with Chromium (`PW_DIR=<folder with node_modules/playwright>` if it is not global).
Everything runs in a throw-away home under `~/.orch-test` with `env -i`; the orch of this computer is never touched.
No real agent can run: the workspace helper is a stand-in script, and programs named like the built-in agent
tools (read from orch's adapter list) are stand-ins first on PATH, so a Start, a Test or a ticket pinned to a
built-in tool runs a stand-in. `server.py` refuses to
start otherwise. A click-through that needs a helper's own move (a chat reply, a proposal) uses `orch(...)`.

## Write one

One file per feature (or a small group of features done in one flow) in `features/`:

```js
// New ticket from Home: write what needs doing, "Save without starting", reload, the ticket is in the list.
module.exports = {
  name: 'New ticket: save without starting',
  covers: ['ticket.new', 'page:home', 'page:tickets'],
  async run({ page, ids, open, reload, act, must, text }) {
    await open('#home');
    await page.getByRole('button', { name: 'New ticket' }).first().click();
    const dlg = page.locator('dialog[open]');
    await dlg.getByPlaceholder(/What should the helper do/).fill('Order the cake for Friday');
    await act('ticket.new', () => dlg.getByRole('button', { name: 'Save without starting' }).click());
    await open('#tickets');
    await reload();
    must((await text()).includes('Order the cake for Friday'), 'the new ticket is not in the list after a reload');
  },
};
```

- `orch(...words)` runs this checkout's orch in the demo workspace as the stand-in helper; `workspace` is its folder.
  `orchAsPerson(...)` is the same as the person at the computer, `orchIn(dir, ...)` in another folder of the home,
  `git(dir, ...)` git with no settings of this computer, `python(code, ...args)` a short snippet with orch importable.
- `until(check, what)`: after a change made outside the page, wait until the page's state passes `check(state)`.
- `home` is the throw-away home, `standins` where the stand-ins listen.
- `open(hash)` goes to a dashboard address and waits until it is drawn; `reload()` reloads and waits.
- `act(op, fn)` runs `fn` (your click) and waits for the page to send `op`; it fails when the server refuses it.
  `act(op, fn, {refused: true})` is for an action that is meant to be refused here (it needs an outside service
  this demo has not got): then check that the page shows the plain refusal.
- `ids` are the seeded tickets: `lunch` (working, one step done, an open question "Which restaurant?"), `menu`
  (done, with a summary), `table` (two open steps), `budget` (no steps). Click-throughs share one workspace and run
  in file order, so make your own ticket when you change one in a way another click-through would notice.
- Use roles and visible words (`getByRole('button', {name: ...})`), as a person sees the page.
- `covers` lists what the click-through really does; the runner checks each op was really sent and each page
  really shown.
