// Factory from idea to a started run (ORCH-896): the person writes an idea on the Factory page and presses "Start
// with this idea" (an order in Draft appears); the stand-in helper proposes the run; the person reads the proposal
// and presses Start in its card. After the undo time the order is started, and a reload shows it as Running.
const fs = require('node:fs');
const path = require('node:path');

module.exports = {
  name: 'Factory: an idea becomes an order, the proposal is read and Start starts it',
  covers: ['addon.start'],
  async run({ page, open, reload, act, must, text, orch, orchAsPerson, addonOn, addonOff, until, workspace, slowOk }) {
    addonOn('factory');
    // the idea opens its new order's page, whose first answer may still be built (503, the page says Try again)
    slowOk(/^\/addon\/factory\/api\/order\/t_[a-z0-9]+$/);
    await open('#home');
    await until(s => (s.addons || []).some(a => a.name === 'factory'), 'Factory on');
    await open('#addon/factory');
    // the Factory page's own server, started from the page as a person does (as in o-factory-stage-review)
    const start = page.locator('[data-key="page-start"]');
    await start.waitFor({ timeout: 60000 });
    await act('addon.start', () => start.click());
    await until(s => (s.services || []).some(x => x.addon === 'factory' && x.running === true), 'Factory running');
    await reload();
    const frame = page.frameLocator('iframe.embed');

    const idea = 'A page that shows our opening hours and holiday closures';
    await frame.locator('textarea').first().fill(idea);
    await frame.getByRole('button', { name: 'Start with this idea' }).click();
    let orders = [];
    for (let i = 0; i < 30 && !orders.length; i++) {
      await page.waitForTimeout(1000);
      orders = JSON.parse(orchAsPerson('factory', 'list', '--json')).filter(o => o.title === idea);
    }
    must(orders.length === 1, 'no order was made from the idea');
    const order = orders[0].order;
    must(orders[0].stage === 'draft', `the new order is in ${orders[0].stage}, not draft`);

    // the helper's move, written as the stand-in helper (no model writes it here): propose the whole run (the contract's
    // own example, with this order's title)
    const repo = path.resolve(__dirname, '..', '..', '..', '..');
    const proposal = JSON.parse(fs.readFileSync(path.join(repo, 'contracts/examples/factory-proposal/valid-run.json'), 'utf8'));
    proposal.title = 'Opening hours page';
    const file = path.join(workspace, 'proposal-r.json');
    fs.writeFileSync(file, JSON.stringify(proposal));
    orch('factory', 'propose', order, '--file', file, '--json');
    fs.unlinkSync(file);

    // back to the Factory home (the idea opened its order's draft page): it lists the proposal under Waits for you
    await open('#addon/factory');
    const read = frame.getByText('Read proposal').first();
    for (let i = 0; i < 6 && !(await read.isVisible()); i++) { await page.waitForTimeout(3000); await open('#addon/factory'); }
    await read.waitFor({ timeout: 10000 }).catch(async () => {
      throw new Error('no "Read proposal" on Factory:\n' + (await frame.locator('body').innerText()).slice(0, 600));
    });
    await read.click();
    await frame.getByRole('button', { name: 'Answer' }).click();
    const card = page.locator('dialog[open]');
    must(/Start 'Opening hours page'\?/.test(await card.innerText()), 'the answer card does not ask to start the run');
    await card.getByRole('button', { name: 'Start', exact: true }).click();
    let started = false;
    for (let i = 0; i < 40 && !started; i++) {   // the answer waits out its undo time first
      await page.waitForTimeout(1000);
      started = JSON.parse(orchAsPerson('factory', 'show', order, '--json')).started === true;
    }
    must(started, 'the order did not start after Start');
    await open('#addon/factory');
    // the Factory page fills in after it is drawn: wait for the Running row instead of reading the first picture
    const body = () => page.frameLocator('iframe.embed').locator('body').innerText({ timeout: 5000 }).catch(() => '');
    let shown = '';
    for (const end = Date.now() + 20000; !/Running[\s\S]*Opening hours page/.test(shown = await body()) && Date.now() < end;) await page.waitForTimeout(250);
    must(/Running[\s\S]*Opening hours page/.test(shown), 'Factory does not show the order as Running after a reload:\n' + shown.slice(0, 400));
    await open('#home');   // leave the Factory tab first: an open tab asks for the page again once Factory is off (a 404)
    orchAsPerson('stop');
    await addonOff('factory');   // off again for the next click-through
  },
};
