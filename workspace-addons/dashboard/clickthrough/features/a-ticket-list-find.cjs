// Tickets list: find a ticket like a person (ORCH-891). Search by a word with an umlaut and by the ticket key, the search
// stays in the address and after a reload; a search with no hit says so and Show all clears it; a view chip; the
// Part of filter shows only an epic's tickets; the Board's Done row starts folded and opens and folds again.
const idOf = out => (/\[(t_[A-Za-z0-9]+)\]/.exec(out) || [])[1];

module.exports = {
  name: 'Tickets list: search, no hit, views, Part of, Board Show more',
  covers: ['page:tickets'],
  async run({ page, open, reload, must, text, orch, orchAsPerson, until }) {
    const complaint = idOf(orch('ticket', 'new', 'Answer the Müller complaint'));
    const domain = idOf(orch('ticket', 'new', 'Renew the shop domain'));
    const epic = idOf(orch('ticket', 'new', 'Spring fair', '--epic'));
    orch('ticket', 'new', 'Book the fair stand', '--parent', epic);
    orch('ticket', 'new', 'Order the fair banner', '--parent', epic);
    for (let i = 1; i <= 5; i++) orchAsPerson('ticket', 'status', idOf(orchAsPerson('ticket', 'new', 'Closed monthly report ' + i)), 'done');
    must(complaint && domain && epic, 'the seed tickets were not made');
    await open('#tickets');  // until() asks the page's server, so a page must be open
    await until(s => [complaint, domain, epic].every(id => JSON.stringify(s.tickets || []).includes(id)), 'the new tickets');
    const search = page.getByRole('searchbox', { name: 'Search tickets' });

    // a word with an umlaut, kept in the address and after a reload
    await open('#tickets');
    await page.getByRole('button', { name: 'List' }).first().click();  // an earlier click-through may have left the Board on
    await search.fill('müller');
    await page.waitForTimeout(300);
    must((await text()).includes('Answer the Müller complaint'), 'the search for müller does not find the ticket');
    must(!(await text()).includes('Renew the shop domain'), 'the search for müller still shows other tickets');
    must(/[?&]q=/.test(page.url()), 'the search is not in the address: ' + page.url());
    await reload();
    must((await search.inputValue()) === 'müller', 'the search is gone after a reload');
    must((await text()).includes('Answer the Müller complaint'), 'the search hit is gone after a reload');

    // the ticket key a person reads on a card
    const key = JSON.parse(orch('ticket', 'show', domain, '--json')).key;
    await search.fill(key);
    await page.waitForTimeout(300);
    must((await text()).includes('Renew the shop domain'), `the search for the key ${key} does not find its ticket`);

    // no hit: the empty state says so, Show all clears the search
    await search.fill('zzqqxx nothing like this');
    await page.waitForTimeout(300);
    must((await text()).includes('No tickets match'), 'a search with no hit does not say No tickets match');
    await page.getByRole('button', { name: 'Show all' }).click();
    await page.waitForTimeout(300);
    must((await search.inputValue()) === '', 'Show all does not clear the search');
    must((await text()).includes('Renew the shop domain'), 'Show all does not show every ticket again');

    // a view chip: Backlog shows only the tickets nobody started
    await page.locator('[data-key="view-chips"] a', { hasText: 'Backlog' }).click();
    await page.waitForTimeout(300);
    const groups = await page.locator('[data-key="ticket-table"] [data-key^="group-toggle-"]').evaluateAll(n => n.map(x => x.dataset.key));
    must(groups.length > 0 && groups.every(k => k === 'group-toggle-open'), 'the Backlog view shows other groups: ' + groups.join(', '));
    must((await text()).includes('Renew the shop domain'), 'the Backlog view does not show a ticket nobody started');
    await page.locator('[data-key="view-chips"] a', { hasText: 'All' }).first().click();
    await page.waitForTimeout(300);

    // Part of: only the epic's own tickets
    await open('#tickets');
    await page.locator('select').filter({ has: page.locator('option', { hasText: 'Any ticket' }) }).first().selectOption({ label: 'Spring fair' });
    await page.waitForTimeout(300);
    const part = await page.locator('[data-key="ticket-table"]').innerText();
    must(part.includes('Book the fair stand') && part.includes('Order the fair banner'), 'Part of does not show the epic\'s tickets');
    must(!part.includes('Renew the shop domain'), 'Part of still shows tickets of no epic');
    // back to every ticket (Part of is kept in the page, not in the address)
    await page.locator('select').filter({ has: page.locator('option', { hasText: 'Any ticket' }) }).first().selectOption({ label: 'Any ticket' });
    await page.waitForTimeout(300);

    // Board (status rows, ORCH-576): the Done row starts folded as "Show N"; one click shows its N tiles, Fold folds it
    await open('#tickets');
    await page.getByRole('button', { name: 'Board' }).first().click();
    await page.waitForTimeout(400);
    const lane = page.locator('section[data-status="done"]');
    const tiles = () => lane.locator('article.ticket-tile').count();
    const show = lane.locator('[data-action="board-open"]');
    must(await show.count(), 'the Done row has no Show button');
    const m = /^Show (\d+)$/.exec((await show.innerText()).trim());
    must(m, 'the Done row button says ' + await show.innerText());
    must(Number(m[1]) >= 5, 'the Done row counts ' + m[1] + ' tickets, not the five closed ones');
    must((await tiles()) === 0, 'the folded Done row already shows tiles: ' + await tiles());
    await show.click();
    await page.waitForTimeout(300);
    const shown = await tiles(), more = lane.locator('[data-action="board-more"]');
    must(shown === Number(m[1]) || (await more.count()), `Show ${m[1]} shows ${shown} tiles and no Show more`);
    const fold = lane.getByRole('button', { name: 'Fold' });
    must(await fold.count(), 'the open Done row has no Fold button');
    await fold.click();
    await page.waitForTimeout(300);
    must((await tiles()) === 0, 'Fold does not fold the Done row');
    await page.getByRole('button', { name: 'List' }).first().click();
  },
};
