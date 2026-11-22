// Tickets calendar (ORCH-1081, owner picked draft C): switch to Calendar, a ticket due today sits on today, a ticket past
// due sits in the Late list, a ticket with no due date is counted below; Calendar and Week stay after a reload; Show
// them in the list goes back to the list.
const idOf = out => (/\[(t_[A-Za-z0-9]+)\]/.exec(out) || [])[1];
const key = d => [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');

module.exports = {
  name: 'Tickets calendar: due today on its day, late in the Late list, Week, reload',
  covers: ['page:tickets'],
  async run({ page, open, reload, must, text, orch, until }) {
    const now = new Date(), past = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 3, 12);
    const today = idOf(orch('ticket', 'new', 'Call the bakery about the cake', '--due', key(now)));
    const late = idOf(orch('ticket', 'new', 'Send the quote to the printer', '--due', key(past)));
    const none = idOf(orch('ticket', 'new', 'Tidy the stock room'));
    must(today && late && none, 'the seed tickets were not made');
    await open('#tickets');
    await until(s => [today, late, none].every(id => JSON.stringify(s.tickets || []).includes(id)), 'the new tickets');

    await page.getByRole('button', { name: 'Calendar', exact: true }).click();
    await page.waitForTimeout(300);
    must(/[?&]layout=calendar/.test(page.url()), 'Calendar is not in the address: ' + page.url());
    // Month shows Sat and Sun in one Weekend cell keyed by its Saturday: on a Sunday, today sits in Saturday's cell
    const cellDay = now.getDay() === 0 ? new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1) : now;
    const todayCell = page.locator(`[data-key="cal-cell-${key(cellDay)}"], [data-key="cal-day-${key(now)}"]`).first();
    must(await todayCell.count(), 'no cell for today on the calendar');
    must((await todayCell.innerText()).includes('Call the bakery about the cake'), 'the ticket due today is not on today');
    const lane = page.locator('[data-key="cal-lane"]');
    must((await lane.innerText()).includes('Send the quote to the printer'), 'the late ticket is not in the Late list');
    must(!(await todayCell.innerText()).includes('Send the quote to the printer'), 'the late ticket is on today');
    must(/tickets? (has|have) no due date/.test(await text()), 'the line about tickets with no due date is missing');

    // Week, kept after a reload
    await page.getByRole('button', { name: 'Week', exact: true }).click();
    await page.waitForTimeout(300);
    must(/[?&]cal=week/.test(page.url()), 'Week is not in the address: ' + page.url());
    await reload();
    must((await page.getByRole('button', { name: 'Week', exact: true }).getAttribute('aria-pressed')) === 'true', 'Week is gone after a reload');
    must((await text()).includes('Call the bakery about the cake'), 'the ticket due today is gone from the week after a reload');

    // back to the list, so later click-throughs start from the list
    await page.getByRole('button', { name: 'Month', exact: true }).click();
    await page.getByRole('button', { name: 'Show them in the list' }).click();
    await page.waitForTimeout(300);
    must(!/[?&]layout=/.test(page.url()), 'Show them in the list did not go back to the list: ' + page.url());
    must((await text()).includes('Tidy the stock room'), 'the list does not show the ticket with no due date');
  },
};
