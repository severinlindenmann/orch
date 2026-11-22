// A person makes a ticket, moves it to Check, then on its page adds a text file and a few words and presses
// "Send back with this": the file is on the ticket, the ticket is back with the helper, and it stays so after a reload.
module.exports = {
  name: 'Ticket page: add a file and send back from Check',
  covers: ['ticket.attach', 'ticket.changes', 'ticket.patch', 'page:ticket'],
  async run({ page, open, reload, act, must, text }) {
    await open('#home');
    await page.getByRole('button', { name: 'New ticket' }).first().click();
    const dlg = page.locator('.new-ticket-page');  // the New ticket page (ORCH-1037)
    await dlg.getByPlaceholder(/What should the helper do/).fill('Collect the allergy list');
    await act('ticket.new', () => dlg.getByRole('button', { name: 'Save without starting' }).click());
    await page.waitForFunction(() => location.hash.startsWith('#ticket/'), null, { timeout: 15000 });  // the saving moment, then the new ticket
    await open('#tickets');
    await page.getByText('Collect the allergy list').first().click();
    await page.getByRole('button', { name: 'Change title' }).waitFor();

    await page.getByLabel('More ticket actions').click();
    await act('ticket.patch', () => page.getByRole('menuitem', { name: 'Check', exact: true }).click());
    // the box is one line until it is selected (ORCH-777): click into it, then Send back shows
    await page.getByPlaceholder(/Write what is new/).last().click();
    await page.getByRole('button', { name: 'Send back with this' }).waitFor();

    await page.locator('input[type=file]').first().setInputFiles({ name: 'allergies.txt', mimeType: 'text/plain', buffer: Buffer.from('Nuts: Jonas\nGluten: Mira\n') });
    await page.getByLabel('Add to this ticket').last().fill('Please add the new names from the file.');
    // the file goes on the ticket first, then the words are sent back: wait for both before the reload
    await act('ticket.changes', () => act('ticket.attach', () => page.getByRole('button', { name: 'Send back with this' }).click()));

    await reload();
    const t = await text();
    must(t.includes('allergies.txt') && t.includes('Text file'), 'the added file is not on the ticket after a reload');
    must(t.includes('Please add the new names'), 'the note that was sent back is not on the ticket after a reload');
    must(!(await page.getByRole('button', { name: 'Send back with this' }).count()), 'the ticket is still in Check after it was sent back');
  },
};
