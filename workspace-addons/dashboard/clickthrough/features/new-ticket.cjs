// New ticket from Home: write what needs doing, "Save without starting", reload, the ticket is in the list.
module.exports = {
  name: 'New ticket: save without starting',
  covers: ['ticket.new', 'page:home', 'page:tickets'],
  async run({ page, open, reload, act, must, text }) {
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
