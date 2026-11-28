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
    try { await walk(); } finally { tidy(); }
    // the tickets made here are closed again, so later click-throughs find the lists they expect
    function tidy() { for (const tid of made) { try { orchAsPerson('ticket', 'status', tid, 'dropped'); } catch (e) { /* already closed */ } } }
    async function walk() {
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
    // W-036 (wide): the list stands on the left, and the keyboard still reaches the card before it
    const wideOrder = await page.evaluate(() => {
      const stops = [...document.querySelectorAll('[data-key="review-layout"] :is(button,a[href],summary,[tabindex="0"])')].filter(n => n.offsetParent && !n.disabled).map(n => n.closest('.review-side') ? 'list' : n.closest('[data-review-nav]') ? 'switch' : n.closest('#deck') ? 'card' : 'other');
      return {first: stops[0], card: stops.indexOf('card'), list: stops.indexOf('list'), sideRight: document.querySelector('.review-side').getBoundingClientRect().right, cardLeft: document.querySelector('.swipe-card:not(.under):not(.under2)').getBoundingClientRect().left};
    });
    must(wideOrder.first === 'switch' && wideOrder.card > 0 && wideOrder.card < wideOrder.list, 'wide: the keyboard meets the list before the card: ' + JSON.stringify(wideOrder));
    must(wideOrder.sideRight <= wideOrder.cardLeft, 'wide: the list is not left of the card: ' + JSON.stringify(wideOrder));
    // W-038: before the first answer there is no progress row (no "0 answered", no bar, no greyed-out Undo)
    must(!(await page.locator('.swipe-top').first().isVisible()), 'the progress row shows before the first answer');
    await shot('five-rows');
    // Next five shows the next five (the list never grows), All every row, First five the start again
    const shownRows = () => page.evaluate(() => [...document.querySelectorAll('.review-side [data-review-row],.review-side [data-review-group]')].map(n => n.innerText.replace(/\s+/g, ' ').trim()));
    const page1 = await shownRows();
    await side.getByRole('button', {name:'Next five'}).click();
    const page2 = await shownRows();
    must(page2.length >= 1 && page2.length <= 5 && !page2.some(r => page1.includes(r)), 'Next five does not show the next rows: ' + JSON.stringify([page1, page2]));
    must((await side.locator('[data-review-where]').innerText()).startsWith('Rows 6 to '), 'the list does not say which rows it shows');
    await side.getByRole('button', {name:/^All /}).click();
    must((await shownRows()).length === (await page.evaluate(() => document.querySelectorAll('.review-side [data-review-row],.review-side [data-review-group]').length)) && (await shownRows()).length > 5, 'All shows every row');
    must(await side.getByRole('button', {name:'Next five'}).count() === 0, 'Next five beside All rows');
    // a row opens its card
    await side.locator('[data-review-row]', {hasText:'Week 7'}).first().click();
    await page.locator('.swipe-card:not(.under):not(.under2)', {hasText:'Week 7'}).first().waitFor();
    must((await side.locator('[data-review-row][aria-current="true"]').innerText()).includes('Week 7'), 'the row of the card on screen is marked');
    await side.getByRole('button', {name:'First five'}).click();
    must(JSON.stringify(await shownRows()) === JSON.stringify(page1), 'First five does not show the first rows again');
    // W-003: answer one card: the menu badge, the heading, the Waiting tab and the list drop together at once (the
    // answer itself is saved after the Undo time); Undo brings all four back
    const numbers = () => page.evaluate(() => ({
      badge: Number(document.querySelector('.sidebar a[href="#review"] .count')?.textContent || 0),
      line: Number((/(\d+) things? needs? you/.exec(document.querySelector('main [data-key="heading"]')?.innerText || '') || [])[1] || 0),
      tab: Number(document.querySelector('[data-review-nav] button[data-show="deck"] .meta')?.textContent || 0),
      list: Number(document.querySelector('[data-review-queue]')?.dataset.reviewTotal || 0)}));
    const n0 = await numbers();
    await side.getByRole('button', {name:/^All /}).click();
    await side.locator('[data-review-row]', {hasText:'Week 2'}).first().click();
    await page.locator('.swipe-card:not(.under):not(.under2)', {hasText:'Week 2'}).first().waitFor();
    await page.locator('.swipe-actions').getByRole('button', {name:/Looks good/}).first().click();
    await page.waitForFunction(n => Number(document.querySelector('.sidebar a[href="#review"] .count')?.textContent || 0) === n, n0.badge - 1, {timeout: 3000});
    const n1 = await numbers();
    // W-038: the first answer brings the progress row; FX-06: it, the card and the answer bar end on one line
    await page.locator('.swipe-top').first().waitFor();
    must(/^1 answered · /.test(await page.locator('.swipe-top span').first().innerText()), 'the progress row does not count the first answer');
    const edges = await page.evaluate(() => { const r = q => Math.round(document.querySelector(q).getBoundingClientRect().right); return {top: r('.swipe-top'), card: r('.swipe-card:not(.under):not(.under2)'), acts: r('.swipe-actions'), nav: r('[data-review-nav]')}; });
    must(Math.abs(edges.top - edges.card) <= 1 && Math.abs(edges.acts - edges.card) <= 1 && Math.abs(edges.nav - edges.card) <= 1, 'three right edges: ' + JSON.stringify(edges));
    await shot('first-answer');
    must(n1.line === n1.badge && n1.tab === n0.tab - 1 && n1.list === n0.list - 1, 'the numbers did not drop together: ' + JSON.stringify([n0, n1]));
    await page.locator('.swipe-top').getByRole('button', {name:/Undo/}).click();
    await page.waitForFunction(n => Number(document.querySelector('.sidebar a[href="#review"] .count')?.textContent || 0) === n, n0.badge, {timeout: 20000});
    const n2 = await numbers();
    must(JSON.stringify(n2) === JSON.stringify(n0), 'Undo did not bring every number back: ' + JSON.stringify([n0, n2]));
    await side.getByRole('button', {name:'First five'}).click();
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
    // W-042 A: the phone card reads the question, the evidence, the explanation with its links, then the answers
    const read = await page.evaluate(() => {
      const c = document.querySelector('.swipe-card:not(.under):not(.under2)'), t = q => { const n = c.querySelector(q); return n && n.offsetParent ? Math.round(n.getBoundingClientRect().top + scrollY) : null; };
      return {head: t('.swipe-head'), preview: t('.swipe-preview'), foot: t('.swipe-foot:not(.empty)'), acts: Math.round(document.querySelector('.swipe-actions').getBoundingClientRect().top + scrollY), cardEnd: Math.round(c.getBoundingClientRect().bottom + scrollY)};
    });
    must(read.head != null && (read.preview == null || read.head < read.preview) && (read.foot == null || (read.foot > read.head && (read.preview == null || read.foot > read.preview))), 'the phone card is not question, evidence, explanation: ' + JSON.stringify(read));
    // O-06: the phone's own list (Needs you · 1 of N) has no Compare and no ticks either
    await page.locator('.swipe-jump-all').click();
    const over = page.locator('.swipe-overview');
    await over.locator('.review-row').first().waitFor();
    must(await over.getByRole('button', {name:/Compare/}).count() === 0 && await over.locator('.review-tick-box').count() === 0, 'the phone list has Compare');
    await shot('phone-list');
    await over.getByRole('button', {name:'Close'}).click();
    await over.waitFor({state:'detached'});
    // the keyboard reaches the card before the list (W-036): the first stops inside the page are the switch and the card
    const firstStops = await page.evaluate(() => [...document.querySelectorAll('[data-key="review-layout"] :is(button,a[href],summary,[tabindex="0"])')].filter(n => n.offsetParent && !n.disabled).slice(0, 3).map(n => n.closest('[data-review-next]') ? 'list' : n.closest('[data-review-nav]') ? 'switch' : n.closest('#deck') ? 'card' : 'other'));
    must(firstStops[0] === 'switch' && firstStops.includes('card') && !firstStops.includes('list'), 'the keyboard meets the list before the card: ' + firstStops);
    // reflow at 320 px: no sideways scroll
    await page.setViewportSize({width:320, height:700});
    await page.waitForTimeout(200);
    const wide320 = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    must(wide320 <= 1, 'the page scrolls sideways at 320 px by ' + wide320);
    await page.setViewportSize(size);
    await side.locator('[data-review-row]').first().waitFor();

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
    }
  },
};
