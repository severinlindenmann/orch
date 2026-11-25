// Home (ORCH-1849): a ticket finished today is named once, in Finished, with its result right under the title, on the
// phone and on the desktop; What changed never repeats it, and the title still opens the ticket.
const idOf = out => (/\[(t_[A-Za-z0-9]+)\]/.exec(out) || [])[1];

module.exports = {
  name: 'Home: a finished ticket says its result once, at its first mention',
  covers: ['page:home'],
  async run({ page, open, reload, must, orch, orchAsPerson, shot }) {
    const id = idOf(orch('ticket', 'new', 'Monthly sales report for November'));
    orch('check', 'add', id, 'Collect the numbers');
    orch('check', 'done', id, 'c1', '--summary', 'Sales up 5% on October.', '--note', 'From the shop export.');
    orchAsPerson('ticket', 'status', id, 'done');  // a person closes it (a helper's done goes to Review)
    for (const [width, height] of [[390, 844], [1440, 800]]) {
      await page.setViewportSize({ width, height });
      await open('#home');
      const row = page.locator(`[data-key="finished-today"] [data-key="ticket-${id}"]`);
      await reload();
      await row.waitFor({ timeout: 15000 });
      const said = await row.innerText();
      must(/Sales up 5% on October\. From the shop export\./.test(said), `at ${width} the Finished row has no result: ` + said);
      must(!/No result written/.test(said), `at ${width} a row with a result says none was written: ` + said);
      const repeats = await page.locator(`[data-key="changed-${id}"]`).count();
      must(repeats === 0, `at ${width} What changed repeats the ticket finished today`);
      const mentions = await page.locator('main').evaluate(m => m.innerText.split('Sales up 5% on October').length - 1);
      must(mentions === 1, `at ${width} the result is said ${mentions} times on Home`);
      await shot('finished-' + width, row);
    }
    await page.locator(`[data-key="finished-today"] [data-key="ticket-${id}"] h3 a`).click();
    await page.waitForURL(new RegExp('#ticket/'));
    await page.setViewportSize({ width: 1280, height: 900 });
  },
};
