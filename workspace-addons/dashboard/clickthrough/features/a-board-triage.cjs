// A person puts a card one place lower in the Backlog column of the board, and starts a triage of the Backlog:
// after a reload the order is kept; Start triage opens the new Triage ticket, which is still there after a reload.
module.exports = {
  name: 'Tickets: reorder a board card, start triage',
  covers: ['ticket.order', 'triage.start', 'page:tickets'],
  async run({ page, open, reload, act, must, text }) {
    await open('#tickets');
    await page.getByRole('button', { name: 'Board' }).click();
    const firstCard = () => page.locator('summary[aria-label$="to another column"]').first();
    const before = await firstCard().getAttribute('aria-label');
    await firstCard().click();
    await act('ticket.order', () => page.getByRole('menuitem', { name: 'Move down' }).first().click());
    await reload();
    await page.getByRole('button', { name: 'Board' }).click();
    must(await firstCard().getAttribute('aria-label') !== before, 'the card is back in its old place after a reload');

    await open('#tickets');
    await page.locator('summary', { hasText: 'Triage' }).click();
    await page.locator('[data-key=triage-lane-needs-you]').uncheck();
    await act('triage.start', () => page.locator('[data-key=triage-start]').click());
    // ORCH-1096: the new Triage ticket opens at once (its helper starts there), not after the helper has started
    await page.waitForFunction(() => location.hash.startsWith('#ticket/'), null, { timeout: 10000 }).catch(() => {});
    must((await page.evaluate(() => location.hash)).startsWith('#ticket/'), 'Start triage did not open the new Triage ticket');
    await open('#tickets');
    must(/Triage \d+ \w+/.test(await text()), 'no Triage ticket on the board after a reload');
  },
};
