// ORCH-420 follow-up: on Review, Send back on a Check result with a picture goes through. Before, the picture landed in
// the ticket's files first, the card's own file list changed, and the answer was refused as "This card changed". Now
// feedback files go in the ticket's feedback folder, the card stays the same, and the ticket is back with its helper.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=', 'base64');
module.exports = {
  name: 'Send back a Check result on Review with a picture',
  covers: ['review.answer', 'ticket.attach', 'page:review'],
  async run({ page, open, reload, act, must, text }) {
    const title = 'Check the poster colours';
    await open('#home');
    await page.getByRole('button', { name: 'New ticket' }).first().click();
    const dlg = page.locator('.new-ticket-page');  // the New ticket page (ORCH-1037)
    await dlg.getByPlaceholder(/What should the helper do/).fill(title);
    await act('ticket.new', () => dlg.getByRole('button', { name: 'Save ticket' }).click());
    await page.waitForFunction(() => location.hash.startsWith('#ticket/'), null, { timeout: 15000 });  // the saving moment, then the new ticket
    await open('#tickets');
    await page.getByText(title).first().click();
    await page.getByRole('button', { name: 'Change title' }).waitFor();
    await page.getByLabel('More ticket actions').click();
    await act('ticket.patch', () => page.getByRole('menuitem', { name: 'Check', exact: true }).click());
    const tid = decodeURIComponent(/#ticket\/([^/?&]+)/.exec(page.url())[1]);
    await open('#review?card=' + encodeURIComponent('core:review:' + tid));
    await page.locator('.swipe-card', { hasText: title }).first().waitFor();
    await page.getByRole('button', { name: /^Send back/ }).first().click();
    const sheet = page.locator('.swipe-sheet');
    await sheet.waitFor();
    await sheet.getByLabel('What should change').fill('The red is too strong, see my picture.');
    await sheet.locator('input[type=file]').setInputFiles({ name: 'poster-note.png', mimeType: 'image/png', buffer: PNG });
    await sheet.locator('.attachment-tile', { hasText: 'poster-note.png' }).waitFor();
    // the answer is held 6 s for Undo, then the picture is kept and the answer saved; a refused answer (the old
    // "This card changed") fails here
    await act('review.answer', () => sheet.getByRole('button', { name: /^Send back/ }).last().click());
    must(!/This card changed/.test(await text()), 'the answer was refused as "This card changed"');
    await open('#ticket/' + tid);
    await reload();
    const t = await text();
    must(t.includes('poster-note.png'), 'the picture is not on the ticket');
    must(t.includes('The red is too strong'), 'the words are not on the ticket');
    must(!(await page.getByRole('button', { name: 'Looks good' }).count()), 'the ticket is still in Check: the Send back did not land');
  },
};
