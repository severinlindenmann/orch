// Where the helper's browser shows (ORCH-1494): with the browser add-on on, the Browser page (its tab) lists every
// helper's browser. A click-through cannot start a real browser, so a browser that ended a minute ago stands in (its
// state file, as the broker leaves it): the Browser page lists it under "Ended today" as a link, its ticket shows one
// quiet "ended" line and no picture, and the ticket's live view (#ticket/<id>?browser=open) says no browser is open,
// with Hide taking it away again. With nothing at all the Browser page shows its one empty state. The live pictures
// and the preview's live state are proven in the add-on's tests (test_live_view.py) and tests/browse_places.test.js.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Browser page: ended today as a link, the quiet line on the ticket, the live view opens and hides',
  covers: ['page:ticket'],
  async run({ page, open, reload, must, text, orch, workspace, addonOn, addonOff, until }) {
    await open('#home');
    addonOn('browse');
    await until(s => (s.addons || []).some(a => a.dashboard?.panel === 'browser'), 'the Browser tab');
    await open('#addon/browse');
    await page.getByText('No helper is using a browser right now').waitFor({ timeout: 30000 });
    must(!(await page.getByRole('button', { name: /Open the helper’s browser/ }).count()), 'a preview shows with no browser');

    const tid = JSON.parse(orch('ticket', 'new', 'Look up the opening hours of the bakery', '--json')).id;
    const run = path.join(workspace, '.orch', 'addons', 'browse', 'run', tid);
    fs.mkdirSync(run, { recursive: true });
    fs.writeFileSync(path.join(run, 'state.json'), JSON.stringify({ state: 'ended', why: 'closed after 15 minutes without a command' }));
    await reload();
    await page.getByText(/Ended today/).waitFor({ timeout: 30000 });
    const link = page.getByRole('link', { name: 'Look up the opening hours of the bakery' });
    await link.waitFor({ timeout: 30000 }).catch(async () => { throw new Error('the ended browser is not a link on the Browser page:\n' + (await text()).slice(0, 400)); });
    must(/ended at \d\d:\d\d/.test(await text()), 'the ended line does not say when');
    await link.click();
    await page.getByText(/The helper’s browser ended at \d\d:\d\d\./).waitFor({ timeout: 30000 });
    must(!(await page.getByRole('button', { name: /Open the helper’s browser/ }).count()), 'an ended browser still shows a picture to open');

    await open('#ticket/' + tid + '?browser=open');
    await page.waitForFunction(() => ['none', 'ended'].includes(document.querySelector('.bview')?.dataset.state), null, { timeout: 30000 });
    must(!(await page.getByRole('button', { name: 'Stop browser' }).count()), 'Stop shows with no browser open');
    await page.getByRole('button', { name: 'Hide' }).click();
    await page.waitForFunction(() => !document.querySelector('.bview') && !location.hash.includes('browser=open'), null, { timeout: 10000 });
    await reload();
    must(!(await page.locator('.bview').count()), 'the live view came back after Hide and a reload');
    fs.rmSync(path.join(run, 'state.json'));
    await addonOff('browse');
  },
};
