// Take over and give back (ORCH-1495): a helper asks for a person in its browser (orch browse ask-person). A
// click-through cannot start a real browser, so a broker's state file that asks stands in (as the broker writes it;
// its process id is this test runner, so it counts as running): Home shows one line, "The helper needs you in its
// browser." with the helper's words and one button that opens the ticket's live view. The real take over, input,
// give back and the helper's waiting are proven with a real headless browser in the add-on's tests
// (workspace-addons/browse/tests/test_take_over.py), the routes in test_browseview.py, the page in
// tests/browse_takeover.test.js and the kit in workspace/src/orch_ui/tests/browser.test.mjs.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Browser: the helper asks for a person, Home shows one line that opens its browser',
  covers: ['page:home'],
  async run({ page, open, reload, must, text, orch, workspace, addonOn, addonOff, until }) {
    await open('#home');
    addonOn('browse');
    await until(s => (s.addons || []).some(a => a.dashboard?.panel === 'browser'), 'the Browser tab');
    const tid = JSON.parse(orch('ticket', 'new', 'Download the October invoices from the supplier portal', '--json')).id;
    const run = path.join(workspace, '.orch', 'addons', 'browse', 'run', tid);
    fs.mkdirSync(run, { recursive: true });
    fs.writeFileSync(path.join(run, 'channel.json'), '{}');
    fs.writeFileSync(path.join(run, 'state.json'), JSON.stringify({
      state: 'ready', generation: '0123456789abcdef', pid: process.pid, started: Date.now() / 1000,
      control: { state: 'helper', asking: 'Please sign in to the supplier portal' },
    }));
    await reload();
    await page.getByText('The helper needs you in its browser.').waitFor({ timeout: 30000 })
      .catch(async () => { throw new Error('Home does not show the helper asking:\n' + (await text()).slice(0, 400)); });
    must((await text()).includes('Please sign in to the supplier portal'), 'Home does not say what the helper asks');
    await page.getByRole('link', { name: 'Open the browser' }).click();
    await page.waitForFunction(t => location.hash === '#ticket/' + t + '?browser=open', tid, { timeout: 10000 });
    await page.waitForSelector('.bview', { timeout: 30000 });
    fs.rmSync(path.join(run, 'state.json'));
    fs.rmSync(path.join(run, 'channel.json'));
    await open('#home');
    await reload();
    await page.waitForFunction(() => !document.body.innerText.includes('The helper needs you in its browser.'), null, { timeout: 30000 });
    await addonOff('browse');
  },
};
