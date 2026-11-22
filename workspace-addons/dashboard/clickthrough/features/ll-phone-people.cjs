// Settings > People > Phones (ORCH-1161, step 4): with the stand-in relay's one paired phone, the person turns
// People on, picks whose the phone is (it shows as theirs after a reload), then cuts it off (asks once in the
// row; after a reload it says cut off). At the end the people list is moved away again, so later
// click-throughs see a workspace with one person, as before.
module.exports = {
  name: 'Settings People: whose phone, cut off a lost phone',
  covers: ['people.tie', 'people.cut'],
  async run({ page, open, reload, act, must, orchAsPerson, python, workspace, standins, until }) {
    const r = standins.relay;
    orchAsPerson('addon', 'add', 'relay', '--yes');
    orchAsPerson('relay', 'connect', r.url, '--workspace', r.workspace, '--token', r.token);
    orchAsPerson('people', 'on', '--name', 'Anna');
    orchAsPerson('people', 'add', 'Lea');
    await open('#settings/people');
    await until(s => (s.settings?.people_list?.phones || []).length > 0, 'the paired phone shows under People');
    await reload();
    const phones = () => page.locator('[data-key="settings-people-phones"]');
    must((await phones().innerText()).includes('Not tied to anyone yet'), 'a new phone does not say it is not tied yet');

    const who = phones().locator('select').first();  // the native select under the design system's picker
    await act('people.tie', () => who.selectOption({ label: 'Lea' }));
    await reload();
    must((await phones().innerText()).includes('Lea’s phone'), 'the phone is not Lea’s after a reload');

    await phones().getByRole('button', { name: /^Cut off/ }).first().click();
    await phones().getByRole('button', { name: 'Cancel' }).click();
    must((await phones().innerText()).includes('Lea’s phone'), 'Cancel cut the phone off');
    await phones().getByRole('button', { name: /^Cut off/ }).first().click();
    await act('people.cut', () => phones().getByRole('button', { name: 'Cut off', exact: true }).click());
    await reload();
    must((await phones().innerText()).includes('Cut off. Also remove it on the relay admin page.'), 'the phone does not say it is cut off after a reload');

    await python('import pathlib, sys; p = pathlib.Path(sys.argv[1]) / ".orch/local/people.json"; p.rename(p.with_name("people.json.ct-phones"))', workspace);
  },
};
