// The menu's add-ons and its open/close button (ORCH-1184), like a person: unpin an add-on, it moves under
// "Show more (n)"; Show more unfolds it, Pin brings it back; after a reload the choice is still there. The button
// beside the orch name closes the menu to its icons, a reload keeps it closed, the button opens it again.
module.exports = {
  name: 'Menu: pin add-ons, Show more, close and open the menu',
  covers: ['page:home'],
  async run({ page, open, reload, must, addonOn, addonOff, until }) {
    await open('#home');
    addonOn('factory');   // the demo starts with no add-on in the menu
    await until(st => (st.addons || []).some(a => a.name === 'factory'), 'factory on');
    await reload();
    const pinned = page.locator('#side-addons nav[aria-label="Pinned add-ons"] .nav-row');
    await pinned.first().waitFor({ timeout: 20000 })
      .catch(() => { throw new Error('the menu shows no pinned add-on'); });
    const first = pinned.first(), name = await first.locator('[data-pin]').getAttribute('data-pin');
    const row = () => page.locator(`#side-addons [data-pin="${name}"]`);
    const more = () => page.locator('#side-addons .nav-more');

    await first.hover();
    await row().click();
    must(await row().count() === 0, `${name} is still in the menu after Unpin`);
    must(/^Show more \(\d+\)$/.test(await more().getAttribute('aria-label')), 'no Show more after an add-on was unpinned');
    must(await page.evaluate(() => document.activeElement?.classList.contains('nav-more')), 'the keyboard did not land on Show more');
    await reload();
    must(await row().count() === 0, `${name} came back into the menu after a reload`);

    await more().click();
    must(await more().getAttribute('aria-expanded') === 'true', 'Show more did not unfold');
    must(await row().getAttribute('aria-pressed') === 'false', `${name} under Show more is not shown unpinned`);
    await row().click();
    must(await row().getAttribute('aria-pressed') === 'true', `Pin did not pin ${name}`);
    await reload();
    must(await page.locator(`#side-addons nav[aria-label="Pinned add-ons"] [data-pin="${name}"]`).count() === 1, `${name} is not pinned after a reload`);

    const toggle = page.locator('#side-toggle');
    await toggle.click();
    must(await page.locator('.shell').getAttribute('data-side') === 'rail', 'Close menu did not close the menu');
    must(await toggle.getAttribute('aria-label') === 'Open menu', 'the closed menu button does not say Open menu');
    must(!(await page.locator('#side-nav .nav-label').first().isVisible()), 'the closed menu still shows its words');
    await reload();
    must(await page.locator('.shell').getAttribute('data-side') === 'rail', 'the menu opened again after a reload');
    await page.locator('#side-toggle').click();
    must(await page.locator('.shell').getAttribute('data-side') === null, 'Open menu did not open the menu');
    must(await page.locator('#side-nav .nav-label').first().isVisible(), 'the opened menu shows no words');
    await addonOff('factory');   // off again for the next click-through
  },
};
