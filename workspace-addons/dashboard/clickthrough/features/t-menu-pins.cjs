// The menu's add-ons and its open/close button (ORCH-1184, tidied by owner D2 A, ORCH-2283; O-34), like a person: no
// menu row edits the list ("Change this list" is gone). Way A: the quiet "…" beside Add-ons opens Settings › Menu;
// there a page moves up with its arrow or by dragging, and its switch sends it under "More (n)" and back; the menu
// follows at once and a reload keeps it. Way B (?menu=b): the same from the row's own "…" in the menu, and no Menu
// section in Settings. The button beside the orch name closes the menu to its icons, a reload keeps it closed, the
// button opens it again.
module.exports = {
  name: 'Menu: order and hide add-on pages (Settings or in place), More and Fewer, close and open the menu',
  covers: ['page:home'],
  async run({ page, base, open, reload, settle, must, addonOn, addonOff, until }) {
    await open('#home');
    addonOn('factory');   // the demo starts with no add-on in the menu
    addonOn('automation');
    await until(st => ['factory', 'automation'].every(n => (st.addons || []).some(a => a.name === n)), 'factory and automation on');
    await reload();
    const names = sel => page.locator(sel).evaluateAll(list => list.map(a => a.getAttribute('href').slice(7)));
    const inList = () => names('#side-addons nav[aria-label="Add-ons"] a[href^="#addon/"]');
    const underMore = () => names('#side-addons nav[aria-label="More add-ons"] a[href^="#addon/"]');
    const more = () => page.locator('#side-addons .nav-more');
    await page.locator('#side-addons nav[aria-label="Add-ons"] a[href="#addon/factory"]').waitFor({ timeout: 20000 }).catch(() => { throw new Error('Factory is not in the menu list'); });
    must(!(await page.locator('#side-menu').innerText()).includes('Change this list'), 'the menu still has the Change this list row');
    must(await page.locator('#side-addons :is(.nav-change,[data-pin])').count() === 0, 'the menu still carries the old edit controls');

    // Way A: "…" beside Add-ons opens Settings at its Menu section
    const edit = page.locator('#side-addons .nav-edit');
    must(await edit.getAttribute('aria-label') === 'Edit menu', 'no Edit menu beside Add-ons');
    await edit.focus();
    await page.keyboard.press('Enter');
    await settle();
    must(page.url().endsWith('#settings/menu'), 'Edit menu did not open Settings at the menu');
    const head = page.locator('#settings-menu');
    must(await head.isVisible() && await head.evaluate(n => document.activeElement === n), 'the Menu section did not take the keyboard position');
    const first = (await inList())[0], second = (await inList())[1];
    must(first && second, 'two add-on pages are needed in the menu');
    // the arrow: the second page goes first, in Settings and in the menu at once
    await page.locator('[data-key="settings-menu-up-' + second + '"]').click();
    must((await inList())[0] === second, 'Move up did not change the menu');
    must(await page.locator('.menu-order [data-menu-row]').first().getAttribute('data-menu-row') === second, 'Move up did not change the Settings list');
    must(await page.locator('[data-key="settings-menu-up-' + second + '"]').isDisabled(), 'the first page can still move up');
    await reload();
    must((await inList())[0] === second, 'the order is gone after a reload');
    // dragging: the first row onto the lower half of the second puts the old order back
    const rowBox = await page.locator('.menu-order [data-menu-row="' + first + '"]').boundingBox();
    await page.locator('.menu-order [data-menu-row="' + second + '"]').dragTo(page.locator('.menu-order [data-menu-row="' + first + '"]'), { targetPosition: { x: 80, y: rowBox.height - 4 } });
    must((await inList()).join() === [first, second].join(), 'dragging a row did not change the order');
    // the switch: off sends Factory under More, on brings it back (at the end)
    const sw = () => page.locator('[data-key="settings-menu-pin-factory"]');
    must(await sw().getAttribute('aria-checked') === 'true', 'Factory is in the menu but its switch is off');
    await sw().click();
    must(await sw().getAttribute('aria-checked') === 'false', 'the switch did not move Factory out of the menu');
    must(!(await inList()).includes('factory'), 'Factory is still in the menu');
    must(/^More \(\d+\)$/.test(await more().getAttribute('aria-label')), 'no More (n) once an add-on waits under it');
    await reload();
    must(!(await inList()).includes('factory') && !(await underMore()).includes('factory'), 'Factory came back into the menu after a reload');
    await more().click();
    must(await more().getAttribute('aria-expanded') === 'true' && await more().innerText() === 'Fewer', 'More did not unfold to Fewer');
    must((await underMore()).includes('factory'), 'Factory is not under More');
    await more().click();
    await sw().click();
    must((await inList()).includes('factory'), 'the switch did not put Factory back in the menu');

    // Way B: the menu itself. No "…" beside Add-ons, no Menu section in Settings; each row has its own "…"
    await page.goto(base + '/?menu=b#settings');
    await settle();
    must(await page.locator('#side-addons .nav-edit').count() === 0, 'way B still shows Edit menu beside Add-ons');
    must(await page.locator('[data-key="settings-menu"]').count() === 0, 'way B still shows the Menu section in Settings');
    const pick = async (name, word) => {
      await page.locator('#side-addons [data-key="nav-row-' + name + '"]').hover();
      await page.locator('[data-key="nav-row-more-' + name + '"]').click();
      await page.locator('[data-key="nav-row-menu-' + name + '"] .menu-item', { hasText: word }).click();
    };
    const top = (await inList())[0], next = (await inList())[1];
    await pick(next, 'Move up');
    must((await inList())[0] === next, 'Move up in the menu did not move the row');
    await pick(next, 'Move down');
    must((await inList())[0] === top, 'Move down in the menu did not move the row');
    await pick('factory', 'Hide from menu');
    must(!(await inList()).includes('factory') && (await underMore()).includes('factory'), 'Hide from menu did not put Factory under More, in sight');
    await reload();
    must(!(await inList()).includes('factory'), 'Factory came back after a reload');
    await pick('factory', 'Show in menu');
    must((await inList()).includes('factory'), 'Show in menu did not bring Factory back');
    await page.goto(base + '/?menu=a#home');   // way A again for the next click-through
    await settle();
    must(await page.locator('#side-addons .nav-edit').count() === 1, 'way A did not come back');

    const toggle = page.locator('#side-toggle');
    await toggle.click();
    must(await page.locator('.shell').getAttribute('data-side') === 'rail', 'Close menu did not close the menu');
    must(await toggle.getAttribute('aria-label') === 'Open menu', 'the closed menu button does not say Open menu');
    must(!(await page.locator('#side-nav .nav-label').first().isVisible()), 'the closed menu still shows its words');
    must(!(await page.locator('#side-addons .nav-edit').isVisible()), 'the closed menu still shows Edit menu');
    await reload();
    must(await page.locator('.shell').getAttribute('data-side') === 'rail', 'the menu opened again after a reload');
    await page.locator('#side-toggle').click();
    must(await page.locator('.shell').getAttribute('data-side') === null, 'Open menu did not open the menu');
    must(await page.locator('#side-nav .nav-label').first().isVisible(), 'the opened menu shows no words');
    await addonOff('factory');   // off again for the next click-through
    await addonOff('automation');
  },
};
