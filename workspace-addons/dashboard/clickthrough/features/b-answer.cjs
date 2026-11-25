// Review page: a ticket in Check is answered "Looks good" (it becomes Done). Then the open question on a ticket
// ("Which restaurant?") is answered on the ticket page. Both survive a reload.
module.exports = {
  name: 'Review page and answering a question',
  covers: ['page:review', 'review.answer', 'answer', 'ticket.patch'],
  async run({ page, ids, open, reload, act, must, text }) {
    // a ticket of our own in Check, so the seeded ones stay as they are
    await open('#home');
    await page.getByRole('button', { name: 'New ticket' }).first().click();
    const dlg = page.locator('.new-ticket-page');  // the New ticket page (ORCH-1037)
    await dlg.getByPlaceholder(/What should the helper do/).fill('Review walk: choose the song');
    await act('ticket.new', () => dlg.getByRole('button', { name: 'Save ticket' }).click());
    await page.waitForFunction(() => location.hash.startsWith('#ticket/'), null, { timeout: 15000 });  // the saving moment, then the new ticket
    await open('#tickets');
    await page.getByRole('link', { name: /Review walk: choose the song/ }).first().click();
    await page.waitForFunction(() => /^#ticket\//.test(location.hash));
    const hash = await page.evaluate(() => location.hash);
    await page.locator('summary[aria-label="More ticket actions"]').click();
    await act('ticket.patch', () => page.getByRole('menuitem', { name: 'Check' }).click());

    await open('#review');
    await page.getByRole('button', { name: 'Later' }).click();  // the question card comes first; this is the Check card
    await page.getByText('The helper says this is ready for your check.').waitFor();
    await act('review.answer', () => page.getByRole('button', { name: 'Looks good' }).click());
    await open(hash);
    must(/Done/.test(await page.locator('main').innerText()), 'the ticket is not Done after "Looks good" and a reload');
    await reload();
    must(/Done/.test(await page.locator('main').innerText()), 'the ticket is not Done after a reload');

    // the seeded open question, answered on its ticket
    await open('#ticket/' + ids.lunch);
    const q = page.locator('[data-question]').first();
    await q.getByText('Seehaus').first().click();
    await act('answer', async () => {
      const send = q.getByRole('button', { name: /^(Send|Answer|Confirm|Use)/ });
      if (await send.count()) await send.first().click();
    });
    await reload();
    must(!(await page.locator('[data-question]').count()), 'the question is still open after a reload');
    must((await text()).includes('Seehaus'), 'the answer "Seehaus" is not on the ticket after a reload');
    await open('#review');
  },
};
