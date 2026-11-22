// Ticket page layout fits (report r-1122-0538, ORCH-1466): a long title on a ticket that waits for a start on Opus
// (Start helper with its caret, Continue on Sonnet, Start in Focus, Open chat, the ⋯ menu) is shown whole at 1280
// (not cut by the buttons beside it); every tab of the tab row fits at 390 without scrolling; a long Done when in
// Properties reads as normal lines across the rail, not a column of two words; What was asked has no empty gap
// under its heading.
const idOf = out => (/\[(t_[A-Za-z0-9]+)\]/.exec(out) || [])[1];

module.exports = {
  name: 'Ticket page: long title, tabs at 390, Done when and What was asked fit',
  covers: ['ticket.model'],
  async run({ page, open, act, must, orch, shot }) {
    const title = 'Spring catalogue for the shops: new photos, prices and texts for every product, checked by both teams';
    const tid = idOf(orch('ticket', 'new', title));
    orch('ticket', 'tidy', tid, title,
      '--description', 'A new spring catalogue: fresh photos, the new prices and short texts for each product, ready for print and the web shop.',
      '--done-when', 'Every product has a new photo, the new price and a short text; the sales team and the shop team both read the whole catalogue and said yes; the print file and the web shop pages show the same prices');
    for (let i = 1; i <= 7; i++) orch('check', 'add', tid, 'Step number ' + i);
    for (let i = 0; i < 12; i++) orch('ticket', 'summary', tid, 'Progress line ' + i);

    await page.setViewportSize({ width: 1280, height: 900 });
    await open('#ticket/' + tid);
    const strip = page.locator('[data-key="ticket-strip-' + tid + '"]');
    await strip.waitFor();
    // the person picks Opus (a helper may not): the start then offers the same start on Sonnet beside it
    await page.locator('[data-key="props-add-' + tid + '"] > summary').click();
    await page.locator('[data-key="prop-add-model-' + tid + '"]').click();
    await act('ticket.model', () => page.locator('[data-key="model-' + tid + '"]').selectOption('opus'));
    await page.locator('[data-key="ticket-start-cheaper"]').waitFor();
    const fit = await page.evaluate(id => {
      const h1 = document.querySelector('[data-key="ticket-strip-' + id + '"] h1');
      const ed = h1.querySelector('.ed-title,.ed') || h1;
      const dd = document.querySelector('[data-key="prop-done-when-' + id + '"] dd');
      const brief = document.querySelector('[data-key="brief"]');
      const head = brief.querySelector('.section-head').getBoundingClientRect();
      const next = [...brief.children].slice(1).find(e => e.getBoundingClientRect().height > 0);
      return { clipped: ed.scrollHeight > ed.clientHeight + 1, titleWidth: h1.getBoundingClientRect().width, ddWidth: dd.getBoundingClientRect().width,
        rail: dd.closest('aside').getBoundingClientRect().width,
        gap: next ? next.getBoundingClientRect().top - head.bottom : 0 };
    }, tid);
    await shot('header-1280', strip);
    await shot('asked-1280', page.locator('[data-key="brief"]'));
    const bad = [];
    const want = (ok, why) => { if (!ok) bad.push(why); };
    want(!fit.clipped, 'at 1280 the ticket title is cut by the buttons beside it');
    // however many buttons sit beside it (Start in Focus too when Focus is on), the title keeps its 360 px
    want(fit.titleWidth >= 350, `at 1280 the title has only ${Math.round(fit.titleWidth)} px beside the buttons`);
    want(fit.ddWidth >= fit.rail * 0.7, `at 1280 Done when is a narrow column (${Math.round(fit.ddWidth)} of ${Math.round(fit.rail)} px)`);
    want(fit.gap <= 16, `What was asked has an empty gap of ${Math.round(fit.gap)} px under its heading`);

    await page.setViewportSize({ width: 390, height: 844 });
    const tabs = page.locator('.ticket-tabs');
    await tabs.waitFor();
    const over = await tabs.evaluate(e => e.scrollWidth - e.clientWidth);
    await shot('tabs-390', strip);
    want(over <= 1, `at 390 the tab row is ${over} px too wide: the last tab is cut`);
    const phone = await page.evaluate(id => {
      const strip = document.querySelector('[data-key="ticket-strip-' + id + '"]');
      const ed = strip.querySelector('h1 .ed-title,h1 .ed') || strip.querySelector('h1');
      const left = sel => Math.round(strip.querySelector(sel)?.getBoundingClientRect().left ?? -1);
      return { lines: Math.round(ed.clientHeight / parseFloat(getComputedStyle(ed).lineHeight)),
        start: left('[data-key="ticket-start-pick"]'), chat: left('.ticket-strip-actions > a, .ticket-strip-actions > button') };
    }, tid);
    want(phone.lines >= 3, `at 390 the title shows only ${phone.lines} lines`);
    want(Math.abs(phone.chat - phone.start) <= 2, `at 390 the buttons do not start at one left edge (${phone.start} and ${phone.chat} px)`);
    await page.setViewportSize({ width: 1280, height: 900 });
    must(!bad.length, bad.join('; '));
  },
};
