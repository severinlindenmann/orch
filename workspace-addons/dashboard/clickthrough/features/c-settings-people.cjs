// Settings > People tab (ORCH-1161): turn the person list on, add Lea, give her Decide, rename her, try and
// remove her (Cancel, then Remove); each change survives a reload. The owner has no Remove. At the end the list
// file is moved away so later click-throughs see a workspace with one person, as before.
module.exports = {
  name: 'Settings People: turn on, add, rights, rename, remove',
  covers: ['page:settings/people', 'people.on', 'people.add', 'people.rights', 'people.rename', 'people.remove'],
  async run({ page, open, reload, act, must, python, workspace }) {
    const box = () => page.locator('#settings-panel-people');
    const seen = () => box().innerText();
    const row = name => box().locator('[data-key^="settings-people-row-"]').filter({ hasText: name });

    await open('#settings/general');
    await page.getByRole('tab', { name: 'People' }).click();  // its own tab (owner, 21 Nov)
    must(page.url().endsWith('#settings/people'), 'the People tab has no address of its own');
    await act('people.on', () => box().getByRole('button', { name: 'Turn on' }).click());
    await reload();
    must((await seen()).includes('Owner'), 'the owner is not listed after turning People on');
    must((await box().getByRole('button', { name: /^Remove/ }).count()) === 0, 'the owner can be removed');

    await box().getByRole('textbox', { name: 'Name of the new person' }).fill('Lea');
    await act('people.add', () => box().getByRole('button', { name: 'Add person' }).click());
    await reload();
    must(await row('Lea').getByRole('checkbox', { name: 'Write' }).isChecked(), 'a new person does not start with Write');
    must((await row('Lea').innerText()).includes('May write.'), 'the row does not say in words what Lea may do');
    must(!(await row('Lea').getByRole('checkbox', { name: 'Decide' }).isChecked()), 'a new person starts with Decide');

    await act('people.rights', () => row('Lea').getByRole('checkbox', { name: 'Decide' }).check());
    await reload();
    must(await row('Lea').getByRole('checkbox', { name: 'Decide' }).isChecked(), 'Decide did not stay after a reload');

    await row('Lea').getByRole('button', { name: 'Rename Lea' }).click();
    await box().getByRole('textbox', { name: 'New name for Lea' }).fill('Leana');
    await act('people.rename', () => box().getByRole('button', { name: 'Save' }).click());
    await reload();
    must((await seen()).includes('Leana'), 'the new name is not there after a reload');

    await row('Leana').getByRole('button', { name: 'Remove Leana' }).click();
    await box().getByRole('button', { name: 'Cancel' }).click();
    must((await row('Leana').count()) === 1, 'Cancel removed the person');
    await row('Leana').getByRole('button', { name: 'Remove Leana' }).click();
    await act('people.remove', () => box().getByRole('button', { name: 'Remove', exact: true }).click());
    await reload();
    must((await row('Leana').count()) === 0, 'the removed person still has a row');
    const gone = await page.locator('[data-key="settings-people-removed"]').innerText();
    must(gone.includes('Leana'), 'the removed person is not named under Removed');

    await python('import pathlib, sys; p = pathlib.Path(sys.argv[1]) / ".orch/local/people.json"; p.rename(p.with_name("people.json.ct-done"))', workspace);
  },
};
