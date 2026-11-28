// Review after the owner's walk of 28 Nov, in the real page on real ticket files:
// - O-05 / O-06: the list shows five compact rows and the count, "Next five" and "All" show the rest, a row opens its
//   card, and there is no Compare button and no tick;
// - W-003: the heading says the menu badge's number;
// - W-036 / O-04: the Reviewer's history is not on Waiting; Answered is one click away and comes back;
// - O-04 / W-042: at phone width the card comes first and the list after it in the same page;
// - W-039: Esc closes the ticket beside the card and the page stays where it was;
// - W-043: a paused automation is one line on top; "Turn on" turns it on again (orch resume) with one click.
module.exports = {
  name: 'Review: card first, five rows with Next five and All, no Compare, the paused line with Turn on',
  covers: ['automation.resume', 'page:review'],
  async run({page, open, reload, act, orch, orchAsPerson, python, until, must, shot}) {
    const made = [];
    for (let i = 1; i <= 8; i++) {
      const tid = python('import sys; from pathlib import Path; from orch import tickets; print(tickets.create(Path.cwd(), sys.argv[1], "agent:standin")["id"])', 'Walk ' + i + ': menu for week ' + i).trim();
      orch('check', 'add', tid, 'Write the menu');
      orch('check', 'done', tid, 'c1', '--note', 'Menu ' + i + ' written.');
      orch('ticket', 'summary', tid, 'Week ' + i + ' has six dishes with seasonal vegetables.');
      orch('ticket', 'status', tid, 'done');
      made.push(tid);
    }
    await open('#home');
    await until(s => made.every(id => (s.review?.cards || []).some(c => c.id === 'core:review:' + id)), 'eight results wait for review', 120);
    await open('#review');
    const side = page.locator('.review-side'), rows = side.locator('[data-review-row]');
    await rows.first().waitFor();
    const total = Number(await page.locator('[data-review-queue]').getAttribute('data-review-total'));
    must(total >= 8, 'the list counts every waiting card: ' + total);
    must(await rows.count() + await side.locator('[data-review-group]').count() === 5, 'five rows at first, not ' + (await rows.count()));
    must((await side.locator('.review-list-head').innerText()).includes(total + ' waiting'), 'the list head says how many wait');
    must(await page.getByRole('button', {name:/^Compare$/}).count() === 0 && await page.locator('.review-tick-box').count() === 0, 'no Compare button and no ticks');
    // W-003: one number in the menu badge and the heading
    const nums = await page.evaluate(() => ({
      badge: Number(document.querySelector('.sidebar a[href="#review"] .count')?.textContent || 0),
      line: Number((/(\d+) things? needs? you/.exec(document.querySelector('main [data-key="heading"]')?.innerText || '') || [])[1] || 0)}));
    must(nums.badge > 0 && nums.badge === nums.line, 'the heading says ' + nums.line + ', the menu badge ' + nums.badge);
    // W-036: the card and its buttons are on screen without scrolling, and the Reviewer's history is not on Waiting
    must(await page.locator('[data-key="review-accepted"]').count() === 0, "the Reviewer's history is on Waiting");
    const bar = await page.locator('.swipe-actions').first().boundingBox();
    must(bar && bar.y + bar.height <= page.viewportSize().height, 'the answer buttons are below the window: ' + JSON.stringify(bar));
    await shot('five-rows');
    // Next five, All, First five
    await side.getByRole('button', {name:'Next five'}).click();
    must(await rows.count() + await side.locator('[data-review-group]').count() === Math.min(10, await page.evaluate(() => document.querySelectorAll('.review-side [data-review-row],.review-side [data-review-group]').length)), 'Next five adds five');
    must(await rows.count() > 5, 'Next five shows more rows');
    if (await side.getByRole('button', {name:/^All /}).count()) await side.getByRole('button', {name:/^All /}).click();
    must(await side.getByRole('button', {name:'Next five'}).count() === 0, 'All shows every row');
    // a row opens its card
    await side.locator('[data-review-row]', {hasText:'Week 7'}).first().click();
    await page.locator('.swipe-card:not(.under):not(.under2)', {hasText:'Week 7'}).first().waitFor();
    must((await side.locator('[data-review-row][aria-current="true"]').innerText()).includes('Week 7'), 'the row of the card on screen is marked');
    await side.getByRole('button', {name:'First five'}).click();
    must(await rows.count() + await side.locator('[data-review-group]').count() === 5, 'First five folds the list again');
    // W-003: answer one card: the menu badge, the heading, the Waiting tab and the list drop together at once (the
    // answer itself is saved after the Undo time); Undo brings all four back
    const numbers = () => page.evaluate(() => ({
      badge: Number(document.querySelector('.sidebar a[href="#review"] .count')?.textContent || 0),
      line: Number((/(\d+) things? needs? you/.exec(document.querySelector('main [data-key="heading"]')?.innerText || '') || [])[1] || 0),
      tab: Number(document.querySelector('[data-review-nav] button[data-show="deck"] .meta')?.textContent || 0),
      list: Number(document.querySelector('[data-review-queue]')?.dataset.reviewTotal || 0)}));
    const n0 = await numbers();
    await side.locator('[data-review-row]', {hasText:'Week 2'}).first().click();
    await page.locator('.swipe-card:not(.under):not(.under2)', {hasText:'Week 2'}).first().waitFor();
    await page.locator('.swipe-actions').getByRole('button', {name:/Looks good/}).first().click();
    await page.waitForFunction(n => Number(document.querySelector('.sidebar a[href="#review"] .count')?.textContent || 0) === n, n0.badge - 1, {timeout: 3000});
    const n1 = await numbers();
    must(n1.line === n1.badge && n1.tab === n0.tab - 1 && n1.list === n0.list - 1, 'the numbers did not drop together: ' + JSON.stringify([n0, n1]));
    await page.locator('.swipe-top').getByRole('button', {name:/Undo/}).click();
    await page.waitForFunction(n => Number(document.querySelector('.sidebar a[href="#review"] .count')?.textContent || 0) === n, n0.badge, {timeout: 20000});
    const n2 = await numbers();
    must(JSON.stringify(n2) === JSON.stringify(n0), 'Undo did not bring every number back: ' + JSON.stringify([n0, n2]));
    // Answered and back
    await page.locator('[data-review-nav] button[data-show="answered"]').click();
    await page.locator('#answered:not([hidden])').waitFor();
    must(await page.locator('[data-key="review-extra"]').count() === 0, 'Waiting rows show on Answered');
    await shot('answered');
    await page.locator('[data-review-nav] button[data-show="deck"]').click();
    await page.locator('#deck:not([hidden])').waitFor();

    // W-039: Open ticket, then Esc: the panel closes, the card is the same, the page did not scroll
    const card = page.locator('.swipe-card:not(.under):not(.under2)').first();
    const title = (await card.locator('h3, .swipe-lead').first().innerText()).trim();
    await page.evaluate(() => window.scrollTo(0, 60));
    const y0 = await page.evaluate(() => window.scrollY);
    const link = card.getByRole('link', {name:/^Open ticket/});
    if (!(await link.isVisible())) await card.locator('.swipe-more summary').click();
    await link.click();
    await page.locator('.review-ticket').waitFor();
    await page.waitForTimeout(300);
    must(Math.abs(await page.evaluate(() => window.scrollY) - y0) <= 2, 'opening the ticket scrolled the page');
    must(await page.locator('[data-key="review-main"] > :first-child').getAttribute('data-key') === 'review-nav', 'something was pushed in above the card');
    await page.keyboard.press('Escape');
    await page.locator('.review-ticket').waitFor({state:'detached'});
    await page.waitForTimeout(300);
    must(Math.abs(await page.evaluate(() => window.scrollY) - y0) <= 2, 'closing the ticket scrolled the page');
    must((await page.locator('.swipe-card:not(.under):not(.under2)').first().innerText()).includes(title), 'the same card after Esc');
    must(await side.isVisible(), 'the list is back');

    // O-04 / W-042: a phone: one column, the card first, the list after it in the same page
    const size = page.viewportSize();
    await page.setViewportSize({width:390, height:844});
    const next = page.locator('[data-review-next]');
    await next.locator('[data-review-row]').first().waitFor();
    must(await page.locator('.review-side.card.review-side[data-key="review-side"]').count() === 0, 'the aside is still drawn on a phone');
    const order = await page.evaluate(() => {
      const deck = document.querySelector('#deck').getBoundingClientRect(), list = document.querySelector('[data-review-next]').getBoundingClientRect();
      return {deck: deck.top, list: list.top, wide: document.documentElement.scrollWidth - document.documentElement.clientWidth};
    });
    must(order.deck < order.list, 'the list is not after the card: ' + JSON.stringify(order));
    must(order.wide <= 1, 'the page scrolls sideways at 390 px by ' + order.wide);
    must(await next.locator('[data-review-row]').count() + await next.locator('[data-review-group]').count() === 5, 'five rows on a phone too');
    await shot('phone');
    await page.setViewportSize(size);
    await side.locator('[data-review-row]').first().waitFor();

    // O-04: beside the Focus panel the shell marks a tight page area (data-live-narrow): the list moves after the card
    // without a reload, and back beside it when the mark goes
    await page.evaluate(() => { document.body.dataset.liveNarrow = ''; });
    await next.locator('[data-review-row]').first().waitFor();
    must(await page.evaluate(() => document.querySelector('#deck').getBoundingClientRect().top < document.querySelector('[data-review-next]').getBoundingClientRect().top), 'beside the panel the list is not after the card');
    await shot('beside-panel');
    await page.evaluate(() => { delete document.body.dataset.liveNarrow; });
    await side.locator('[data-review-row]').first().waitFor();
    must(await page.locator('[data-review-next]').count() === 0, 'two lists on a wide page');

    // W-043: paused: one line on top; Turn on is one click
    orchAsPerson('pause', '--reason', 'Disk almost full');
    await reload();
    const line = page.locator('[data-key="review-paused"]');
    await line.waitFor();
    const words = await line.innerText();
    must(words.includes('Automation is paused: Disk almost full.') && !/orch resume/.test(words), 'the paused line: ' + words);
    must(await page.evaluate(() => { const l = document.querySelector('[data-key="review-paused"]'), m = document.querySelector('[data-key="review-layout"]'); return l.getBoundingClientRect().bottom <= m.getBoundingClientRect().top; }), 'the line is not on top');
    await shot('paused');
    await act('automation.resume', () => line.getByRole('button', {name:'Turn on'}).click());
    await line.waitFor({state:'detached'});
    must(JSON.parse(orchAsPerson('resume', '--json')).was_paused === false, 'automation is still paused after Turn on');
    await reload();
    must(await page.locator('[data-key="review-paused"]').count() === 0, 'the paused line is back after a reload');
  },
};
