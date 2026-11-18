// Settings > Add-ons: a person turns the Shared links add-on on (confirms the question), reloads and sees it on,
// then turns it off again and sees it off after a reload. Shared links is part of orch, so nothing is downloaded.
module.exports = {
  name: 'Add-ons: turn Shared links on and off',
  covers: ['page:settings/addons', 'addon.set'],
  async run({ page, open, reload, act, must, text }) {
    await open('#settings/addons');
    const sw = () => page.locator('button[data-action="settings-addon"][data-name="publish"]');
    must((await sw().innerText()).trim() === 'Off', 'Shared links should start off');
    await sw().click();
    const dlg = page.locator('dialog[open]');
    await act('addon.set', () => dlg.getByRole('button', { name: 'Turn on' }).click());
    await reload();
    must((await sw().innerText()).trim() === 'On', 'Shared links is not on after a reload');
    await act('addon.set', () => sw().click());
    await reload();
    must((await sw().innerText()).trim() === 'Off', 'Shared links is not off after a reload');
    must((await text()).includes('Installed add-ons'), 'the add-ons list is missing');
  },
};
