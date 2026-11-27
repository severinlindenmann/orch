// ORCH-576: a person clicks "Part of: …" on a board tile and sees that ticket and every ticket inside it, then goes
// back to all tickets; a parent tile opens the list of its parts in place.
module.exports = {
  name: 'Tickets: a ticket and all its parts on the board',
  covers: ['page:tickets'],
  async run({ page, open, must, orchAsPerson }) {
    const id = (...w) => { const out = orchAsPerson(...w, '--json'); try { return JSON.parse(out).id; } catch (e) { return (out.match(/t_[a-z0-9]+/) || [])[0]; } };
    const epic = id('ticket', 'new', 'Spring newsletter', '--epic');
    id('ticket', 'new', 'Write the intro', '--parent', epic);
    id('ticket', 'new', 'Pick the pictures', '--parent', epic);
    await open('#tickets');
    await page.getByRole('button', { name: 'Board', exact: true }).click();
    const partOf = page.locator('.tile-part-of').first();
    await partOf.waitFor({ timeout: 15000 }).catch(() => {});
    const all = await page.locator('.status-row .ticket-tile').count();
    must(await partOf.count() === 1, 'no tile says "Part of: …" on the demo board');
    await partOf.click();
    const bar = page.locator('.scope-bar');
    await bar.waitFor();
    must(/Parts of/.test(await bar.innerText()), 'the scope bar does not say "Parts of"');
    const scoped = await page.locator('.status-row .ticket-tile').count();
    must(scoped > 0 && scoped < all, 'the scoped board does not show only the family (' + scoped + ' of ' + all + ')');
    await page.getByRole('button', { name: 'Back to all tickets' }).click();
    must(await page.locator('.scope-bar').count() === 0, 'Back to all tickets left the scope bar');
    // ORCH-2153: the board re-renders after Back; wait for the tiles instead of counting at once
    const back = await page.waitForFunction((n) => document.querySelectorAll('.status-row .ticket-tile').length === n,
      all, { timeout: 15000 }).then(() => true, () => false);
    must(back, 'not every tile came back');
    const bars = page.locator('.ticket-tile .parts-bar');
    if (await bars.count()) {
      await bars.first().click();
      const opened = await page.locator('.tile-parts .tile-part').first().waitFor({ timeout: 15000 }).then(() => true, () => false);
      must(opened, 'the parts list did not open in the tile');
    }
  },
};
