// Steps of a ticket: a person adds a step, renames it, moves it, ticks it, marks one "Won't do", reopens it, removes one.
module.exports = {
  name: 'Steps: add, rename, move, tick, won\'t do, reopen, remove',
  covers: ['check.add', 'check.edit', 'check.move', 'check.set', 'check.wont_do', 'check.reopen', 'check.remove'],
  async run({ page, open, reload, act, must, text }) {
    // a ticket of our own, so other click-throughs keep their seeded steps
    await open('#home');
    await page.getByRole('button', { name: 'New ticket' }).first().click();
    const dlg = page.locator('.new-ticket-page');  // the New ticket page (ORCH-1037)
    await dlg.getByPlaceholder(/What should the helper do/).fill('Steps walk: print the posters');
    await act('ticket.new', () => dlg.getByRole('button', { name: 'Save without starting' }).click());
    await page.waitForFunction(() => location.hash.startsWith('#ticket/'), null, { timeout: 15000 });  // the saving moment, then the new ticket
    await open('#tickets');
    await page.getByRole('link', { name: /Steps walk: print the posters/ }).first().click();
    await page.waitForFunction(() => /^#ticket\//.test(location.hash));
    const hash = await page.evaluate(() => location.hash);
    await open(hash);
    const tasksTab = async () => { await page.getByRole('tab', { name: /^Tasks/ }).click(); };
    await tasksTab();

    const add = async t => {
      await page.getByLabel('Add a task').first().fill(t);
      await act('check.add', () => page.getByLabel('Add a task').first().press('Enter'));
    };
    await add('Choose the paper');
    await add('Send to the printer');
    await add('Pick them up');
    await reload();
    await tasksTab();
    const body = await text();
    must(['Choose the paper', 'Send to the printer', 'Pick them up'].every(s => body.includes(s)), 'added steps are missing after a reload');

    const row = name => page.locator('.ticket-task-row', { hasText: name }).first();
    const more = name => row(name).getByRole('button', { name: 'More' });

    // rename
    await more('Choose the paper').click();
    await row('Choose the paper').getByRole('button', { name: 'Rename' }).click();
    const d = page.locator('dialog[open]');
    await d.getByLabel('Task').fill('Choose the glossy paper');
    await act('check.edit', () => d.getByRole('button', { name: 'Save' }).click());
    await reload();
    await tasksTab();
    must((await text()).includes('Choose the glossy paper'), 'the new step name is gone after a reload');

    // move "Pick them up" up one place
    await more('Pick them up').click();
    await act('check.move', () => row('Pick them up').getByRole('button', { name: 'Move up' }).click());
    await reload();
    await tasksTab();
    const order = (await page.locator('.ticket-task-row h3').allInnerTexts()).map(s => s.trim());
    must(order.indexOf('Pick them up') < order.indexOf('Send to the printer') && order.indexOf('Pick them up') >= 0, 'the moved step is not above the other one after a reload: ' + order.join(' | '));

    // tick it
    await act('check.set', () => row('Choose the glossy paper').getByRole('checkbox').click());
    await reload();
    await tasksTab();
    must((await row('Choose the glossy paper').getByRole('checkbox').getAttribute('aria-checked')) === 'true', 'the ticked step is not ticked after a reload');

    // won't do with a reason, then open again
    await more('Send to the printer').click();
    await row('Send to the printer').getByPlaceholder('Reason (optional)').fill('We print at the office');
    await act('check.wont_do', () => row('Send to the printer').getByRole('button', { name: "Won't do" }).click());
    await reload();
    await tasksTab();
    must((await text()).includes('Skipped: We print at the office'), "the Won't do reason is not shown after a reload");
    await more('Send to the printer').click();
    await act('check.reopen', () => row('Send to the printer').locator('form button[type=submit]').click());
    await reload();
    await tasksTab();
    must(!(await text()).includes('Skipped: We print at the office'), 'the step is still skipped after Open again and a reload');

    // remove
    await more('Pick them up').click();
    await act('check.remove', () => row('Pick them up').getByRole('button', { name: 'Remove' }).click());
    await reload();
    await tasksTab();
    must(!(await text()).includes('Pick them up'), 'the removed step is back after a reload');
  },
};
