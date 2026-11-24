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
    // ORCH-1852: Save ticket sits beside the request (right under it on a phone), in the first screen, with the line that says what Start now costs
    const box = await form.getByPlaceholder(/What should the helper do/).boundingBox();
    const save = await form.getByRole('button', { name: 'Save ticket' }).boundingBox();
    must(save.y < page.viewportSize().height && save.y + save.height >= box.y + box.height && save.y - (box.y + box.height) < 24, 'Save ticket is not beside or right under the request');
    must((await text()).includes('This uses its time and may cost money'), 'the page does not say what Start now costs');
    await act('ticket.new', () => form.getByRole('button', { name: 'Save ticket' }).click());
    await page.waitForFunction(() => location.hash.startsWith('#ticket/'), null, { timeout: 15000 });
    must((await text()).includes('Order the cake for Friday'), 'the new ticket page did not open after saving');
    await open('#tickets');
    await reload();
    must((await text()).includes('Order the cake for Friday'), 'the new ticket is not in the list after a reload');
  },
};
