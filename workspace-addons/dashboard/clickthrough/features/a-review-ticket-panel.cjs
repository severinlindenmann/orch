// ORCH-1804 (draft): "Open ticket" on a Review card shows that ticket beside the deck; Review stays where it is
// (the same card, its words box untouched), Close hides the panel again and a reload keeps it open or closed.
module.exports = {
  name: 'Review: Open ticket shows the card\'s ticket beside the deck',
  covers: ['page:review'],
  async run({page, open, orch, python, until, must, shot}) {
    const tid = python('from pathlib import Path; from orch import tickets; print(tickets.create(Path.cwd(), "Plan the spring menu", "agent:standin")["id"])').trim();
    orch('check', 'add', tid, 'Write the menu');
    orch('check', 'done', tid, 'c1', '--note', 'Menu written in menu.md.');
    orch('ticket', 'summary', tid, 'Six dishes with spring vegetables, two of them vegan.');
    orch('ticket', 'status', tid, 'done');
    await open('#home');
    await until(s => (s.review?.cards || []).some(c => c.id === 'core:review:' + tid), 'menu ready for review');
    await open('#review?card=' + encodeURIComponent('core:review:' + tid));
    const card = page.locator('.swipe-card:not(.under):not(.under2)', {hasText:'Six dishes with spring vegetables'}).first();
    await card.waitFor();
    const host = await page.locator('[data-review-host]').elementHandle();
    await card.getByRole('link', {name:/^Open ticket/}).click();
    const panel = page.locator('.review-ticket');
    await panel.waitFor();
    must(page.url().includes('ticket=' + tid), 'the address names the ticket: ' + page.url());
    await panel.getByText('Six dishes with spring vegetables').first().waitFor();  // the ticket page's own handover
    must(await host.evaluate(n => n.isConnected), 'the deck was not drawn again');
    must(await card.isVisible(), 'the card stays on screen beside the ticket');
    must(!(await page.locator('.review-side').isVisible()), 'the ticket takes the place of All cards');
    must(await page.locator('h1:not([aria-level="2"])').count() === 1, 'one level-1 heading: the ticket title reads as level 2');
    await shot('open');
    await page.reload();
    await page.locator('.review-ticket').waitFor();
    await page.locator('.review-ticket').getByRole('link', {name:'Close ticket'}).click();
    await page.locator('.review-ticket').waitFor({state:'detached'});
    must(await page.locator('.review-side').isVisible(), 'All cards is back');
    must(await page.locator('.swipe-card:not(.under):not(.under2)', {hasText:'Six dishes with spring vegetables'}).first().isVisible(), 'the same card');
  },
};
