// The Documentation page (ORCH-735): the book icon next to Settings opens the overview (three layers, Start here);
// a tile opens its page with the page list at the left, the flow and Under the hood (commands with Copy, live facts);
// an add-on that is off here is still readable and says Off; the way back is the Documentation link. A reload of a
// page's own address shows the same page.
module.exports = {
  name: 'Documentation: the book icon opens the overview, a page shows its flow and commands, Back returns',
  covers: ['page:docs'],
  async run({ page, open, reload, must, text }) {
    await open('#home');
    await page.locator('#side-settings a[href="#docs"]').click();
    await page.waitForFunction(() => location.hash === '#docs');
    await page.waitForSelector('.ui-docs .dl-tile');
    const overview = await text();
    must(overview.includes('Start here') && overview.includes('After you make a ticket'), 'the overview has no Start here entry');
    must(overview.includes('Turn on when needed') && overview.includes('Add-ons'), 'the overview misses a layer');
    must(overview.includes('This workspace now'), 'the overview shows no live facts');
    await page.locator('.ui-docs .dl-start .dl-link').click();
    await page.waitForFunction(() => location.hash === '#docs/new-ticket');
    await page.waitForSelector('.ui-docs .dh');
    const one = await text();
    must(one.includes('orch picks the model'), 'the new-ticket page shows no flow');
    must(one.includes('Under the hood') && one.includes('orch ticket new'), 'the page shows no commands');
    must(await page.locator('.ui-docs .sl-item[aria-current="page"]').count() === 1, 'the page list does not mark the page');
    await reload();
    await page.waitForSelector('.ui-docs .dh');
    must((await text()).includes('After you make a ticket'), 'a reload of the page address lost the page');
    await page.locator('.ui-docs .sl-item[href="#docs/focus"]').click();
    await page.waitForFunction(() => location.hash === '#docs/focus' && document.querySelector('.ui-docs h1')?.textContent === 'Live');
    const self = await page.locator('.ui-docs .dh-live').innerText();
    must(/This add-on\s*Off/.test(self), `an add-on that is off here does not say Off on its page: ${self}`);
    await page.locator('.ui-docs .dp-back').click();
    await page.waitForFunction(() => location.hash === '#docs');
    await page.waitForSelector('.ui-docs .dl-tile');
  },
};
