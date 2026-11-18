// Settings > About & updates: look at the page, turn "Update automatically" on, reload, it is still on, turn it off.
// The Update and Switch buttons are not pressed (they download and install); see the report.
module.exports = {
  name: 'Settings About: update automatically switch',
  covers: ['page:settings/about', 'update.auto'],
  async run({ page, open, reload, act, must }) {
    await open('#settings/about');
    const sw = page.locator('[data-key="settings-switch-auto-update"]');
    await sw.waitFor({ timeout: 30000 });  // the version check has answered
    const was = (await sw.getAttribute('aria-checked')) === 'true';
    await act('update.auto', () => sw.click());
    await reload();
    await sw.waitFor({ timeout: 30000 });
    must(((await sw.getAttribute('aria-checked')) === 'true') === !was, 'the automatic update switch did not stay flipped after a reload');
    await act('update.auto', () => sw.click());  // straight back: nothing may update by itself during these seconds
    await reload();
    await sw.waitFor({ timeout: 30000 });
    must(((await sw.getAttribute('aria-checked')) === 'true') === was, 'the automatic update switch did not go back');
  },
};
