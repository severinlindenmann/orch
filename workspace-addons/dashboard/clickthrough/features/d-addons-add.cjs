// Settings > Add-ons > Add add-ons (ORCH-1739, owner pick A): a person ticks Lessons in the pick list (installed here
// but off), presses "Add 1 add-on", reads what it may do and presses "Yes, add it". The dialog shows the run's steps
// and ends with "1 add-on is on"; after a reload Lessons' switch is on. The switch then turns it off again (addon.set,
// unchanged) so the next click-through starts from the same place.
module.exports = {
  name: 'Add-ons: add one from the pick list in one run',
  covers: ['addon.add'],
  async run({ page, open, reload, act, must, until }) {
    await open('#settings/addons');
    await page.locator('[data-key="settings-addon-catalog"]').click();
    const dlg = page.locator('dialog[open]');
    await dlg.locator('[data-key="catalog-pick-lessons"]').check();
    await dlg.getByRole('button', { name: 'Add 1 add-on' }).click();
    must((await dlg.innerText()).includes('This takes about a minute. orch restarts once at the end.'), 'the confirm step does not say what happens');
    await act('addon.add', () => dlg.getByRole('button', { name: 'Yes, add it' }).click());
    must(await dlg.locator('.run-steps').count() === 1, 'the dialog shows no steps after Yes, add it');
    await dlg.locator('h2', { hasText: '1 add-on is on' }).waitFor({ timeout: 240000 })
      .catch(async () => { throw new Error('the run did not end with "1 add-on is on":\n' + (await dlg.innerText()).slice(0, 400)); });
    await dlg.getByRole('button', { name: 'Close' }).click();
    await until(s => (s.addons || []).some(a => a.name === 'lessons'), 'Lessons on after the run');
    await reload();
    const sw = page.locator('button[data-action="settings-addon"][data-name="lessons"]');
    await sw.waitFor({ timeout: 20000 });
    must((await sw.innerText()).trim() === 'On', 'Lessons is not on after a reload');
    await act('addon.set', () => sw.click());
    await reload();
    must((await sw.innerText()).trim() === 'Off', 'Lessons is not off again after a reload');
  },
};
