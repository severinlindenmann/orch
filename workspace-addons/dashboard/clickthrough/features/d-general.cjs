// Settings > General: a person turns "Tell teammates about orch" on and off, picks how helpers get their own
// copies (when, how many, what runs in a new copy), cleans up copies, and each choice is still there after a reload.
module.exports = {
  name: 'Settings: share with the team and separate copies',
  covers: ['page:settings/general', 'share.set', 'copies.set', 'copies.clean'],
  async run({ page, open, reload, act, must }) {
    await open('#settings/general');
    const share = () => page.locator('[data-key="settings-switch-share"]');
    must((await share().getAttribute('aria-checked')) === 'false', 'sharing should start off');
    await share().click();
    await act('share.set', () => page.locator('[data-key="settings-review-ok"]').click());
    await reload();
    must((await share().getAttribute('aria-checked')) === 'true', 'sharing is not on after a reload');
    await share().click();
    await act('share.set', () => page.locator('[data-key="settings-review-ok"]').click());
    await reload();
    must((await share().getAttribute('aria-checked')) === 'false', 'sharing is not off after a reload');

    await act('copies.set', () => page.locator('[data-key="settings-copies-always"]').click());
    await act('copies.set', () => page.locator('[data-key="settings-copies-max"]').selectOption('5'));
    await page.locator('[data-key="settings-copy-setup-edit"]').click();
    await page.locator('[data-key="settings-copy-setup"]').fill('true');
    await act('copies.set', () => page.locator('[data-key="settings-copy-setup-save"]').click());
    await reload();
    must((await page.locator('[data-key="settings-copies-always"]').getAttribute('aria-checked')) === 'true', 'the copies mode is not kept');
    must((await page.locator('[data-key="settings-copies-max"]').inputValue()) === '5', 'the copies number is not kept');
    must((await page.locator('.copies-setup-view').innerText()).includes('true'), 'the command for a new copy is not kept');

    await page.locator('[data-key="settings-copies-clean"]').click();
    await act('copies.clean', () => page.locator('[data-key="settings-review-ok"]').click());
    await reload();
    must((await page.locator('[data-key="settings-copies-disk"]').innerText()).includes('Copies on this computer'), 'the copies card is gone');
  },
};
