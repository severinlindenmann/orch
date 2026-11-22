// A person puts a tile one place lower in the Backlog row of the board (ORCH-576: status rows), and starts a triage of the Backlog:
// after a reload the order is kept, and a Triage ticket exists.
module.exports = {
  name: 'Tickets: reorder a board card, start triage',
  covers: ['ticket.order', 'triage.start', 'page:tickets'],
  async run({ page, open, reload, act, must, text }) {
    await open('#tickets');
    await page.getByRole('button', { name: 'Board', exact: true }).click();
    const firstCard = () => page.locator('.status-row[data-status=open] summary[aria-label$="to another column"]').first();
    const before = await firstCard().getAttribute('aria-label');
    await firstCard().click();
    await act('ticket.order', () => page.locator('.status-row[data-status=open] details[open]').getByRole('menuitem', { name: 'Move down' }).click());
    await reload();
    await page.getByRole('button', { name: 'Board', exact: true }).click();
    must(await firstCard().getAttribute('aria-label') !== before, 'the card is back in its old place after a reload');

    await open('#tickets');
    await page.locator('summary', { hasText: 'Triage' }).click();
    await page.locator('[data-key=triage-lane-needs-you]').uncheck();
    await act('triage.start', () => page.locator('[data-key=triage-start]').click());
    await open('#tickets');
    must(/Triage \d+ \w+/.test(await text()), 'no Triage ticket on the board after a reload');
  },
};
