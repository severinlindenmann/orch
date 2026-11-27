// New ticket from Home: the New ticket page (#new, ORCH-1037), write what needs doing, "Save ticket", the
// short saving moment, then the new ticket's page; reload, the ticket is in the list.
module.exports = {
  name: 'New ticket: save without starting',
  covers: ['ticket.new', 'page:home', 'page:new', 'page:tickets'],
  async run({ page, open, reload, act, must, text }) {
    await open('#home');
    await page.getByRole('button', { name: 'New ticket' }).first().click();
    await page.waitForFunction(() => location.hash === '#new');
    await reload();  // the address alone opens the page too
    const form = page.locator('.new-ticket-page');
    await form.getByPlaceholder(/What should the helper do/).fill('Order the cake for Friday');
    // ORCH-2162 option A: Save ticket sits under the request in its column, in the first screen, with Start now beside it
    // and the line that says what Start now costs
    const box = await form.getByPlaceholder(/What should the helper do/).boundingBox();
    const save = await form.getByRole('button', { name: 'Save ticket' }).boundingBox();
    const start = await form.getByRole('button', { name: 'Start now' }).boundingBox();
    const under = save.y >= box.y + box.height && save.x < box.x + box.width;
    must(save.y + save.height <= page.viewportSize().height && under, 'Save ticket is not under the request in the first screen');
    must(Math.abs(start.y - save.y) < 8 && start.x > save.x, 'Start now is not beside Save ticket');
    must((await text()).includes('This may cost money'), 'the page does not say what Start now costs');
    await act('ticket.new', () => form.getByRole('button', { name: 'Save ticket' }).click());
    await page.waitForFunction(() => location.hash.startsWith('#ticket/'), null, { timeout: 15000 });
    must((await text()).includes('Order the cake for Friday'), 'the new ticket page did not open after saving');
    await open('#tickets');
    await reload();
    must((await text()).includes('Order the cake for Friday'), 'the new ticket is not in the list after a reload');
  },
};
