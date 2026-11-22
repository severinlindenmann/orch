// The Sync page against the real server, signed in once (ORCH-386): turn the Sync add-on on in Settings > Add-ons,
// open the Sync page, and its status call (the one that answered 403 after a reused sign-in link, ORCH-382) must
// go through; a reload asks again and goes through again. Then Sync is turned off so later click-throughs see the
// seeded workspace as it was. The browser context signed in with ONE launch token, as a person does.
// Since ORCH-413 the page reads that status with GET /api/addon-read (not POST /api/act addon.act), so wait for it.
const statusRead = (page, fn) => Promise.all([
  page.waitForResponse(r => r.request().method() === 'GET' && r.url().includes('/api/addon-read?addon=sync&verb=status'), { timeout: 60000 }),
  fn(),
]).then(([r]) => r);

module.exports = {
  name: 'Sync page: opens signed in, its status call is not refused',
  covers: ['addon.set'],
  async run({ page, open, reload, act, must, text, orchAsPerson }) {
    await open('#settings/addons');
    const sw = () => page.getByRole('switch', { name: 'Backup on or off' });
    must((await sw().innerText()).trim() === 'Off', 'Sync should start off');
    await sw().click();
    const dlg = page.locator('dialog[open]');
    await act('addon.set', () => dlg.getByRole('button', { name: 'Turn on' }).click());
    const first = await statusRead(page, () => open('#addon/sync'));
    must(first.status() === 200, `the Sync page's status call answered ${first.status()}`);
    must(/Sync/.test(await text()), 'the Sync page shows no Sync card');
    const again = await statusRead(page, () => reload());
    must(again.status() === 200, `the Sync page's status call answered ${again.status()} after a reload`);
    // a copy on this computer only (ORCH-896): pick it, Save, reload: it is on; then Off, Save: it is off again
    await page.getByText('On this computer only').first().click();
    await page.getByRole('button', { name: 'Save' }).click();
    await page.getByText(/Last synced|Synced/).first().waitFor({ timeout: 30000 })
      .catch(async () => { throw new Error('Sync on this computer did not start:\n' + (await text()).slice(0, 400)); });
    await reload();
    must(/Sync: local/.test(orchAsPerson('sync', 'status')), 'Sync is not on this computer after Save: ' + orchAsPerson('sync', 'status'));
    await page.getByText(/^Off$/).first().click();
    await page.getByRole('button', { name: 'Save' }).click();
    await page.waitForTimeout(1500);
    await reload();
    must(/Sync is off/.test(orchAsPerson('sync', 'status')), 'Sync is not off after Save: ' + orchAsPerson('sync', 'status'));
    await open('#settings/addons');
    await act('addon.set', () => sw().click());
    await reload();
    must((await sw().innerText()).trim() === 'Off', 'Sync is not off again after a reload');
  },
};
