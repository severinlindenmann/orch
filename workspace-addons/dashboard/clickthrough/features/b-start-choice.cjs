// The one Start button (ORCH-475): the caret opens the Start choice, its Fresh start starts fresh, and a double click on
// the main half starts one run. (The demo's stand-in tools take no model: the choice says so instead of a Model picker.)
// START_SHOTS=<folder> keeps pictures of the open choice at 1280 and 390 (for the UX checklist).
const path = require('node:path');
const idOf = out => (/\[(t_[A-Za-z0-9]+)\]/.exec(out) || [])[1];

module.exports = {
  name: 'Start button: the Start choice, Starting and one run per double click',
  covers: ['run.start', 'run.stop'],
  async run({ page, open, reload, act, must, orch }) {
    const shots = process.env.START_SHOTS || '';
    const starts = [];
    page.on('request', r => { if (r.url().endsWith('/api/act') && r.headers()['x-orch-op'] === 'run.start') starts.push(r.url()); });
    const stopIt = async () => {
      const stop = page.getByRole('button', { name: 'Stop', exact: true });
      await stop.waitFor({ timeout: 15000 });
      await act('run.stop', () => stop.click());
    };

    // the caret opens the choice: Fresh start with tool and model, the places line
    const water = idOf(orch('ticket', 'new', 'Water the plants on the terrace'));
    must(water, 'no new ticket');
    await open('#ticket/' + water);
    const main = page.locator('[data-key="ticket-start"] [data-start="main"]');
    must((await main.innerText()).trim() === 'Start helper', 'a ticket that never ran does not say Start helper');
    await page.locator('[data-key="ticket-start"] summary[aria-label="Other ways to start"]').click();
    const choice = page.locator('[data-key="ticket-start"] .start-pop');
    await choice.getByText('Fresh start', { exact: true }).waitFor({ timeout: 5000 });
    const said = await choice.innerText();
    must(/Start a helper/.test(said) && /Fresh start/.test(said), 'the Start choice is not shown: ' + said);
    must(!/Continue where it stopped/.test(said), 'Continue is offered with no earlier session');
    if (shots) {
      await page.screenshot({ path: path.join(shots, 'start-choice-1280.png') });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(200);
      await page.screenshot({ path: path.join(shots, 'start-choice-390.png') });
      await page.setViewportSize({ width: 1280, height: 900 });
    }

    must(/This tool uses its own model\./.test(said), 'a tool without models does not say so');
    // Fresh start from the choice: a fresh run starts
    const fresh = [];
    page.on('request', r => { if (r.url().endsWith('/api/act') && r.headers()['x-orch-op'] === 'run.start') fresh.push(JSON.parse(r.postData() || '{}').args || {}); });
    await act('run.start', () => choice.getByRole('button', { name: /^Fresh start on/ }).click());
    must(fresh.length === 1 && fresh[0].fresh === true, 'Fresh start did not start fresh: ' + JSON.stringify(fresh));
    await stopIt();

    // a double click on the main half starts one run
    const soup = idOf(orch('ticket', 'new', 'Order soup for the team lunch'));
    await open('#ticket/' + soup);
    starts.length = 0;
    await page.locator('[data-key="ticket-start"] [data-start="main"]').dblclick();
    // Starting… until the helper runs (then the page shows Stop instead)
    await page.waitForFunction(() => /Starting…/.test(document.querySelector('[data-key="ticket-start"]')?.textContent || '')
      || [...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Stop'), null, { timeout: 5000 });
    await page.waitForTimeout(1500);
    must(starts.length === 1, 'a double click sent ' + starts.length + ' starts');
    if (shots) await page.screenshot({ path: path.join(shots, 'start-after-dblclick-1280.png') });
    await stopIt();
    await reload();
  },
};
