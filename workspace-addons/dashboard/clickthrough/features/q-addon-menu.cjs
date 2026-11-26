// An add-on with its own page in the menu (Factory), turned on and off from Settings > Add-ons like a person on the
// first day (ORCH-897 clean e2e): Turn on in the confirm window puts Factory in the menu, and after a reload it is
// still there; the switch turns it off, and after a reload the menu entry is gone. An old Factory link then says
// the add-on is turned off and leads to its settings instead of an empty page.
module.exports = {
  name: 'Add-ons: a menu add-on comes and goes with its switch',
  covers: ['page:settings/addons', 'addon.set'],
  async run({ page, open, reload, act, must, text }) {
    const sw = () => page.locator('button[data-action="settings-addon"][data-name="factory"]');
    const menu = () => page.locator('a[href="#addon/factory"]');
    await open('#settings/addons');
    must((await sw().innerText()).trim() === 'Off', 'Factory should start off');
    must(await menu().count() === 0, 'Factory is in the menu while it is off');

    await sw().click();
    const dlg = page.locator('dialog[open]');
    await act('addon.set', () => dlg.getByRole('button', { name: 'Turn on' }).click());
    await menu().first().waitFor({ state: 'attached', timeout: 20000 })
      .catch(() => { throw new Error('Factory did not come into the menu after Turn on'); });
    await reload();
    must((await sw().innerText()).trim() === 'On', 'Factory is not on after a reload');
    must(await menu().count() > 0, 'Factory left the menu after a reload');

    await act('addon.set', () => sw().click());
    await reload();
    must((await sw().innerText()).trim() === 'Off', 'Factory is not off after a reload');
    must(await menu().count() === 0, 'Factory is still in the menu after it was turned off');

    await open('#addon/factory');
    const t = await text();
    must(/turned off/i.test(t), 'an old Factory link does not say the add-on is turned off:\n' + t.slice(0, 300));
    // the button names the add-on by its menu label (Factory, owner D3 B, ORCH-2284)
    await page.locator('[data-key="addon-off"] a[href="#settings/addons/factory"]').click();
    await page.waitForFunction(() => location.hash.startsWith('#settings/addons'), null, { timeout: 10000 })
      .catch(() => { throw new Error('"Open Factory settings" did not lead to Settings > Add-ons'); });
  },
};
