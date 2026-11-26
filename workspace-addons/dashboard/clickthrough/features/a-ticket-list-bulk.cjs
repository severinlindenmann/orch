// Tickets list: pick several (ORCH-2034). A person ticks two rows, the bar says "2 selected", Status > To do moves
// both, Priority > High sets both, Clear takes the bar away; after a reload both tickets still show what was set.
const idOf = out => (/\[(t_[A-Za-z0-9]+)\]/.exec(out) || [])[1];

module.exports = {
  name: 'Tickets list: pick several, set status and priority',
  covers: ['page:tickets', 'ticket.patch', 'ticket.edit'],
  async run({ page, open, reload, act, must, orch, until }) {
    const a = idOf(orch('ticket', 'new', 'Order the bulk napkins'));
    const b = idOf(orch('ticket', 'new', 'Order the bulk plates'));
    must(a && b, 'the seed tickets were not made');
    await open('#tickets');
    await until(s => [a, b].every(id => JSON.stringify(s.tickets || []).includes(id)), 'the new tickets');
    await open('#tickets');
    await page.getByRole('button', { name: 'List' }).first().click();  // an earlier click-through may have left the Board on

    await page.getByRole('checkbox', { name: 'Select Order the bulk napkins' }).check();
    await page.getByRole('checkbox', { name: 'Select Order the bulk plates' }).check();
    const bar = page.locator('[data-key="ticket-bulk"]');
    await bar.waitFor();
    must((await bar.innerText()).includes('2 selected'), 'the bar does not say 2 selected: ' + await bar.innerText());

    // Status: one click moves both; the bar stays for the next change
    await bar.locator('[data-key="bulk-status"] > summary').click();
    await act('ticket.patch', () => bar.locator('[data-key="bulk-status-ready"]').click());
    await page.waitForFunction(() => !document.querySelector('[data-key="ticket-bulk"][aria-busy]'), null, { timeout: 30000 });

    // Priority: same path as the ticket page (ticket.edit)
    await bar.locator('[data-key="bulk-priority"] > summary').click();
    await act('ticket.edit', () => bar.locator('[data-key="bulk-priority-high"]').click());
    await page.waitForFunction(() => !document.querySelector('[data-key="ticket-bulk"][aria-busy]'), null, { timeout: 30000 });

    await bar.getByRole('button', { name: 'Clear' }).click();
    must(!(await bar.count()), 'Clear does not take the bar away');

    await reload();
    for (const id of [a, b]) {
      const t = JSON.parse(orch('ticket', 'show', id, '--json'));
      must(t.status === 'ready', `${t.title} is ${t.status}, not To do`);
      must(t.priority === 'high', `${t.title} has priority ${t.priority}, not High`);
    }
  },
};
