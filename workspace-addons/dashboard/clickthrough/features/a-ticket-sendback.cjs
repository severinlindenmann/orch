// A person makes a ticket, moves it to Review, then under the result presses Send back, adds a text file and a few
// words and sends: the file is on the ticket, the ticket is back with the helper, and it stays so after a reload.
// (O-07, owner 28 Nov: the Overview has no write box of its own; Send back opens its box under the result.)
module.exports = {
  name: 'Ticket page: add a file and send back from Check',
  covers: ['ticket.attach', 'ticket.changes', 'ticket.patch', 'page:ticket'],
  async run({ page, open, reload, act, must, seen }) {
    await open('#home');
    await page.getByRole('button', { name: 'New ticket' }).first().click();
    const dlg = page.locator('.new-ticket-page');  // the New ticket page (ORCH-1037)
    await dlg.getByPlaceholder(/What should the helper do/).fill('Collect the allergy list');
    await act('ticket.new', () => dlg.getByRole('button', { name: 'Save ticket' }).click());
    await page.waitForFunction(() => location.hash.startsWith('#ticket/'), null, { timeout: 15000 });  // the saving moment, then the new ticket
    await open('#tickets');
    await page.getByText('Collect the allergy list').first().click();
    await page.getByRole('button', { name: 'Change title' }).waitFor();

    await page.locator('summary[data-key^="ticket-actions-"]').click();
    await act('ticket.patch', () => page.getByRole('menuitemradio', { name: 'Review', exact: true }).click());
    const card = page.locator('[data-key^="review-card-"]');
    await card.getByRole('button', { name: 'Send back', exact: true }).click();
    const box = card.locator('[id^="ticket-changes-box-"]');
    await box.getByPlaceholder('Write, paste a picture or record').waitFor();

    await box.locator('input[type=file]').first().setInputFiles({ name: 'allergies.txt', mimeType: 'text/plain', buffer: Buffer.from('Nuts: Jonas\nGluten: Mira\n') });
    await box.getByPlaceholder('Write, paste a picture or record').fill('Please add the new names from the file.');
    // the file goes on the ticket first, then the words are sent back: wait for both before the reload
    await act('ticket.changes', () => act('ticket.attach', () => box.getByRole('button', { name: 'Send back', exact: true }).click()));

    await reload();
    const t = await seen(['allergies.txt', 'Text file', 'Please add the new names']);
    must(t.includes('allergies.txt') && t.includes('Text file'), 'the added file is not on the ticket after a reload');
    must(t.includes('Please add the new names'), 'the note that was sent back is not on the ticket after a reload');
    must(!(await page.locator('[data-key^="review-card-"]').count()), 'the ticket is still in Review after it was sent back');
  },
};
